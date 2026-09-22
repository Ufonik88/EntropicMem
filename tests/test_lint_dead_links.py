"""Regression: dead-link lint must not depend on note iteration order.

``cmd_lint`` used to accumulate known note ids inside the same loop that
validated wikilinks. A link written as a note id (``Domain/File``) therefore
resolved only when the target note happened to be iterated *before* the linking
note. Because ``Vault.list_notes`` returns sorted paths, that made the result
deterministic but wrong: every note sorting before the target was reported as a
dead link, while later notes linking the same target were not.

The vault in this test reproduces that shape — the link target sorts last and
its frontmatter title differs from its note id, so the link can only resolve via
the id set.
"""

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins" / "entropicmem" / "scripts"))

import entropicmem  # noqa: E402


def _write_note(root: Path, rel: str, title: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    path.write_text(
        "---\n"
        f"title: {title}\n"
        "domain: Knowledge\n"
        "type: note\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        "tags: []\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )


def _lint_args() -> SimpleNamespace:
    return SimpleNamespace(pii=False)


def test_link_to_later_sorted_note_id_is_not_a_dead_link(tmp_path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    _write_note(
        vault,
        "Knowledge/A-Linker.md",
        "A Linker",
        "Body text long enough to clear the stub threshold for lint. "
        "See [[Knowledge/Z-Target]] for the full detail.",
    )
    _write_note(
        vault,
        "Knowledge/Z-Target.md",
        "Zed Target",
        "Target body text, comfortably longer than fifty characters so it is not a stub.",
    )

    monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", str(vault))
    monkeypatch.setenv("ENTROPICMEM_INDEX_DB", str(tmp_path / "index.db"))

    rc = entropicmem.cmd_lint(_lint_args())
    out = capsys.readouterr().out

    assert "dead-link" not in out, f"link target was treated as dead: {out}"
    assert rc == 0, out


def test_same_target_is_consistently_resolved_from_either_sort_position(tmp_path, monkeypatch, capsys):
    """Both the early- and late-sorting linker must agree the target exists."""
    vault = tmp_path / "vault"
    link = "See [[Knowledge/M-Target]] for the full detail, written out long enough."
    _write_note(vault, "Knowledge/A-Linker.md", "A Linker", f"Body text. {link}")
    _write_note(
        vault,
        "Knowledge/M-Target.md",
        "Em Target",
        "Target body text, comfortably longer than fifty characters so it is not a stub.",
    )
    _write_note(vault, "Knowledge/Z-Linker.md", "Z Linker", f"Body text. {link}")

    monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", str(vault))
    monkeypatch.setenv("ENTROPICMEM_INDEX_DB", str(tmp_path / "index.db"))

    rc = entropicmem.cmd_lint(_lint_args())
    out = capsys.readouterr().out

    assert "dead-link" not in out, f"same link resolved differently by position: {out}"
    assert rc == 0, out
