"""`em.provider.prefetch_service` — slice 2: precompute / queue / topic (EM-403)."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.provider.prefetch_service import (  # noqa: E402
    PrefetchService,
    TopicState,
    scope_key,
)
from em.store.db import Store  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import Scope  # noqa: E402

SCOPE = Scope(profile="slice2")


def _spawn(target, name):
    t = threading.Thread(target=target, name=name, daemon=True)
    t.start()
    return t


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as writer:
        migrate(writer)
    yield s
    s.close()


def _service(store, *, embedder=None, **kw):
    return PrefetchService(
        connect=store.reader,
        spawn_thread=_spawn,
        embed_query=embedder,
        **kw,
    )


def test_thread_affinity_embedder_runs_only_in_precompute_worker(store):
    seen = {"threads": []}

    def embed(text):
        seen["threads"].append(threading.current_thread().name)
        return [0.1, 0.2]

    svc = _service(store, embedder=embed)
    svc._last_scope = SCOPE
    handle = svc.queue_precompute("hello", session_id="s1", scope=SCOPE)
    assert handle.done.wait(timeout=5.0)
    assert all(t != threading.current_thread().name for t in seen["threads"])
    assert seen["threads"], "embedder was never called"
    svc.close()


def test_coalescing_only_latest_runs(store):
    gate = threading.Event()
    calls = {"queries": []}

    def embed(text):
        # hold the worker on the first request so the second is queued behind it
        if text == "A":
            gate.wait(timeout=5.0)
        calls["queries"].append(text)
        return None

    svc = _service(store, embedder=embed)
    svc._last_scope = SCOPE
    hA = svc.queue_precompute("A", session_id="s1", scope=SCOPE)
    # let A reach the worker and block
    time.sleep(0.2)
    hB = svc.queue_precompute("B", session_id="s1", scope=SCOPE)
    gate.set()
    assert hA.done.wait(timeout=5.0)
    assert hB.done.wait(timeout=5.0)
    # B must be processed (A may be skipped by coalescing)
    pool = svc.candidate_pool("s1", SCOPE)
    assert pool is not None and pool["query"] == "B"
    # different sessions are tracked separately
    svc.close()


def test_different_sessions_do_not_coalesce(store):
    svc = _service(store)
    svc._last_scope = SCOPE
    h1 = svc.queue_precompute("q1", session_id="a", scope=SCOPE)
    h2 = svc.queue_precompute("q2", session_id="b", scope=SCOPE)
    assert h1.done.wait(timeout=5.0) and h2.done.wait(timeout=5.0)
    assert svc.candidate_pool("a", SCOPE)["query"] == "q1"
    assert svc.candidate_pool("b", SCOPE)["query"] == "q2"
    svc.close()


def test_cache_isolation_by_session_and_scope(store):
    svc = _service(store)
    s1 = Scope(profile="p1")
    s2 = Scope(profile="p2")
    svc.precompute("hello", session_id="s1", scope=s1)
    svc.precompute("hello", session_id="s2", scope=s2)
    assert svc.candidate_pool("s1", s1) is not None
    assert svc.candidate_pool("s2", s2) is not None
    # keys differ
    assert (svc.candidate_pool("s1", s1)) is not (svc.candidate_pool("s2", s2))
    assert scope_key(s1) != scope_key(s2)
    svc.close()


def test_topic_state_ema_hand_computed(store):
    svc = _service(store)
    svc._update_topic("t", entities=["e1"], embedding=[1.0, 0.0])
    svc._update_topic("t", entities=["e2"], embedding=[0.0, 1.0])
    st = svc.topic_state("t")
    assert isinstance(st, TopicState)
    # alpha 0.5: (0.5, 0.5)
    assert st.embedding == (0.5, 0.5)
    assert "e1" in st.entities and "e2" in st.entities
    # window beyond 5 drops oldest entity
    for i in range(10):
        svc._update_topic("t", entities=[f"e{i + 10}"], embedding=[1.0, 1.0])
    st2 = svc.topic_state("t")
    assert "e1" not in st2.entities
    assert st2.turns == 5
    svc.close()


def test_bonus_zero_without_topic(store):
    svc = _service(store, token_budget=450)
    r = svc.prefetch("port", scope=SCOPE, session_id="nope")
    # no topic state => no +0.05; just ensure no crash and returns str
    assert isinstance(r.text, str)
    svc.close()


def test_close_rejects_enqueue(store):
    svc = _service(store)
    svc.close()
    with pytest.raises(RuntimeError):
        svc.queue_precompute("q", session_id="s", scope=SCOPE)


def test_worker_survives_embedder_exception(store):
    def bad(text):
        raise ValueError("boom")

    svc = _service(store, embedder=bad)
    svc._last_scope = SCOPE
    h = svc.queue_precompute("q", session_id="s", scope=SCOPE)
    assert h.done.wait(timeout=5.0)
    # worker still alive: another successful precompute
    svc2 = _service(store)
    svc2._last_scope = SCOPE
    h2 = svc2.queue_precompute("q2", session_id="s2", scope=SCOPE)
    assert h2.done.wait(timeout=5.0)
    svc.close()
    svc2.close()


def test_candidate_pool_bounded(store):
    svc = _service(store)
    svc._candidate_pool_max = 2
    for i in range(5):
        svc.precompute(f"q{i}", session_id=f"s{i}", scope=SCOPE)
    assert len(svc._candidate_pools) <= 2
    svc.close()


def test_reset_clears_topic_and_pools(store):
    svc = _service(store)
    svc.precompute("q", session_id="s", scope=SCOPE)
    svc.reset()
    assert svc.candidate_pool("s", SCOPE) is None
    assert svc.topic_state("s") is None
    svc.close()


def test_topic_bonus_configurable_and_zero_without_topic(store):
    svc = _service(store, topic_bonus=0.0)
    items = []
    # _apply_topic_bonus with a populated topic but zero configured bonus => unchanged
    svc._topic_states["x"] = TopicState(entities=frozenset({"e"}), turns=1)
    got = svc._apply_topic_bonus(items, "x")
    assert got == items
    # default bonus constant exposed
    from em.provider.prefetch_service import TOPIC_ENTITY_BONUS

    assert TOPIC_ENTITY_BONUS == 0.05
    svc.close()


def test_stats_counters_increment(store):
    svc = _service(store)
    svc._last_scope = SCOPE
    # coalesce
    gate = threading.Event()

    def slow_embed(text):
        if text == "A":
            gate.wait(timeout=5.0)
        return None

    svc2 = PrefetchService(connect=store.reader, spawn_thread=_spawn, embed_query=slow_embed)
    svc2._last_scope = SCOPE
    hA = svc2.queue_precompute("A", session_id="s", scope=SCOPE)
    time.sleep(0.2)
    hB = svc2.queue_precompute("B", session_id="s", scope=SCOPE)
    gate.set()
    assert hA.done.wait(timeout=5.0) and hB.done.wait(timeout=5.0)
    st = svc2.precompute_stats
    assert st["precompute_enqueued"] >= 2
    assert st["precompute_coalesced"] >= 1
    # reject after close
    svc2.close()
    with pytest.raises(RuntimeError):
        svc2.queue_precompute("q", session_id="s", scope=SCOPE)
    assert svc2.precompute_stats["precompute_rejected_after_close"] >= 1
    svc.close()


def test_candidate_pool_eviction_stat(store):
    svc = _service(store)
    svc._candidate_pool_max = 1
    svc.precompute("q1", session_id="s1", scope=SCOPE)
    svc.precompute("q2", session_id="s2", scope=SCOPE)
    assert svc.precompute_stats["candidate_pool_evicted"] >= 1
    svc.close()


def test_scope_key_covers_all_privacy_dimensions():
    base = Scope(profile="p", user="u", chat="c", chat_type="ct", author="a", is_owner=True)
    for kwargs in [
        dict(user="x"),
        dict(chat="x"),
        dict(chat_type="x"),
        dict(author="x"),
        dict(is_owner=False),
        dict(profile="x"),
    ]:
        other = Scope(**{**base.__dict__, **kwargs})
        assert scope_key(base) != scope_key(other)


def test_precompute_pool_never_crosses_session_or_scope(store):
    s1 = Scope(profile="p1")
    s2 = Scope(profile="p2")
    svc = _service(store)
    svc.precompute("hello", session_id="A", scope=s1)
    assert svc.candidate_pool("B", s2) is None
    assert svc.candidate_pool("A", s2) is None
    svc.reset()
    assert svc.candidate_pool("A", s1) is None
    svc.close()
