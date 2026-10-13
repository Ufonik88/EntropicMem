"""EM-403's acceptance criterion: the `PrefetchService` harness (§4.2).

One test per line of the card's AC, driving the service over real v3 stores the
way the provider will (chunk 35 wires it; this harness pins the component):

1. warm p95 ≤ 150 ms @ 50k memories;
2. the cache-hit path ≤ 10 ms;
3. a forced-slow generator → returns within 1.5 s with a partial result;
4. the block never exceeds 9,000 chars;
5. cumulative replayed memory tokens over 50 turns ≤ 50 × budget × 0.6
   (dedup working).

Every stopwatch test prints its distribution (the `perf-smoke` lesson: a low
p50 with a huge max is one noisy sample, not a slow path), and the 50k corpus is
a **performance fixture only** — it supports no quality claim.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import to_iso, utc_now  # noqa: E402
from em.provider.prefetch_service import PrefetchService  # noqa: E402
from em.retrieval import candidates  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

SCOPE = Scope(profile="ac-prefetch")
BUDGET = 450  # §3.6's prefetch.token_budget default


def _spawn(target, name):
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


@pytest.fixture()
def store(tmp_path):
    store = Store(str(tmp_path / "memory.db"))
    with store.writer() as writer:
        migrate(writer)
    yield store
    store.close()


def _add(store, content, *, pinned=False, kind="fact", **draft):
    with store.transaction() as writer:
        result = MemoryStore(writer).add(
            MemoryDraft(
                content=content,
                kind=kind,
                source="agent",
                status="active",
                pinned=pinned,
                **draft,
            ),
            scope=SCOPE,
            actor="tester",
        )
        assert result.ok
        return result.id


def _service(store, **kwargs):
    return PrefetchService(connect=store.reader, spawn_thread=_spawn, **kwargs)


def _report(name, samples):
    ordered = sorted(samples)
    p95 = ordered[max(0, int(0.95 * len(ordered)) - 1)]
    print(
        f"[ac] {name}: n={len(ordered)} p50={ordered[len(ordered)//2]:.2f} ms "
        f"p95={p95:.2f} ms max={ordered[-1]:.2f} ms"
    )
    return p95


# --- AC 3: forced-slow generator -----------------------------------------


def test_a_forced_slow_generator_returns_within_1_5s_with_a_partial_result(
    store, monkeypatch
):
    """A generator that ignores the deadline contract entirely (the shape a
    blocked SQLite read or a stuck disk page takes) must not blow §4.1's hard
    1.5 s internal cap: it is abandoned, the rest is served, and the result is
    marked partial."""
    _add(store, "never deploy on a Friday", pinned=True, kind="constraint")
    _add(store, "the Acme staging port is 9090 and it is used for builds only")

    def slow(ctx):
        time.sleep(3.0)  # no deadline check at all — deliberately contract-breaking
        return []

    monkeypatch.setitem(candidates.GENERATORS, "recent", slow)
    service = _service(store)  # default max_latency_ms=1200
    started = time.monotonic()
    result = service.prefetch("what is the staging port?", scope=SCOPE)
    elapsed = time.monotonic() - started
    service.close()
    print(f"[ac] forced-slow generator: prefetch returned in {elapsed:.3f}s")
    assert elapsed < 1.5, f"prefetch took {elapsed:.3f}s — the hard cap is 1.5 s"
    assert result.partial is True, "the run must be marked partial"
    assert result.text, "the generators that finished must still be served"
    assert "9090" in result.text or "Friday" in result.text


# --- AC 4: the char cap ---------------------------------------------------


def test_the_block_never_exceeds_9000_chars(store):
    for n in range(12):
        _add(store, f"staging port fact {n}: " + "port detail " * 150)
    service = _service(store, token_budget=50_000)  # the cap must come from the char rule
    result = service.prefetch("which staging port?", scope=SCOPE)
    service.close()
    print(f"[ac] hard cap: block is {len(result.text)} chars")
    assert result.text, "some rows must survive"
    assert len(result.text) <= 9_000, f"{len(result.text)} chars > the 9,000 cap"
    # and the cap is min(token_budget*4, 9000) — with a 50k budget, exactly 9000
    assert result.injected, "the injected set is what survived the cap"


# --- AC 5: cumulative replayed tokens over 50 turns -----------------------


def test_cumulative_replayed_memory_tokens_over_50_turns_stays_under_the_dedup_bound(
    store,
):
    """50 distinct turns all surface the same five memories. §4.2's dedup rule
    is what keeps the replayed tokens — the rows that ride again in what Hermes
    replays byte-for-byte on later requests — under `50 × budget × 0.6`.

    The hot set is sized to **fill a turn's budget** (5 × ~130-token rows under
    a 450-token budget): with a smaller corpus the bound is satisfied even with
    dedup broken, which mutation-checking caught — a turn that injects only
    ~54% of the budget can replay every turn and stay under `0.6 × budget`. The
    bound only means "(dedup working)" when re-injecting everything per turn is
    guaranteed to blow it.

    The rows are also **cold** (fusion score below the rule's 0.8 hot
    threshold): a hot row is re-shown every 3 turns *by §4.2's own rule*, which
    makes the replay bound unsatisfiable by design — the hot escape valve is
    pinned by `test_a_hot_memory_re_shows_after_three_turns` instead.
    """
    hot = [
        f"staging port fact {n}: the service-{n} staging port is {9000 + n} and it is"
        " used for integration builds in the Frankfurt cluster every night. The port"
        f" number for service {n} changed twice this quarter, once after the firewall"
        " migration and once after the load balancer was reconfigured by the platform"
        " team. Anyone deploying to the staging environment must use this exact port"
        " and must never hard-code the old value in a script, because the smoke tests"
        " will fail in a way that looks like a network outage but is really a stale"
        f" configuration value. Service {n} owners should confirm the port with the"
        " platform team before each release train."
        for n in range(5)
    ]
    for content in hot:
        _add(store, content, importance=0.05, confidence=0.05)

    service = _service(store, token_budget=BUDGET)
    replayed = 0
    total = 0
    first_turn_tokens = 0
    seen = set()
    for turn in range(50):
        result = service.prefetch(f"question {turn}: which staging port?", scope=SCOPE)
        for row in result.injected:
            if row.owner_type != "memory":
                continue
            total += row.tokens
            if turn == 0:
                first_turn_tokens += row.tokens
            if row.owner_id in seen:
                replayed += row.tokens
            seen.add(row.owner_id)
    service.close()
    bound = 50 * BUDGET * 0.6
    print(
        f"[ac] replay over 50 turns: replayed={replayed} tokens, total={total} tokens, "
        f"first turn={first_turn_tokens} tokens, bound={bound:.0f}"
    )
    assert first_turn_tokens > 0.6 * BUDGET, (
        "the hot set must fill a turn's budget, or the bound below is satisfied "
        "even with dedup broken (mutation-checked 2026-10-13)"
    )
    assert replayed <= bound, (
        f"cumulative replayed memory tokens {replayed} > 50 x budget x 0.6 = {bound:.0f}"
    )


# --- AC 2: the cache-hit path --------------------------------------------


def test_the_cache_hit_path_is_under_10ms(store):
    for n in range(5):
        _add(
            store,
            f"staging port fact {n}: the service-{n} staging port is {9000 + n} and it"
            " is used for integration builds in the Frankfurt cluster every night",
        )
    service = _service(store, token_budget=BUDGET)
    service.prefetch("which staging port is used for builds?", scope=SCOPE)  # warm it
    samples = []
    for probe in range(20):
        started = time.perf_counter()
        result = service.prefetch("which staging port is used for builds?", scope=SCOPE)
        samples.append((time.perf_counter() - started) * 1000.0)
        assert result.cache_hit is True
    service.close()
    p95 = _report("cache-hit path", samples)
    assert p95 < 10.0, f"cache-hit p95 {p95:.2f} ms > 10 ms"


# --- AC 1: warm p95 @ 50k ------------------------------------------------


def test_warm_p95_at_50k_is_under_150ms(tmp_path):
    """The card's AC at scale: 50k memories, warm, p95 ≤ 150 ms. The corpus is a
    performance fixture; it supports no quality claim."""
    store = Store(str(tmp_path / "big.db"))
    with store.writer() as writer:
        migrate(writer)

    stamp = to_iso(utc_now())
    topics = ["billing", "deployments", "search", "mobile", "auth", "reports"]
    rows = []
    for i in range(50_000):
        topic = topics[i % len(topics)]
        rows.append(
            (
                f"mem_{i:06d}",
                "ac-prefetch",
                "",
                "profile",
                "fact",
                f"memory {i} about {topic}: the {topic} staging port is {8000 + (i % 1000)}"
                " and it is used for integration builds",
                f"h{i:06d}",
                "agent",
                stamp,
                stamp,
                "active",
            )
        )
    with store.transaction() as conn:
        conn.executemany(
            "INSERT INTO memories (id, scope_profile, scope_user, visibility, kind,"
            " content, content_hash, source, created_at, updated_at, status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )

    service = _service(store, token_budget=BUDGET)
    warmup = [
        "which billing staging port is used for builds?",
        "what is the deployments staging port?",
        "where is the search staging port configured?",
        "what is the mobile staging port?",
        "which auth staging port is used for integration builds?",
    ]
    for query in warmup:
        service.prefetch(query, scope=SCOPE)

    samples = []
    for probe in range(25):
        topic = topics[probe % len(topics)]
        query = f"probe {probe}: what is the {topic} staging port?"
        started = time.perf_counter()
        result = service.prefetch(query, scope=SCOPE)
        samples.append((time.perf_counter() - started) * 1000.0)
        assert result.text, f"probe {probe} found nothing in 50k rows"
    service.close()
    store.close()
    p95 = _report("warm prefetch @ 50k", samples)
    assert p95 <= 150.0, f"warm p95 {p95:.2f} ms > 150 ms (samples: {samples})"
