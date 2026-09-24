"""Engine-v2 adapter tests — real MemoryEngine + real provider pipeline (temp dirs)."""

import pytest
from evals.adapters import engine_v2
from evals.dataset import Memory, NoiseSpec, Scenario, Turn


def _scenario(**kw):
    return Scenario(
        scenario_id="adapter_s1",
        category="ageing",
        memories=[
            Memory(content="The user's name is Marta Kolar and she lives in Brackenridge",
                   age_days=120, importance=0.9, domain="People"),
        ],
        noise=NoiseSpec(count=kw.get("noise", 20), seed=7),
        turns=[Turn(query="where does the user live?", expect_ids=["$0"],
                    expect_substrings=["Brackenridge"], must_not=["$noise"])],
    )


@pytest.fixture()
def adapter():
    a = engine_v2.EngineV2Adapter()
    yield a
    a.shutdown()


def test_load_returns_handle_with_ref_and_noise_ids(adapter):
    h = adapter.load(_scenario())
    try:
        assert h.ref_ids["$0"] and len(h.ref_ids["$0"]) == 16
        assert len(h.noise_ids) == 20
        assert "$0" not in h.noise_ids
    finally:
        adapter.finish(h)


def test_aged_memories_are_backdated(adapter):
    h = adapter.load(_scenario())
    try:
        engine = h.extra["engine"]
        row = engine.db.execute(
            "SELECT created_at, updated_at, last_accessed FROM facts WHERE id = ?",
            (h.ref_ids["$0"],),
        ).fetchone()
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        for col in ("created_at", "updated_at", "last_accessed"):
            stamped = datetime.fromisoformat(row[col])
            if stamped.tzinfo is None:
                stamped = stamped.replace(tzinfo=timezone.utc)
            age = (now - stamped).total_seconds() / 86400.0
            assert 119.0 < age < 121.0, f"{col} not aged: {row[col]}"
        # noise stays fresh
        nrow = engine.db.execute(
            "SELECT created_at FROM facts WHERE id = ?", (sorted(h.noise_ids)[0],)
        ).fetchone()
        assert nrow and nrow[0]
    finally:
        adapter.finish(h)


def test_search_returns_ordered_hits(adapter):
    h = adapter.load(_scenario())
    try:
        hits = adapter.search(h, "where does the user live?", k=5)
        assert isinstance(hits, list)
        assert len(hits) <= 5
        assert all(h.id and isinstance(h.content, str) for h in hits)
    finally:
        adapter.finish(h)


def test_search_is_deterministic(adapter):
    h = adapter.load(_scenario())
    try:
        a = [x.id for x in adapter.search(h, "where does the user live?", k=5)]
        b = [x.id for x in adapter.search(h, "where does the user live?", k=5)]
        assert a == b
    finally:
        adapter.finish(h)


def test_prefetch_returns_bullets_or_empty_string(adapter):
    h = adapter.load(_scenario())
    try:
        block = adapter.prefetch(h, "where does the user live?")
        assert isinstance(block, str)
        if block:
            assert block.startswith("## EntropicMem recall")
            import re

            ids = re.findall(r"^- \[([^\]]+)\]", block, re.MULTILINE)
            assert ids
    finally:
        adapter.finish(h)


def test_prefetch_junk_returns_string(adapter):
    # Whether v2 abstains on junk is what the abstain_correct *metric*
    # measures (known v2 defect: it injects filler at relevance 1.0). The
    # adapter contract here is only "returns str, bullets parse to ids".
    h = adapter.load(_scenario())
    try:
        block = adapter.prefetch(h, "zzqx nonsense a")
        assert isinstance(block, str)
    finally:
        adapter.finish(h)


def test_scenarios_are_isolated(adapter):
    h1 = adapter.load(_scenario())
    h2 = adapter.load(_scenario())
    try:
        assert h1.ref_ids["$0"] == h2.ref_ids["$0"]  # same content → same id
        e1 = h1.extra["engine"].db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        assert e1 == 1 + 20  # scenario DB is per-handle, not shared
    finally:
        adapter.finish(h1)
        adapter.finish(h2)
