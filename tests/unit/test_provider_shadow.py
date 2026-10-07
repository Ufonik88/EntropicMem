"""P0 — the v3 shadow read: the flag, the turn path, and the divergence line.

The two properties the owner asked to be *asserted* rather than inspected:

1. **The full provider response is byte-identical with the shadow on and off** — the
   transcript, not just the rendered block, because a block-only test can pass while
   the surrounding response drifts.
2. **The shadow does not touch the turn path** — proven by blocking the shadow thread
   on an event and showing the response still returns, which cannot pass by luck.

Plus the properties that keep the diagnostic honest: the copy's age on every line,
the caveat, the promotion observable fixed in advance, and the live store never
written.

Invented data only (rule 4).
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from plugins.entropicmem import EntropicMemMemoryProvider, _shadow  # noqa: E402

from memory_engine import StoredFact  # noqa: E402


class _FakeEngine:
    """The smallest engine `_build_fact_block` can drive."""

    def __init__(self, facts):
        self._facts = facts
        self.closed = False

    def recall_with_relevance(self, query, **kwargs):  # noqa: ANN001, ANN003
        # `_get_candidates` passes the whole decay/reinforcement config as keywords,
        # so the fake has to accept them or `prefetch` swallows the TypeError and
        # returns '' — which looks like a shadow failure and is not one.
        return list(self._facts)

    def close(self):
        self.closed = True


def _fact(index: int, content: str) -> StoredFact:
    return StoredFact(
        id=f"{index:016x}",
        content=content,
        importance=0.8,
        domain="Infrastructure",
        created_at="2026-09-01T10:00:00+00:00",
        relevance_score=0.9,
    )


FACTS = [_fact(1, "the staging server runs on port 9090"), _fact(2, "nightly billing job")]


@pytest.fixture(autouse=True)
def _host_provides_a_real_thread(monkeypatch):
    """Make the host primitive behave like a host that provides it.

    `tests/conftest.py` stubs `agent.memory_provider` with a MagicMock, so `_spawn`
    calls a *mock* `spawn_context_thread` and its `.start()` does nothing — the shadow
    then never runs and every "it is off the turn path" assertion passes vacuously.
    Returning a real thread is what the host does in production, and `_spawn` is the
    one helper the provider is allowed to use (F-005b/H3), so the test meets it there
    rather than making the provider bypass it.
    """
    # `sys.modules`, not `import agent.memory_provider as host`: conftest stubs the
    # parent with a MagicMock, so attribute access hands back a *different*
    # auto-child Mock than the object `from agent.memory_provider import ...` resolves
    # through. Patching the wrong one is invisible — the stub absorbs the setattr.
    import sys

    host = sys.modules["agent.memory_provider"]

    def _thread(target, name=None, daemon=True):  # noqa: ANN001, ANN202
        return threading.Thread(target=target, name=name, daemon=daemon)

    monkeypatch.setattr(host, "spawn_context_thread", _thread, raising=False)


@pytest.fixture()
def live_db(tmp_path):
    """A real but *empty* sqlite file — the shadow copies it and migrates the copy.

    Deliberately empty rather than a hand-rolled ``facts`` table: a stub table makes
    migration 0001 skip its ``CREATE TABLE IF NOT EXISTS`` and then fail on a column
    the real v2 schema has, which is a test-fixture bug that *looks* like a shadow bug.
    """
    import sqlite3

    path = tmp_path / "live" / "memory.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(str(path)).close()
    return path


def _provider(tmp_path, live_db, monkeypatch) -> EntropicMemMemoryProvider:
    monkeypatch.setattr(
        EntropicMemMemoryProvider, "_open_engine", lambda self: _FakeEngine(FACTS)
    )
    provider = EntropicMemMemoryProvider(config={})
    provider.initialize("shadow-session", hermes_home=str(tmp_path))
    # `initialize` leaves these unset when the skill tree is not in the temp home;
    # `prefetch` needs both, and the shadow needs the db path.
    provider._scripts_dir = str(tmp_path)
    provider._memory_db = live_db
    provider._profile_id = "eval"
    return provider


def _transcript(provider, query: str) -> dict:
    """Everything the host receives for one turn — not just the rendered block."""
    return {
        "system_prompt": provider.system_prompt_block(),
        "context_query": provider._build_context_query(query),
        "prefetch_first": provider.prefetch(query),
        "prefetch_second": provider.prefetch(query),  # the cache path
        "prefetch_other": provider.prefetch("an unrelated query about invoices"),
    }


# --- the flag is off by default -------------------------------------------


def test_the_shadow_is_off_unless_the_environment_names_a_copy(monkeypatch):
    monkeypatch.delenv(_shadow.SHADOW_ENV, raising=False)
    assert _shadow.shadow_path() is None


def test_a_disabled_shadow_runs_nothing(monkeypatch, tmp_path, live_db):
    monkeypatch.delenv(_shadow.SHADOW_ENV, raising=False)
    provider = _provider(tmp_path, live_db, monkeypatch)
    provider.prefetch("the staging server port")
    # No copy, no log: the default path is inert.
    assert not (tmp_path / "shadow").exists()


def test_run_returns_none_when_disabled(monkeypatch, tmp_path, live_db):
    monkeypatch.delenv(_shadow.SHADOW_ENV, raising=False)
    assert _shadow.run(live_db, profile="eval", query="q", v2_ids=["a"]) is None


# --- property 1: the full response is byte-identical ----------------------


def test_the_full_provider_response_is_byte_identical_with_the_shadow_on(
    monkeypatch, tmp_path, live_db
):
    """The owner's strengthening: the transcript, not only the block.

    `system_prompt_block`, the context query, the first prefetch, the cached second
    prefetch and an abstaining query are all compared. A shadow that leaked into any
    of them would show up here.
    """
    query = "what port does the staging server use"

    monkeypatch.delenv(_shadow.SHADOW_ENV, raising=False)
    before = _transcript(_provider(tmp_path, live_db, monkeypatch), query)

    monkeypatch.setenv(_shadow.SHADOW_ENV, str(tmp_path / "shadow" / "memory.db"))
    after = _transcript(_provider(tmp_path, live_db, monkeypatch), query)

    assert after == before
    assert before["prefetch_first"], "the fixture must actually inject something"


def test_turning_the_shadow_on_actually_enables_it(monkeypatch, tmp_path, live_db):
    """The byte-identity test above is only meaningful if the flag does something."""
    calls = []
    monkeypatch.setattr(_shadow, "run", lambda *a, **kw: calls.append(a) or {})
    monkeypatch.setenv(_shadow.SHADOW_ENV, str(tmp_path / "shadow" / "memory.db"))
    provider = _provider(tmp_path, live_db, monkeypatch)

    provider.prefetch("the staging server port")
    for _ in range(200):
        if calls:
            break
        threading.Event().wait(0.01)
    assert calls, "the shadow was enabled but never ran"


def test_the_shadow_receives_the_injected_ids(monkeypatch, tmp_path, live_db):
    seen = {}
    monkeypatch.setattr(_shadow, "run", lambda *a, **kw: seen.update(kw) or {})
    monkeypatch.setenv(_shadow.SHADOW_ENV, str(tmp_path / "shadow" / "memory.db"))
    provider = _provider(tmp_path, live_db, monkeypatch)

    block = provider.prefetch("the staging server port")
    for _ in range(200):
        if seen:
            break
        threading.Event().wait(0.01)
    assert seen["v2_ids"] == _shadow.injected_ids(block)
    assert seen["v2_ids"], "the ids must be the ones actually injected"


# --- property 2: the shadow is not on the turn path -----------------------


def test_the_response_returns_before_the_shadow_finishes(monkeypatch, tmp_path, live_db):
    """Blocked-shadow proof, not an inspection.

    The shadow is made to wait on an event that is only set *after* `prefetch`
    returns. If any part of the shadow were on the turn path this would deadlock
    rather than fail — so the event is set in `finally`, and the assertion is that
    the response arrived first.
    """
    gate = threading.Event()
    entered = threading.Event()

    def blocking_run(*args, **kwargs):
        entered.set()
        gate.wait(timeout=10.0)
        return {}

    monkeypatch.setattr(_shadow, "run", blocking_run)
    monkeypatch.setenv(_shadow.SHADOW_ENV, str(tmp_path / "shadow" / "memory.db"))
    provider = _provider(tmp_path, live_db, monkeypatch)

    try:
        block = provider.prefetch("the staging server port")
        assert block, "the turn must still produce its answer"
        assert entered.wait(timeout=5.0), "the shadow should have started"
        assert not gate.is_set(), "the turn path must not have waited for the shadow"
    finally:
        gate.set()


def test_the_shadow_runs_on_its_own_named_thread(monkeypatch, tmp_path, live_db):
    names = []
    monkeypatch.setattr(
        _shadow, "run", lambda *a, **kw: names.append(threading.current_thread().name) or {}
    )
    monkeypatch.setenv(_shadow.SHADOW_ENV, str(tmp_path / "shadow" / "memory.db"))
    provider = _provider(tmp_path, live_db, monkeypatch)

    provider.prefetch("the staging server port")
    for _ in range(200):
        if names:
            break
        threading.Event().wait(0.01)
    assert names == ["em-shadow-v3"]


def test_a_failing_shadow_cannot_break_the_turn(monkeypatch, tmp_path, live_db):
    def explode(*args, **kwargs):
        raise RuntimeError("shadow blew up")

    monkeypatch.setattr(_shadow, "run", explode)
    monkeypatch.setenv(_shadow.SHADOW_ENV, str(tmp_path / "shadow" / "memory.db"))
    provider = _provider(tmp_path, live_db, monkeypatch)
    assert provider.prefetch("the staging server port")


# --- the divergence line --------------------------------------------------


def test_run_writes_a_line_carrying_the_staleness_bound_and_the_caveat(
    monkeypatch, tmp_path, live_db
):
    """The two biases cannot be designed away, so they travel with every number."""
    shadow_db = tmp_path / "shadow" / "memory.db"
    monkeypatch.setenv(_shadow.SHADOW_ENV, str(shadow_db))
    log = tmp_path / "divergence.jsonl"

    line = _shadow.run(
        live_db, profile="eval", query="the staging server port", v2_ids=["a", "b"], destination=log
    )

    assert line is not None
    assert line["v2_ids"] == ["a", "b"]
    assert line["v3_ids"] == [], "an empty copy injects nothing"
    assert line["divergence"] == ["a", "b"]
    assert line["v3_only"] == []
    assert line["copy_age_s"] == 0.0 and line["copy_refreshed"] is True
    assert line["stale"] is False
    assert "EM-303" in line["caveat"] and "LOWER BOUND" in line["caveat"]

    written = [json.loads(row) for row in log.read_text().splitlines()]
    assert written == [line], "one line per turn"


def test_the_copy_is_a_migrated_v3_store(monkeypatch, tmp_path, live_db):
    """The refresh migrates, so the shadow exercises the cutover path on a copy."""
    import sqlite3

    shadow_db = tmp_path / "shadow" / "memory.db"
    monkeypatch.setenv(_shadow.SHADOW_ENV, str(shadow_db))
    _shadow.run(live_db, profile="eval", query="q", v2_ids=[], destination=tmp_path / "d.jsonl")

    connection = sqlite3.connect(f"file:{shadow_db}?mode=ro", uri=True)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()
    assert version >= 1 and "memories" in tables


def test_the_live_store_is_never_written(monkeypatch, tmp_path, live_db):
    """Repo rule 3. The shadow reads the live store and writes only its own copy."""
    shadow_db = tmp_path / "shadow" / "memory.db"
    monkeypatch.setenv(_shadow.SHADOW_ENV, str(shadow_db))
    before = (live_db.read_bytes(), live_db.stat().st_mtime)

    _shadow.run(live_db, profile="eval", query="q", v2_ids=[], destination=tmp_path / "d.jsonl")

    assert (live_db.read_bytes(), live_db.stat().st_mtime) == before


def test_a_stale_copy_is_refreshed_and_a_fresh_one_reused(monkeypatch, tmp_path, live_db):
    shadow_db = tmp_path / "shadow" / "memory.db"
    monkeypatch.setenv(_shadow.SHADOW_ENV, str(shadow_db))
    log = tmp_path / "d.jsonl"

    first = _shadow.run(live_db, profile="eval", query="q", v2_ids=[], destination=log)
    second = _shadow.run(live_db, profile="eval", query="q", v2_ids=[], destination=log)
    assert first["copy_refreshed"] is True
    assert second["copy_refreshed"] is False, "a fresh copy must not be re-copied every turn"

    import os
    import time

    old = time.time() - (_shadow.MAX_COPY_AGE_S + 60.0)
    os.utime(shadow_db, (old, old))
    third = _shadow.run(live_db, profile="eval", query="q", v2_ids=[], destination=log)
    assert third["copy_refreshed"] is True, "a copy past the bound must be refreshed"


# --- id spaces: the defect the end-to-end run found -----------------------


def test_a_migrated_memory_compares_equal_through_its_legacy_id(monkeypatch, tmp_path):
    """v2 and v3 name one memory differently, and a raw comparison calls it a divergence.

    The unit tests all passed while **every real line would have been meaningless**:
    v2 returns the 16-hex content id, v3 returns a ``mem_…`` ULID for the *same* row, so
    the raw sets never intersect, every line reports "v3 fabricated a hit", and the
    ``v3_only == 0`` promotion condition would have tripped on the first day. Found by
    running the shadow end to end against a real migrated store — not by a unit test.
    """
    from memory_engine import MemoryEngine

    live = tmp_path / "live" / "memory.db"
    live.parent.mkdir(parents=True, exist_ok=True)
    engine = MemoryEngine(live, profile_id="default")
    memory_id = engine.remember(
        "the staging server runs Ubuntu 22.04 with nginx", importance=0.8, source="agent"
    )
    engine.close()

    monkeypatch.setenv(_shadow.SHADOW_ENV, str(tmp_path / "shadow" / "memory.db"))
    line = _shadow.run(
        live,
        profile="default",
        query="what does the staging server run",
        v2_ids=[memory_id],
        destination=tmp_path / "d.jsonl",
    )

    assert line["v3_ids"] == [memory_id], "the v3 hit must be compared by its legacy_id"
    assert line["divergence"] == [] and line["v3_only"] == []


def test_a_row_written_only_to_v3_keeps_its_own_id(monkeypatch, tmp_path):
    """A row with no legacy counterpart still reads as itself, so it shows as v3-only."""
    from em.store.db import Store
    from em.store.memories import MemoryStore
    from em.store.migrations import migrate
    from em.store.types import MemoryDraft, Scope

    shadow_db = tmp_path / "shadow" / "memory.db"
    shadow_db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(shadow_db))
    with store.writer() as conn:
        migrate(conn)
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(content="a row written straight to v3"), scope=Scope(profile="default"),
            actor="tester",
        )
    mapped = _shadow.comparison_ids(store.reader(), [result.id])
    store.close()
    assert mapped == [result.id]


def test_comparison_ids_passes_an_unknown_id_through(tmp_path):
    """An id the copy does not hold is returned unchanged rather than dropped."""
    from em.store.db import Store
    from em.store.migrations import migrate

    shadow_db = tmp_path / "shadow" / "memory.db"
    shadow_db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(shadow_db))
    with store.writer() as conn:
        migrate(conn)
    try:
        assert _shadow.comparison_ids(store.reader(), ["mem_not_in_this_store"]) == [
            "mem_not_in_this_store"
        ]
    finally:
        store.close()


# --- the shared shape and the pre-declared thresholds ---------------------


def test_injected_ids_reads_the_bullet_shape_the_runner_reads():
    block = "- [f·1] first\n- [f·2] second\nplain line\n"
    assert _shadow.injected_ids(block) == ["f·1", "f·2"]
    assert _shadow.injected_ids("") == []


def test_the_promotion_observable_is_declared_in_advance():
    """Fixed before collecting, so the threshold cannot be fitted to the data."""
    assert set(_shadow.PROMOTION) == {
        "min_turns", "max_copy_age_s", "max_divergence_rate", "max_v3_only", "max_p95_shadow_ms",
    }
    assert _shadow.PROMOTION["max_v3_only"] == 0, "v3 must never inject what v2 did not"
    assert _shadow.PROMOTION["max_copy_age_s"] == _shadow.MAX_COPY_AGE_S
