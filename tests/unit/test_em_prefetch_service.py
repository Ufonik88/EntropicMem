"""`em.provider.prefetch_service` — §4.2's synchronous core (EM-403 slice 1).

Truth tables for the pieces the AC harness only measures end to end:

* the **cache key** — `(session_id, scope_key, sha1(normalized_query),
  write_generation)`, with `write_generation` = the in-process counter plus the
  read connection's `PRAGMA data_version` (cross-process);
* the **dedup rule** — §4.2's exact wording: a memory injected in any of the
  last `dedup_turns` turns is skipped unless its score ≥ 0.8 and it was injected
  more than 2 turns ago; pinned constraints re-show only every
  `constraint_repeat_turns` turns;
* the **hard cap** `min(token_budget * 4, 9000)` chars, dropping whole rows;
* the **metrics** — the five names, and what each counts;
* the **watchdog** — a generator that ignores the deadline contract is
  abandoned rather than allowed to blow the cap.

The service's retrieval seam (`retrieve=`) is faked where scores must be
deterministic and the real pipeline is used where execution is the subject.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.provider.prefetch_service import (  # noqa: E402
    OUTPUT_CHAR_CAP,
    PrefetchCall,
    PrefetchMetrics,
    PrefetchService,
    scope_key,
)
from em.retrieval import candidates  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

SCOPE = Scope(profile="prefetch-service")
QUERY = "what is the staging port?"


def _spawn(target, name):
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def _ranking(owner_id, score, *, owner_type="memory"):
    return SimpleNamespace(
        owner_type=owner_type,
        owner_id=owner_id,
        score=score,
        key=(owner_type, owner_id),
    )


def _row(pinned=False):
    return SimpleNamespace(pinned=pinned, text="", scope_user="")


def _fast_empty(ctx):
    return []


def _retrieval(rankings, *, pinned=(), partial=False):
    rows = {r.key: _row(pinned=(r.owner_id in set(pinned))) for r in rankings}
    return SimpleNamespace(
        rankings=list(rankings),
        rows=rows,
        predecessors={},
        partial=partial,
        generators_skipped=(),
    )


class FakeRetrieve:
    """A `pipeline.retrieve` stand-in returning pre-set rankings, one call each."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls = []

    def __call__(self, conn, **kwargs):
        self.calls.append(kwargs)
        if not self._outcomes:
            raise AssertionError("fake retrieve called too many times")
        outcome = self._outcomes.pop(0)
        return outcome(**kwargs) if callable(outcome) else outcome


@pytest.fixture()
def store(tmp_path):
    store = Store(str(tmp_path / "memory.db"))
    with store.writer() as writer:
        migrate(writer)
    yield store
    store.close()


def _add(store, content, *, pinned=False, kind="fact", importance=0.5):
    with store.transaction() as writer:
        result = MemoryStore(writer).add(
            MemoryDraft(
                content=content,
                kind=kind,
                importance=importance,
                source="agent",
                status="active",
                pinned=pinned,
            ),
            scope=SCOPE,
            actor="tester",
        )
        assert result.ok
        return result.id


def _service(store, *, retrieve=None, **kwargs):
    return PrefetchService(
        connect=store.reader,
        spawn_thread=_spawn,
        retrieve=retrieve,
        **kwargs,
    )


# --- the cache key -------------------------------------------------------


def test_the_same_query_is_a_hit_and_every_key_part_is_a_miss(store):
    _add(store, "the Acme staging port is 9090")
    fake = FakeRetrieve(
        _retrieval([_ranking("m-1", 0.9)]),
        _retrieval([_ranking("m-1", 0.9)]),
        _retrieval([_ranking("m-1", 0.9)]),
        _retrieval([_ranking("m-1", 0.9)]),
        _retrieval([_ranking("m-1", 0.9)]),
    )
    service = _service(store, retrieve=fake, token_budget=200)
    service.prefetch(QUERY, scope=SCOPE, session_id="s1")
    assert service.prefetch(QUERY, scope=SCOPE, session_id="s1").cache_hit is True
    # a different session
    assert service.prefetch(QUERY, scope=SCOPE, session_id="s2").cache_hit is False
    # a different scope (a different readable set)
    other = Scope(profile="prefetch-service", user="alice")
    assert service.prefetch(QUERY, scope=other, session_id="s1").cache_hit is False
    # a different query
    assert service.prefetch("another question", scope=SCOPE, session_id="s1").cache_hit is False
    service.close()


def test_the_query_is_normalized_before_it_is_keyed(store):
    _add(store, "the Acme staging port is 9090")
    fake = FakeRetrieve(_retrieval([_ranking("m-1", 0.9)]))
    service = _service(store, retrieve=fake)
    service.prefetch("  what   is\nthe port?  ", scope=SCOPE, session_id="s1")
    assert service.prefetch("what is the port?", scope=SCOPE, session_id="s1").cache_hit is True
    service.close()


