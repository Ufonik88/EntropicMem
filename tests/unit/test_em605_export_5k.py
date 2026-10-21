"""EM-605 slice 2.5 — the 5,000-node export AC, and the body read it exposed.

The card asked for a generated 5k-node fixture, the time **and** the output size
recorded, and the budget set only after measuring. Measuring first found the
real cost: ``VaultIndex.get_graph_nodes`` joined ``notes_fts`` and read every
note's **full body**, and the payload discards it unless ``include_bodies`` is
on — so an ordinary 5k export spent 3.2 s of its 4.1 s reading text it threw
away. That is what this file pins:

* the loader reads bodies only when the export asks for them (the contract,
  which fails first);
* a 5k-node export stays inside a generous, measured budget for both renderers,
  and inside a size ceiling that an accidental body inclusion would break (the
  bodies in this fixture are 2 KB each, so leaking them would roughly
  quadruple the file).

The measured figures are printed on every run (one warning line, like the other
ACs in this suite) so a drift is visible before the ceiling trips. Rules for the
fixture: invented data only, and the bodies are filler.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.graph.export import export_html, export_json  # noqa: E402
from em_internal.index import VaultIndex  # noqa: E402
from em_internal.vault import Vault  # noqa: E402

#: The AC's node count (the card's 5k).
NODES = 5_000

#: Body length per note: long enough that an accidental body inclusion is
#: visible in the output size, short enough to keep the fixture quick.
BODY_CHARS = 900

#: The budget, set **after** measuring, in the machine-independent form this
#: repo uses for timing ACs: an export costs at most **half the index build of
#: the same vault**, with a 3 s floor so a very fast box cannot make the budget
#: absurd and a 15 s cap so a pathological build cannot hide a pathological
#: export. Measured here: build ~6.7 s, each renderer ~1.1 s (0.16x). Before the
#: body read was fixed the export measured ~7.7 s (1.15x) and would fail.
EXPORT_SHARE_OF_BUILD = 0.5
EXPORT_FLOOR_MS = 3_000.0
EXPORT_CEILING_MS = 15_000.0

#: Size ceilings at 5k nodes. Measured ~2.9 MB (JSON) / ~2.6 MB (HTML). The
#: fixture's 900-char bodies plus previews would add ~7 MB if the default
#: export ever embedded vault content.
MAX_JSON_BYTES = 8_000_000
MAX_HTML_BYTES = 8_000_000


def _filler(chars: int) -> str:
    line = "Filler sentence about the Acme rollout and its Widget milestones. "
    return (line * (chars // len(line) + 1))[:chars]


def _build_vault(root: Path, count: int) -> Vault:
    """``count`` notes, each linking to the next and to the first.

    Two wikilink edges per note, so the export has ``2 * count`` edges and no
    isolated node — a graph the viewer would actually draw.
    """
    (root / "Knowledge").mkdir(parents=True, exist_ok=True)
    body = (
        '---\ntitle: Note {i}\ntype: permanent\ncreated: "2026-01-02"\n'
        'updated: "2026-01-02"\nagent: true\n---\n\n'
        "Links: [[Note {next}]] and [[Note 0]].\n\n{text}\n"
    )
    text = _filler(BODY_CHARS)
    for i in range(count):
        (root / "Knowledge" / f"Note {i}.md").write_text(
            body.format(i=i, next=(i + 1) % count, text=text), encoding="utf-8"
        )
    return Vault(root)


@pytest.fixture(scope="module")
def small_index(tmp_path_factory):
    """One note whose body is longer than the 500-char ``body_preview``."""
    root = tmp_path_factory.mktemp("small") / "vault"
    (root / "Knowledge").mkdir(parents=True)
    (root / "Knowledge" / "Alpha.md").write_text(
        '---\ntitle: Alpha\ntype: permanent\n---\n\n' + _filler(900) + "\n",
        encoding="utf-8",
    )
    index = VaultIndex(root.parent / "index.db")
    index.rebuild(Vault(root))
    yield index
    index.close()


def test_the_loader_reads_bodies_only_when_the_export_asks(small_index):
    """The default read is metadata; the modal asks for the body explicitly."""
    plain = small_index.get_graph_nodes(max_nodes=10)
    assert len(plain) == 1
    asked = small_index.get_graph_nodes(max_nodes=10, include_bodies=True)

    assert asked[0]["full_body"].startswith("Filler sentence")
    assert len(asked[0]["full_body"]) > len(asked[0]["body_preview"])
    assert plain[0]["full_body"] == plain[0]["body_preview"], (
        "without include_bodies the loader must report the preview it already "
        "has, not read every note's body out of the FTS table"
    )


def test_the_json_export_asks_the_loader_for_bodies_when_bodies_are_requested(
    small_index, tmp_path
):
    """``--include-bodies`` must reach the loader, not just the HTML shell.

    The empty-modal bug this guards: ``export_html`` fills bodies from the vault
    even when the payload behind ``graph.json`` never had them, so the HTML
    looks right while the JSON beside it is body-less. ``meta.include_bodies``
    is not evidence either — it is the model's own claim, and a dropped flag
    makes it agree with the wrong answer.
    """
    payload = export_json(
        small_index, tmp_path / "graph.json", include_bodies=True
    )
    node = payload["nodes"][0]
    assert payload["meta"]["include_bodies"] is True
    assert node["full_body"].startswith("Filler sentence")
    assert len(node["full_body"]) > len(node["body_preview"]), (
        "the full body must come from the index, not from the 500-char preview"
    )
    written = json.loads((tmp_path / "graph.json").read_text(encoding="utf-8"))
    assert written["nodes"][0]["full_body"] == node["full_body"]


def test_a_five_thousand_node_export_meets_its_measured_budget(tmp_path):
    import time
    import warnings

    root = tmp_path / "vault"
    vault = _build_vault(root, NODES)
    index = VaultIndex(tmp_path / "index.db")
    try:
        started = time.perf_counter()
        assert index.rebuild(vault) == NODES
        build_ms = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        payload = export_json(index, tmp_path / "graph.json", max_nodes=NODES)
        json_ms = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        export_html(index, tmp_path / "graph.html", max_nodes=NODES)
        html_ms = (time.perf_counter() - started) * 1000.0

        json_bytes = (tmp_path / "graph.json").stat().st_size
        html_bytes = (tmp_path / "graph.html").stat().st_size
    finally:
        index.close()

    # Note 0's self-link and its duplicate link from the last note collapse,
    # so "about two per node" is the exact fixture shape.
    assert len(payload["nodes"]) == NODES
    assert 2 * NODES - 2 <= len(payload["edges"]) <= 2 * NODES
    assert payload["meta"]["include_bodies"] is False
    assert all(
        "full_body" not in node and "body_preview" not in node
        for node in payload["nodes"]
    ), "the default export embeds no vault content"

    budget_ms = min(
        max(EXPORT_FLOOR_MS, build_ms * EXPORT_SHARE_OF_BUILD), EXPORT_CEILING_MS
    )
    warnings.warn(
        f"[export 5k] index build {build_ms:.0f} ms; json {json_ms:.0f} ms / "
        f"{json_bytes} B, html {html_ms:.0f} ms / {html_bytes} B "
        f"(budget {budget_ms:.0f} ms = max({EXPORT_FLOOR_MS:.0f}, "
        f"{EXPORT_SHARE_OF_BUILD:.0%} of build), ceiling {MAX_JSON_BYTES} B each)",
        stacklevel=1,
    )

    assert json_ms < budget_ms, f"json export took {json_ms:.0f} ms of {budget_ms:.0f}"
    assert html_ms < budget_ms, f"html export took {html_ms:.0f} ms of {budget_ms:.0f}"
    assert json_bytes < MAX_JSON_BYTES, f"graph.json is {json_bytes} bytes"
    assert html_bytes < MAX_HTML_BYTES, f"graph.html is {html_bytes} bytes"
