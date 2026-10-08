"""P0c — the shadow **collector**: real engines, real copy, and no live write.

The collector exists because the promotion observable needs 200 turns and a dev box
has none. Its claims are exactly the ones that would otherwise rot silently:

* **the store it reads is never written** (repo rule 3) — asserted on bytes and mtime,
  not by reading the code for a `mode=ro`;
* **the ids on each line come from the real v2 engine** — a stub returning ``[]`` would
  make every sample "no signal" and still exit 2, so the property is tested by seeding
  facts and requiring non-empty ``v2_ids`` that match the engine's own answer;
* **the sample is readable by the real reporter** — writer and reader schema coupling;
* **``_shadow`` loads without the Hermes host** — the collector deliberately bypasses
  ``plugins/entropicmem/__init__.py`` (which imports ``agent.memory_provider``), and a
  relative import added inside ``_shadow.py`` would break it with no other symptom;
* **the process env it borrows is given back.**

Invented data only (rule 4). Everything runs in a temp directory.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugins" / "entropicmem"
SCRIPTS = PLUGIN / "scripts"
COLLECTOR = REPO / "scripts" / "shadow_collect.py"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


collect = _load(COLLECTOR, "_shadow_collect_under_test")
shadow = _load(PLUGIN / "_shadow.py", "_shadow_for_collect_tests")

from memory_engine import MemoryEngine  # noqa: E402

FACTS = (
    "the staging server runs on port 9090",
    "the nightly billing job is owned by Bob Example",
    "Initech rotates api credentials every ninety days",
    "Globex keeps its staging cluster in the Frankfurt region",
)


@pytest.fixture()
def live_store(tmp_path):
    """A real v2 store with four invented facts. It is the *source*: read-only."""
    path = tmp_path / "live" / "memory.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = MemoryEngine(path, profile_id="default")
    for fact in FACTS:
        engine.remember(fact)
    engine.close()
    return path


# --- the rule that matters most -------------------------------------------


def test_the_collector_never_writes_the_store_it_reads(live_store, tmp_path):
    before = (live_store.read_bytes(), live_store.stat().st_mtime_ns)

    code = collect.main(["--source", str(live_store), "--turns", "8", "--out", str(tmp_path / "out")])
    assert code in (0, 1, 2), "the run must finish with a verdict, whatever it concludes"

    assert (live_store.read_bytes(), live_store.stat().st_mtime_ns) == before, (
        "the source store moved — the collector would be writing to a real profile"
    )


def test_the_collector_refuses_a_source_that_is_not_there(tmp_path):
    with pytest.raises(SystemExit):
        collect.collect(source=tmp_path / "nope.db", turns=1, out=tmp_path / "out", profile="default")


# --- the numbers come from the real engines -------------------------------


def test_the_v2_ids_come_from_the_real_engine_not_from_a_stub(live_store, tmp_path):
    """A collector whose `v2_ids` returned `[]` would still exit 2 with "no signal" and
    look like a clean plumbing run. So the ids must be shown to arrive."""
    out = tmp_path / "out"
    log = collect.collect(source=live_store, turns=8, out=out, profile="default")

    lines = [json.loads(raw) for raw in log.read_text(encoding="utf-8").splitlines() if raw.strip()]
    assert len(lines) == 8
    injected = [line for line in lines if line["v2_ids"]]
    assert injected, "a store with four matching facts cannot produce a single injection"

    engine = MemoryEngine(live_store, profile_id="default")
    try:
        for line in injected[:3]:
            assert collect.v2_ids(engine, line["query"]) == line["v2_ids"]
    finally:
        engine.close()


def test_the_sample_the_collector_writes_is_readable_by_the_reporter(live_store, tmp_path):
    out = tmp_path / "out"
    log = collect.collect(source=live_store, turns=6, out=out, profile="default")

    report = shadow.report(log)
    assert report["sample"]["usable"] == 6
    assert report["sample"]["malformed"] == 0, "the writer and the reader must agree"
    assert report["context"]["turns_with_injection"] > 0


def test_an_empty_store_reads_as_plumbing_proved_and_nothing_more(tmp_path, capsys):
    """The honest shape of a dev box today: zero facts, so nothing injects, and the
    report says `cannot conclude` rather than `0% divergence, promote`."""
    code = collect.main(["--empty", "--turns", "5", "--out", str(tmp_path / "out")])
    printed = capsys.readouterr().out

    assert code == 2
    assert "no denominator" in printed
    assert "verdict: CANNOT CONCLUDE" in printed


# --- the seams the collector leans on -------------------------------------


def test_the_shadow_module_loads_without_the_hermes_host():
    """`_shadow.py` must stay importable with no host package: the collector loads it
    by path because `plugins/entropicmem/__init__.py` imports `agent.memory_provider`.
    A relative import added inside `_shadow.py` breaks the collector and nothing else."""
    tree = ast.parse((PLUGIN / "_shadow.py").read_text(encoding="utf-8"))
    top = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    offenders = [
        f"{getattr(node, 'module', '') or ''} level={getattr(node, 'level', 0)}"
        for node in top
        if isinstance(node, ast.ImportFrom)
        and (node.level or 0) > 0
        or isinstance(node, ast.Import)
        and any(alias.name.split(".")[0] in {"agent", "em", "em_internal", "memory_engine"} for alias in node.names)
    ]
    assert not offenders, f"_shadow.py gained a non-stdlib module-level import: {offenders}"

    module = collect.load_shadow()
    assert module.PROMOTION == shadow.PROMOTION, "the collector must read the frozen observable"


def test_the_collector_never_imports_the_plugin_package():
    """Going through `plugins.entropicmem` would pull the host module into a CLI."""
    tree = ast.parse(COLLECTOR.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    assert not {name for name in names if name.startswith("plugins.")}, sorted(names)


def test_the_env_the_collector_borrows_is_given_back(live_store, tmp_path, monkeypatch):
    """A CLI that leaves `ENTROPICMEM_SHADOW_V3` set would make the *next* provider
    prefetch in the same process a shadow run. Borrow, then give back."""
    import os

    monkeypatch.delenv(shadow.SHADOW_ENV, raising=False)
    monkeypatch.delenv(shadow.LOG_ENV, raising=False)

    collect.collect(source=live_store, turns=2, out=tmp_path / "out", profile="default")

    assert os.environ.get(shadow.SHADOW_ENV) is None
    assert os.environ.get(shadow.LOG_ENV) is None


def test_a_source_that_is_not_there_is_refused_rather_than_emptied(tmp_path):
    """Silently degrading "the store you pointed at does not exist" into an empty store
    would hand back a plumbing sample that reads like a real profile."""
    with pytest.raises(SystemExit, match="No store at"):
        collect.copy_store(tmp_path / "nowhere.db", tmp_path / "out" / "v2" / "memory.db")


def test_turns_below_one_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        collect.main(["--empty", "--turns", "0", "--out", str(tmp_path / "out")])