def test_a_memory_context_block_in_the_query_does_not_change_the_key(store):
    _add(store, "the Acme staging port is 9090")
    fake = FakeRetrieve(_retrieval([_ranking("m-1", 0.9)]))
    service = _service(store, retrieve=fake)
    service.prefetch("what is the port?", scope=SCOPE, session_id="s1")
    replayed = "<memory-context>\n- [m-1] old block\n</memory-context>\nwhat is the port?"
    assert service.prefetch(replayed, scope=SCOPE, session_id="s1").cache_hit is True
    service.close()


def test_an_in_process_write_invalidates_the_cache(store):
    _add(store, "the Acme staging port is 9090")
    fake = FakeRetrieve(
        _retrieval([_ranking("m-1", 0.9)]),
        _retrieval([_ranking("m-1", 0.9)]),
    )
    service = _service(store, retrieve=fake)
    service.prefetch(QUERY, scope=SCOPE, session_id="s1")
    service.note_write()
    assert service.prefetch(QUERY, scope=SCOPE, session_id="s1").cache_hit is False
    service.close()


def test_a_commit_by_another_connection_invalidates_the_cache(store):
    """§4.2's cross-process half: `PRAGMA data_version` on the *persistent* read
    connection moves when another connection commits — which is also why the
    read connection must be persistent (a fresh one always reads 1)."""
    _add(store, "the Acme staging port is 9090")
    fake = FakeRetrieve(
        _retrieval([_ranking("m-1", 0.9)]),
        _retrieval([_ranking("m-1", 0.9)]),
    )
    service = _service(store, retrieve=fake)
    service.prefetch(QUERY, scope=SCOPE, session_id="s1")
    _add(store, "the Acme staging port was changed to 9191")
    assert service.prefetch(QUERY, scope=SCOPE, session_id="s1").cache_hit is False
    service.close()


def test_scope_key_is_stable_and_separates_readable_sets():
    one = Scope(profile="p", user="alice", chat="c", chat_type="group", author="alice", is_owner=True)
    same = Scope(profile="p", user="alice", chat="c", chat_type="group", author="alice", is_owner=True)
    other_user = Scope(profile="p", user="bob", chat="c", chat_type="group", author="alice", is_owner=True)
    other_owner = Scope(profile="p", user="alice", chat="c", chat_type="group", author="alice", is_owner=False)
    assert scope_key(one) == scope_key(same)
    assert scope_key(one) != scope_key(other_user)
    assert scope_key(one) != scope_key(other_owner)
    assert scope_key(one) == scope_key(one)  # stable across calls (never hash())


# --- the dedup rule (§4.2) -----------------------------------------------


def _dedup_service(store, fake, **kwargs):
    return _service(store, retrieve=fake, token_budget=4000, **kwargs)


def test_a_memory_is_skipped_for_the_dedup_window_then_returns(store):
    mid = _add(store, "the Acme staging port is 9090 and it is used for builds only")
    fake = FakeRetrieve(*[_retrieval([_ranking(mid, 0.5)]) for _ in range(9)])
    service = _dedup_service(store, fake)
    shown = [service.prefetch(f"question {n}", scope=SCOPE).injected for n in range(8)]
    assert shown[0], "first turn injects"
    assert not shown[1] and not shown[2] and not shown[3]
    assert not shown[4] and not shown[5] and not shown[6], "within the 6-turn window"
    assert shown[7], "a cold row returns once the window has passed"
    service.close()


def test_a_hot_memory_re_shows_after_three_turns(store):
    mid = _add(store, "the Acme staging port is 9090 and it is used for builds only")
    fake = FakeRetrieve(*[_retrieval([_ranking(mid, 0.9)]) for _ in range(6)])
    service = _dedup_service(store, fake)
    shown = [service.prefetch(f"question {n}", scope=SCOPE).injected for n in range(5)]
    assert shown[0]
    assert not shown[1] and not shown[2], "a hot row is still quiet for 2 turns"
    assert shown[3], "score >= 0.8 and injected > 2 turns ago: it re-shows"
    assert not shown[4]
    service.close()


def test_a_hot_memory_is_still_skipped_in_the_first_two_turns(store):
    mid = _add(store, "the Acme staging port is 9090 and it is used for builds only")
    fake = FakeRetrieve(*[_retrieval([_ranking(mid, 0.8)]) for _ in range(4)])
    service = _dedup_service(store, fake)
    assert service.prefetch("q one", scope=SCOPE).injected
    assert not service.prefetch("q two", scope=SCOPE).injected
    assert not service.prefetch("q three", scope=SCOPE).injected
    service.close()


