"""Engine-v3 adapter tests — the real `em` pipeline over a migrated v3 store.

Mirrors `test_adapter_v2.py`'s shape, and adds the two asymmetries the v3 adapter
deliberately has: `search` runs without the gate (ranking measures ORDER) and
`prefetch` runs with it (`abstain_correct` reads the block).

Nothing here touches a live store: every handle is a temp directory.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from evals.adapters import engine_v3  # noqa: E402
from evals.dataset import Memory, NoiseSpec, Scenario, Turn  # noqa: E402
from evals.runner import parse_injected_ids  # noqa: E402

from em.store.migrations import LATEST  # noqa: E402


def _scenario(**kw) -> Scenario:
    return Scenario(
        scenario_id="adapter_v3_s1",
        category="ageing",
        memories=[
            Memory(
                content="The user's name is Marta Kolar and she lives in Brackenridge",
                age_days=120,
                importance=0.9,
                domain="People",
                kind="profile",
            ),
            Memory(content="Marta's sister Tonia keeps bees near Aldermoor", age_days=5),
        ],
        noise=NoiseSpec(count=kw.get("noise", 20), seed=7),
        turns=[Turn(query="where does the user live?", expect_ids=["$0"], must_not=["$noise"])],
    )


@pytest.fixture()
def adapter():
    a = engine_v3.EngineV3Adapter()
    yield a
    a.shutdown()


def test_the_adapter_is_registered_under_the_name_v3():
    assert engine_v3.EngineV3Adapter.name == "v3"


def test_load_returns_a_v3_store_with_ref_and_noise_ids(adapter):
    handle = adapter.load(_scenario())
    try:
        assert handle.ref_ids["$0"] and handle.ref_ids["$0"].startswith("mem_")
        assert len(handle.ref_ids) == 2
        assert len(handle.noise_ids) == 20
        assert "$0" not in handle.noise_ids

        store = handle.extra["store"]
        version = store.reader().execute("PRAGMA user_version").fetchone()[0]
        assert version == LATEST, "the adapter must drive a *migrated* v3 store"
    finally:
        adapter.finish(handle)


def test_the_store_is_a_temp_database_not_a_live_one(adapter):
    """A guard against the one thing an eval must never do: touch the live store."""
    handle = adapter.load(_scenario(noise=0))
    try:
        path = Path(handle.extra["store"].path).resolve()
        assert ".hermes/entropicmem" not in str(path)
        assert "em-eval-v3-" in str(path)
    finally:
        adapter.finish(handle)


def test_aged_memories_are_backdated(adapter):
    handle = adapter.load(_scenario(noise=0))
    try:
        row = handle.extra["conn"].execute(
            "SELECT created_at, updated_at FROM memories WHERE id = ?",
            (handle.ref_ids["$0"],),
        ).fetchone()
        for column in ("created_at", "updated_at"):
            stamped = datetime.fromisoformat(str(row[column]).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - stamped).total_seconds() / 86400.0
            assert 119.0 < age < 121.0, f"{column} not aged: {row[column]}"
    finally:
        adapter.finish(handle)


def test_search_ranks_the_expected_memory_first(adapter):
    handle = adapter.load(_scenario())
    try:
        hits = adapter.search(handle, "where does the user live?", k=5)
        assert hits, "search returned nothing"
        assert hits[0].id == handle.ref_ids["$0"]
        assert hits[0].content, "a hit should carry its text"
        assert hits[0].score >= hits[-1].score, "hits must be in descending score order"
    finally:
        adapter.finish(handle)


def test_prefetch_renders_bullets_the_runner_can_parse(adapter):
    handle = adapter.load(_scenario())
    try:
        block = adapter.prefetch(handle, "where does the user live?")
        assert block, "an on-topic query must not abstain"
        assert parse_injected_ids(block) == [handle.ref_ids["$0"]]
        assert block.startswith("- [")
    finally:
        adapter.finish(handle)


def test_prefetch_abstains_on_an_unrelated_query(adapter):
    """§3.6: nothing survives the gate → the memory section is omitted entirely."""
    handle = adapter.load(_scenario())
    try:
        block = adapter.prefetch(handle, "what is the orbital decay of a geosynchronous satellite?")
        assert block == ""
        assert parse_injected_ids(block) == []
    finally:
        adapter.finish(handle)


def test_search_does_not_abstain_even_when_prefetch_does(adapter):
    """The asymmetry: ranking metrics measure ORDER, so the gate is not applied there."""
    handle = adapter.load(_scenario())
    try:
        query = "what is the orbital decay of a geosynchronous satellite?"
        assert adapter.prefetch(handle, query) == ""
        assert adapter.search(handle, query, k=5), "search must still return a ranking"
    finally:
        adapter.finish(handle)


def test_the_adapter_passes_calibration_overrides_through():
    """EM-306's seam: an override given to the adapter must reach the pipeline.

    A strict ``min_score`` above the scale drops the unpinned hit; ``search`` still
    returns its ordering, because that is the asymmetry the adapter exists to keep.
    """
    from em.retrieval import gate

    strict = engine_v3.EngineV3Adapter(gate_config=gate.GateConfig(min_score=1.1))
    try:
        handle = strict.load(_scenario())
        assert strict.prefetch(handle, "where does the user live?") == ""
        assert strict.search(handle, "where does the user live?", k=5)
    finally:
        strict.shutdown()


def test_shutdown_is_idempotent(adapter):
    handle = adapter.load(_scenario(noise=0))
    adapter.finish(handle)
    adapter.shutdown()
    adapter.shutdown()  # must not raise on an already-cleaned adapter


def test_the_v3_adapter_never_imports_the_v2_engine_module():
    """It measures the `em` pipeline; a v2 import would mean it measures something else.

    Checked by parsing the imports rather than by scanning the text — the module's
    prose mentions `engine_v2` to explain the asymmetry with it.
    """
    import ast

    imported = set()
    for node in ast.walk(ast.parse(Path(engine_v3.__file__).read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "memory_engine" not in imported
    assert "engine_v2" not in imported
    assert "em" in imported
