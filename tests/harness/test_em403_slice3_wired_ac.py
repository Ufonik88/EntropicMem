"""EM-403's acceptance criterion, re-run through the **wired provider** (chunk 35).

Slice 1's harness (``test_prefetch_service_ac.py``) pins the card's AC at the
service leaf; this one replays the same five lines through
``EntropicMemProvider.prefetch`` on a v3 store with
``ENTROPICMEM_V3_RETRIEVAL=1`` — the wiring this chunk adds — so the AC is
evidence about the path a turn actually takes, not only about the component:

1. warm p95 ≤ 150 ms @ 50k memories;
2. the cache-hit path ≤ 10 ms;
3. a forced-slow generator → returns within 1.5 s with a partial result;
4. the block never exceeds 9,000 chars;
5. cumulative replayed memory tokens over 50 turns ≤ 50 × budget × 0.6
   (dedup working).

Every stopwatch test prints its distribution (the ``perf-smoke`` lesson: a low
p50 with a huge max is one noisy sample, not a slow path), and the 50k corpus is
a **performance fixture only** — it supports no quality claim. Invented data
only; the live store is never touched.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins" / "entropicmem" / "scripts"
for _entry in (str(ROOT), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

from em.clock import to_iso, utc_now  # noqa: E402
from em.facade.engine import V3_RETRIEVAL_ENV  # noqa: E402
from em.retrieval import candidates  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

SCOPE = Scope(profile="default")
BUDGET = 450  # §3.6's prefetch.token_budget default; the provider derives it
# as ``prefetch_token_budget // 4``, so a config of 1800 buys exactly this.
PROVIDER_TOKEN_CHARS = BUDGET * 4


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    """The wired path's gate: a v3 store plus the flag. The flag's default is
    untouched — this fixture sets it for the duration of the test only."""
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")


def _real_spawn(target, name):
    """A real thread factory, installed before the service is built.

    The service's generator runner runs on the provider's ``_spawn`` seam
    (F-005b) and captures it at construction. Under pytest the conftest's
    mocked ``agent`` host turns the host factory into a MagicMock whose
    ``start()`` is a no-op, which would silently serve empty blocks.
    """
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def _store(tmp_path) -> Store:
    store = Store(str(tmp_path / "memory.db"))
    with store.writer() as writer:
        migrate(writer)
    return store


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


def _provider(tmp_path, store, **config) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(config={
        "core_memory_enabled": False,
        "touch_on_inject": False,
        "cache_conversation_context": True,
        "prefetch_token_budget": PROVIDER_TOKEN_CHARS,
        **config,
    })
    provider.initialize("wired-ac-session", hermes_home=str(tmp_path))
    provider._scripts_dir = SCRIPTS
    provider._memory_db = store.path if hasattr(store, "path") else str(tmp_path / "memory.db")
    provider._profile_id = "default"
    provider._spawn = _real_spawn
    return provider


def _report(name, samples):
    ordered = sorted(samples)
    p95 = ordered[max(0, int(0.95 * len(ordered)) - 1)]
    print(
        f"[ac-wired] {name}: n={len(ordered)} p50={ordered[len(ordered)//2]:.2f} ms "
        f"p95={p95:.2f} ms max={ordered[-1]:.2f} ms"
    )
    return p95


def _row_tokens(line: str) -> int:
    return max(1, len(line) // 4) if line else 0


# --- AC 3: forced-slow generator -----------------------------------------


def test_a_forced_slow_generator_returns_within_1_5s_with_a_partial_result(
    tmp_path, monkeypatch
):
    """The same contract-breaking generator the leaf harness uses, now behind
    the provider: §4.1's 1.5 s hard cap holds on the turn path, the run is
    marked partial in the provider's own metrics, and the generators that
    finished are still served."""
    store = _store(tmp_path)
    try:
        _add(store, "never deploy on a Friday", pinned=True, kind="constraint")
        _add(store, "the Acme staging port is 9090 and it is used for builds only")

        def slow(ctx):
            time.sleep(3.0)  # no deadline check at all — deliberately contract-breaking
            return []

        monkeypatch.setitem(candidates.GENERATORS, "recent", slow)
        provider = _provider(tmp_path, store)
        started = time.monotonic()
        try:
            block = provider.prefetch("what is the staging port?")
        finally:
            elapsed = time.monotonic() - started
            provider.shutdown()
        print(f"[ac-wired] forced-slow generator: provider.prefetch returned in {elapsed:.3f}s")
        assert elapsed < 1.5, f"prefetch took {elapsed:.3f}s — the hard cap is 1.5 s"
        assert block, "the generators that finished must still be served"
        assert "9090" in block or "Friday" in block
        assert block.startswith("## EntropicMem — recalled memory"), (
            "the wired turn is §4.2's render, not v2's bullets"
        )
    finally:
        store.close()


# --- AC 4: the char cap ---------------------------------------------------


def test_the_block_never_exceeds_9000_chars_through_the_provider(tmp_path):
    store = _store(tmp_path)
    try:
        for n in range(12):
            _add(store, f"staging port fact {n}: " + "port detail " * 150)
        # A legacy budget far above the cap: EM-407 folds the character count to
        # the typed rule's maximum (2,000 tokens) — the block still may not pass
        # the 9,000-char rule, which is what this drives.
        provider = _provider(tmp_path, store, prefetch_token_budget=200_000)
        try:
            block = provider.prefetch("which staging port?")
            print(f"[ac-wired] hard cap: block is {len(block)} chars")
        finally:
            provider.shutdown()
        assert block, "some rows must survive"
        assert len(block) <= 9_000, f"{len(block)} chars > the 9,000 cap"
    finally:
        store.close()


# --- AC 5: cumulative replayed tokens over 50 turns -----------------------


def test_cumulative_replayed_memory_tokens_over_50_turns_stays_under_the_dedup_bound(
    tmp_path,
):
    """50 distinct turns, all surfacing the same five memories, driven through
    ``provider.prefetch``. Same fixture discipline as the leaf harness: the hot
    set fills a turn's budget and is cold (score below §4.2's 0.8 hot rule), so
    the bound means "(dedup working)" only if replaying everything would blow it.

    "Replayed" is measured the way the host replays: a row's line that has
    already been injected in an earlier turn of this session rides again in what
    the API re-sends, and its tokens are counted then.
    """
    store = _store(tmp_path)
    try:
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

        provider = _provider(tmp_path, store)
        replayed = 0
        total = 0
        first_turn_tokens = 0
        seen = set()
        try:
            for turn in range(50):
                block = provider.prefetch(f"question {turn}: which staging port?")
                for line in (ln for ln in block.splitlines() if ln.startswith("- [")):
                    owner_id = line.split("]", 1)[0][3:]
                    cost = _row_tokens(line)
                    total += cost
                    if turn == 0:
                        first_turn_tokens += cost
                    if owner_id in seen:
                        replayed += cost
                    seen.add(owner_id)
        finally:
            provider.shutdown()
        bound = 50 * BUDGET * 0.6
        print(
            f"[ac-wired] replay over 50 turns: replayed={replayed} tokens, total={total}"
            f" tokens, first turn={first_turn_tokens} tokens, bound={bound:.0f}"
        )
        assert first_turn_tokens > 0.6 * BUDGET, (
            "the hot set must fill a turn's budget, or the bound below is satisfied "
            "even with dedup broken"
        )
        assert replayed <= bound, (
            f"cumulative replayed memory tokens {replayed} > 50 x budget x 0.6 = {bound:.0f}"
        )
    finally:
        store.close()


# --- AC 2: the cache-hit path --------------------------------------------


def test_the_cache_hit_path_is_under_10ms_through_the_provider(tmp_path):
    store = _store(tmp_path)
    try:
        for n in range(5):
            _add(
                store,
                f"staging port fact {n}: the service-{n} staging port is {9000 + n} and it"
                " is used for integration builds in the Frankfurt cluster every night",
            )
        provider = _provider(tmp_path, store)
        try:
            provider.prefetch("which staging port is used for builds?")  # warm it
            samples = []
            for _ in range(20):
                started = time.perf_counter()
                provider.prefetch("which staging port is used for builds?")
                samples.append((time.perf_counter() - started) * 1000.0)
            hits = provider.metrics()["prefetch.cache_hit"]
        finally:
            provider.shutdown()
        assert hits["hits"] == 20, f"every probe must be a service cache hit: {hits}"
        p95 = _report("cache-hit path through the provider", samples)
        assert p95 < 10.0, f"cache-hit p95 {p95:.2f} ms > 10 ms"
    finally:
        store.close()


# --- AC 1: warm p95 @ 50k ------------------------------------------------


def test_warm_p95_at_50k_is_under_150ms_through_the_provider(tmp_path):
    """The card's AC at scale through the wired path: 50k memories, warm,
    p95 ≤ 150 ms, one ``provider.prefetch`` per probe (core block, context
    query, shadow check and §4.2's serve all included). The corpus is a
    performance fixture; it supports no quality claim."""
    store = _store(tmp_path)
    try:
        stamp = to_iso(utc_now())
        topics = ["billing", "deployments", "search", "mobile", "auth", "reports"]
        rows = []
        for i in range(50_000):
            topic = topics[i % len(topics)]
            rows.append(
                (
                    f"mem_{i:06d}",
                    "default",
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

        provider = _provider(tmp_path, store)
        warmup = [
            "which billing staging port is used for builds?",
            "what is the deployments staging port?",
            "where is the search staging port configured?",
            "what is the mobile staging port?",
            "which auth staging port is used for integration builds?",
        ]
        try:
            for query in warmup:
                provider.prefetch(query)
            samples = []
            for probe in range(25):
                topic = topics[probe % len(topics)]
                query = f"probe {probe}: what is the {topic} staging port?"
                started = time.perf_counter()
                block = provider.prefetch(query)
                samples.append((time.perf_counter() - started) * 1000.0)
                assert block, f"probe {probe} found nothing in 50k rows"
        finally:
            provider.shutdown()
        p95 = _report("warm prefetch @ 50k through the provider", samples)
        assert p95 <= 150.0, f"warm p95 {p95:.2f} ms > 150 ms (samples: {samples})"
    finally:
        store.close()