def test_a_pinned_constraint_re_shows_only_every_ten_turns(store):
    mid = _add(store, "never deploy on a Friday", pinned=True, kind="constraint")
    fake = FakeRetrieve(*[_retrieval([_ranking(mid, 0.99)], pinned=[mid]) for _ in range(13)])
    service = _dedup_service(store, fake, constraint_repeat_turns=10)
    shown = [service.prefetch(f"question {n}", scope=SCOPE).injected for n in range(12)]
    assert shown[0]
    assert not any(shown[1:10]), "pinned rows stay quiet for the full repeat window"
    assert shown[10], "gap 10: the constraint is re-shown"
    service.close()


def test_reset_clears_the_cache_and_the_dedup_history(store):
    mid = _add(store, "the Acme staging port is 9090 and it is used for builds only")
    fake = FakeRetrieve(*[_retrieval([_ranking(mid, 0.5)]) for _ in range(3)])
    service = _dedup_service(store, fake)
    assert service.prefetch(QUERY, scope=SCOPE).injected
    service.reset()
    again = service.prefetch(QUERY, scope=SCOPE)
    assert again.cache_hit is False, "the cache is gone"
    assert again.injected, "and so is the memory of what was shown"
    service.close()


# --- the hard cap --------------------------------------------------------


def test_the_block_never_exceeds_the_char_cap_even_with_a_huge_budget(store):
    ids = [
        _add(store, f"fact {n}: " + "staging port details " * 120) for n in range(10)
    ]
    fake = FakeRetrieve(
        _retrieval([_ranking(mid, 0.9 - n / 100) for n, mid in enumerate(ids)])
    )
    service = _service(store, retrieve=fake, token_budget=100_000)
    result = service.prefetch(QUERY, scope=SCOPE)
    assert result.text, "some rows must survive the cap"
    assert len(result.text) <= OUTPUT_CHAR_CAP
    assert len(result.text) <= min(100_000 * 4, OUTPUT_CHAR_CAP)
    # rows are dropped from the *end* — the lowest-scored — never the head
    assert "fact 0:" in result.text
    assert "fact 9:" not in result.text
    assert result.injected, "the injected set is what survived the cap"
    service.close()


def test_the_cap_is_also_token_budget_times_four_when_that_is_smaller(store):
    ids = [
        _add(store, f"fact {n}: " + "staging port details " * 40) for n in range(6)
    ]
    fake = FakeRetrieve(
        _retrieval([_ranking(mid, 0.9 - n / 100) for n, mid in enumerate(ids)])
    )
    service = _service(store, retrieve=fake, token_budget=300)
    result = service.prefetch(QUERY, scope=SCOPE)
    assert result.text
    assert len(result.text) <= 300 * 4
    service.close()


# --- the metrics ---------------------------------------------------------


def test_the_snapshot_carries_exactly_the_five_metric_names(store):
    mid = _add(store, "the Acme staging port is 9090 and it is used for builds only")
    fake = FakeRetrieve(_retrieval([_ranking(mid, 0.5)]))
    service = _service(store, retrieve=fake)
    service.prefetch(QUERY, scope=SCOPE)
    service.prefetch(QUERY, scope=SCOPE)  # cache hit
    snap = service.metrics.snapshot()
    assert set(snap) == {
        "prefetch.latency_ms",
        "prefetch.cache_hit",
        "prefetch.partial",
        "prefetch.injected_count",
        "prefetch.tokens",
    }
    assert snap["prefetch.cache_hit"]["calls"] == 2
    assert snap["prefetch.cache_hit"]["hits"] == 1
    assert snap["prefetch.injected_count"]["total"] == 1
    assert snap["prefetch.tokens"]["total"] > 0
    assert snap["prefetch.latency_ms"]["count"] == 2
    assert snap["prefetch.latency_ms"]["p95"] >= snap["prefetch.latency_ms"]["p50"]
    service.close()


def test_a_trivial_prompt_is_invisible_to_the_metrics_and_the_dedup_turn(store):
    mid = _add(store, "the Acme staging port is 9090 and it is used for builds only")
    fake = FakeRetrieve(*[_retrieval([_ranking(mid, 0.5)]) for _ in range(2)])
    service = _service(store, retrieve=fake, is_trivial=lambda q: q.strip() == "hi")
    assert service.prefetch("hi", scope=SCOPE).text == ""
    assert service.metrics.snapshot()["prefetch.latency_ms"]["count"] == 0
    result = service.prefetch("what is the port?", scope=SCOPE)
    assert result.injected, "the trivial turn must not have aged the window"
    service.close()


# --- the watchdog and the deadline ---------------------------------------


def test_a_contract_violating_generator_is_abandoned_not_obeyed(store, monkeypatch):
    """§4.1's hard internal cap holds for *any* generator: this one ignores the
    deadline contract entirely (a blocked read, a stuck disk page) and sleeps."""
    _add(store, "the Acme staging port is 9090")

    def slow(ctx):
        time.sleep(2.5)
        return []

    monkeypatch.setitem(candidates.GENERATORS, "recent", slow)
    service = _service(store, max_latency_ms=300)
    started = time.monotonic()
    result = service.prefetch(QUERY, scope=SCOPE)
    elapsed = time.monotonic() - started
    service.close()
    assert elapsed < 1.5, f"prefetch took {elapsed:.2f}s — the cap is 1.5 s"
    assert result.partial is True
    assert result.injected, "the generators that finished must still be served"


def test_while_the_worker_is_stuck_the_next_call_fails_fast_and_then_recovers(
    store, monkeypatch
):
    _add(store, "the Acme staging port is 9090")

    def slow(ctx):
        time.sleep(1.2)
        return []

    monkeypatch.setitem(candidates.GENERATORS, "recent", slow)
    service = _service(store, max_latency_ms=1000)
    first = service.prefetch("first question", scope=SCOPE)
    started = time.monotonic()
    second = service.prefetch("second question", scope=SCOPE)
    fast = time.monotonic() - started
    time.sleep(0.4)  # the abandoned generator has finished (1.2 s after it started)
    monkeypatch.setitem(candidates.GENERATORS, "recent", _fast_empty)
    third = service.prefetch("third question", scope=SCOPE)
    service.close()
    assert first.partial is True
    # The fail-fast path is a lock check (microseconds). A version that queued
    # behind the stuck call would burn this call's whole budget — 1.05 s here —
    # so the bound separates the two by more than 2x without being tight.
    assert fast < 0.5, f"the busy path must not wait for the stuck call ({fast:.2f}s)"
    assert second.partial is True
    assert third.partial is False, "and once the worker frees up, prefetch runs again"


def test_an_expired_deadline_marks_the_result_partial(store):
    _add(store, "the Acme staging port is 9090")
    service = _service(store, max_latency_ms=0.0)
    result = service.prefetch(QUERY, scope=SCOPE)
    assert result.partial is True
    assert result.injected == ()
    service.close()


def test_a_partial_result_is_never_cached(store):
    """A deadline-shortened build is not a complete answer to replay: the next
    turn re-runs the pipeline instead of serving the fragment from cache."""
    _add(store, "the Acme staging port is 9090")
    fake = FakeRetrieve(
        _retrieval([], partial=True),
        _retrieval([]),
    )
    service = _service(store, retrieve=fake, max_latency_ms=0.0)
    first = service.prefetch(QUERY, scope=SCOPE)
    second = service.prefetch(QUERY, scope=SCOPE)
    assert first.partial is True
    assert second.cache_hit is False, "a partial build must not be replayed from cache"
    assert len(fake.calls) == 2
    service.close()


# --- the guards ----------------------------------------------------------


def test_no_caller_supplied_vector_means_no_vector_work(store, monkeypatch):
    """The service must never invent a query vector (EM-403's guard)."""
    _add(store, "the Acme staging port is 9090")
    fake = FakeRetrieve(_retrieval([_ranking("m-1", 0.5)]))
    service = _service(store, retrieve=fake)
    service.prefetch(QUERY, scope=SCOPE)
    call = fake.calls[0]
    assert call["query_vector"] is None
    assert call["embedding_model"] is None
    service.close()


def test_a_supplied_vector_passes_through_untouched(store):
    _add(store, "the Acme staging port is 9090")
    fake = FakeRetrieve(_retrieval([_ranking("m-1", 0.5)]))
    service = _service(store, retrieve=fake)
    service.prefetch(QUERY, scope=SCOPE, query_vector=(0.1, 0.2), embedding_model="model-x")
    call = fake.calls[0]
    assert call["query_vector"] == (0.1, 0.2)
    assert call["embedding_model"] == "model-x"
    service.close()


def test_the_generator_priority_is_the_one_4_2_names(store):
    """§4.2: `pinned → bm25 → entity → vector → episodic → recent` — the order
    partial results are kept in."""
    _add(store, "the Acme staging port is 9090")
    fake = FakeRetrieve(_retrieval([]))
    service = _service(store, retrieve=fake)
    service.prefetch(QUERY, scope=SCOPE)
    assert fake.calls[0]["generator_order"] == (
        "pinned",
        "bm25",
        "entity",
        "vector",
        "episodic",
        "recent",
    )
    service.close()


def test_metrics_instances_are_independent_and_start_empty():
    one, two = PrefetchMetrics(), PrefetchMetrics()
    one.record(PrefetchCall(latency_ms=12.0, cache_hit=False, partial=False, injected_count=2, tokens=80))
    assert one.snapshot()["prefetch.latency_ms"]["count"] == 1
    assert two.snapshot()["prefetch.latency_ms"]["count"] == 0
    assert two.snapshot()["prefetch.cache_hit"]["hits"] == 0
