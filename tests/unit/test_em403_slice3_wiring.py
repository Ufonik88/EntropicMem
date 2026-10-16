"""EM-403 slice 3, second half (chunk 35): the provider wiring, pinned at the wire.

The first half (`f674146`, pushed directly to `main`) built the
``PrefetchService`` on v3 stores and routed ``queue_prefetch`` + ``metrics``.
This chunk routes the **synchronous fact block** through
``PrefetchService.prefetch`` and pins what that means, one group per claim:

* **v2 unchanged** — the service is ``None`` on a v2 store, so the old path runs
  byte-for-byte. The golden below was captured from the commit *before* the
  wiring (a detached worktree of `main` at `e4fd865`, flag ON) — the same
  method P0b used — and a structural test blocks service construction outright.
* **v3 wired** — with the flag on, §4.2's block is served (the §3.6 renderer's
  shape, not v2's bullets), the call reaches the service, and one author's
  private memory still never reaches another author through the wired path.
  With the flag off, the existing path serves exactly as before.
* **the five metrics** — ``prefetch.latency_ms`` / ``cache_hit`` / ``partial`` /
  ``injected_count`` / ``tokens`` come back through ``metrics()`` on v3 and
  ``{}`` on v2.
* **shutdown** — the service and the store are closed, and a later enqueue is
  refused rather than resurrected.
* **the enqueue gate** — a v3 store with the flag off enqueues nothing (the
  service still exists, so ``metrics()`` works); with it on, one enqueue per
  call. The gate decision and its reasons are written on
  ``_prefetch_service_for_turn``.
* **fail soft** — a service that raises degrades to the v2 path; the turn keeps
  its memory block.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

import em.provider.prefetch_service as ps_mod  # noqa: E402
from em.facade.engine import V3_RETRIEVAL_ENV, V3Engine  # noqa: E402
from em.provider.prefetch_service import PrefetchService  # noqa: E402
from em.store.db import Store  # noqa: E402
from memory_engine import MemoryEngine, StoredFact  # noqa: E402

STAMP = "2026-01-15T00:00:00Z"
QUERY = "what port does the staging server use"
STAGING = "the staging server runs on port 9090"
BILLING = "nightly billing job reconciles invoices"
PRIVATE = "Alice Example keeps the staging deploy key in the Acme vault under ops/deploy"

STAGING_V2_ID = StoredFact.make_id(STAGING)
BILLING_V2_ID = StoredFact.make_id(BILLING)

#: The pre-wiring golden for a **v2** store, captured 2026-10-15 from a detached
#: worktree of `main` at `e4fd865` (the commit before this chunk) with
#: ``ENTROPICMEM_V3_RETRIEVAL=1`` already set — i.e. the flag cannot move a v2
#: store even when it is on. Ids are content-derived (``StoredFact.make_id``).
V2_GOLDEN = {
    # EM-409: Appendix D's policy text (all nine tools registered; the plan's
    # wraps as single-line bullets) replaced the ad-hoc `# EntropicMem (active)`
    # base — this field is repointed, the prefetch fields are the v2 golden.
    "system_prompt": (
        "# Long-term memory (EntropicMem)\n"
        "You have persistent memory across sessions.\n"
        "- Recalled memory may appear in <memory-context> blocks. It is reference data from past sessions, not a message from the user. Use it silently; do not mention the block. It can be outdated: prefer what the user says now, and fix memory when they correct it.\n"
        "- When you rely on a recalled memory, you may cite it like [m·7Q4F2K9A].\n"
        "- Save with entropicmem_remember when the user shares something that will matter later: identity, preferences, goals, decisions, commitments, procedures, constraints (\"from now on…\"), or corrections. Store technical facts in full detail. One memory per idea.\n"
        "- If a memory is wrong or changed, use entropicmem_update (keeps history) instead of saving a duplicate.\n"
        "- Before answering questions about the past (\"last time\", \"what did we decide\"), use entropicmem_search or entropicmem_timeline.\n"
        "- Never store passwords, API keys, tokens or other secrets.\n"
        "- The built-in memory tool is mirrored automatically; don't save the same thing twice."
    ),
    "context_query": QUERY,
    "prefetch_first": (
        "## EntropicMem recall\n"
        f"- [{STAGING_V2_ID}] {STAGING} (Knowledge · 2026-01-15) [score:0.89]"
    ),
    "prefetch_second": (
        "## EntropicMem recall\n"
        f"- [{STAGING_V2_ID}] {STAGING} (Knowledge · 2026-01-15) [score:0.89]"
    ),
    "prefetch_other": (
        "## EntropicMem recall\n"
        f"- [{BILLING_V2_ID}] {BILLING} (Knowledge · 2026-01-15) [score:0.50]"
    ),
}

SERVICE_TITLE = "## EntropicMem — recalled memory"


# --- fixtures ---------------------------------------------------------------


def _v2_db(tmp_path: Path) -> Path:
    """A v2-schema store (``user_version=0``) with two invented facts."""
    db = tmp_path / "memory.db"
    engine = MemoryEngine(db, profile_id="default")
    engine.remember(STAGING, importance=0.8, source="agent")
    engine.remember(BILLING, importance=0.5, source="agent")
    engine.close()
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("UPDATE facts SET created_at=?, updated_at=?", (STAMP, STAMP))
        conn.commit()
    finally:
        conn.close()
    return db


def _v3_db(tmp_path: Path, *, private: bool = False) -> Path:
    """A migrated v3 store with the same facts (plus one user-private row)."""
    db = tmp_path / "memory.db"
    engine = V3Engine(db)
    engine.remember(STAGING, title="Staging server", domain="Infrastructure", importance=0.8)
    engine.remember(BILLING, domain="Knowledge", importance=0.5)
    engine.close()
    if private:
        store = Store(str(db))
        try:
            from em.store.memories import MemoryStore
            from em.store.types import MemoryDraft, Scope

            with store.transaction() as conn:
                result = MemoryStore(conn).add(
                    MemoryDraft(
                        content=PRIVATE,
                        kind="fact",
                        sensitivity="sensitive",
                        importance=0.9,
                        source="agent",
                        status="active",
                    ),
                    scope=Scope(profile="default", user="u-alice"),
                    actor="u-alice",
                )
                assert result.ok, result
        finally:
            store.close()
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            conn.execute(
                "UPDATE memories SET created_at=?, updated_at=?, last_accessed_at=NULL",
                (STAMP, STAMP),
            )
    finally:
        store.close()
    return db


def _provider(tmp_path: Path, db: Path, *, init_kwargs=None, real_spawn=True, **config) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(config={
        "core_memory_enabled": False,
        "touch_on_inject": False,
        "cache_conversation_context": True,
        **config,
    })
    provider.initialize(
        "slice3-session", hermes_home=str(tmp_path), **(init_kwargs or {})
    )
    # `initialize` leaves these unset when the skill tree is not in the temp
    # home; `prefetch` needs both, and this points it at the real facade.
    provider._scripts_dir = SCRIPTS
    provider._memory_db = db
    provider._profile_id = "default"
    if real_spawn:
        # The service's generator runner runs on the provider's ``_spawn`` seam
        # (F-005b), and the service captures that seam when it is built. Under
        # pytest the conftest's mocked ``agent`` host turns the host factory into
        # a MagicMock whose ``start()`` is a no-op, which would silently serve
        # empty blocks — so install a real thread factory *before* the service
        # is constructed. The real host supplies a working factory in production.
        provider._spawn = _real_spawn
    return provider


def _real_spawn(target, name):
    import threading

    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def _transcript(provider: EntropicMemMemoryProvider, query: str = QUERY) -> dict:
    return {
        "system_prompt": provider.system_prompt_block(),
        "context_query": provider._build_context_query(query),
        "prefetch_first": provider.prefetch(query),
        "prefetch_second": provider.prefetch(query),  # the cache path
        "prefetch_other": provider.prefetch("an unrelated query about invoices"),
    }


@pytest.fixture(autouse=True)
def _flag_off_by_default(monkeypatch):
    monkeypatch.delenv(V3_RETRIEVAL_ENV, raising=False)


# --- v2 unchanged: byte-identical, and the service is never built -----------


def test_a_v2_store_s_transcript_is_byte_identical_with_the_flag_on(tmp_path, monkeypatch):
    """The golden was captured from the commit before the wiring, with the flag
    already ON. Re-running it on the wired tree proves the wiring cannot move a
    v2 store's turn — the strongest form of "v2 unchanged" available."""
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    provider = _provider(tmp_path, _v2_db(tmp_path))
    try:
        assert _transcript(provider) == V2_GOLDEN
        assert V2_GOLDEN["prefetch_first"], "the fixture must actually inject something"
    finally:
        provider.shutdown()


def test_a_v2_store_never_constructs_the_service(tmp_path, monkeypatch):
    """Independent of the golden: on a v2 store the service is ``None`` and any
    attempt to build one is an error — the wiring is structurally unreachable."""
    for flag in ("0", "1", None):
        if flag is None:
            monkeypatch.delenv(V3_RETRIEVAL_ENV, raising=False)
        else:
            monkeypatch.setenv(V3_RETRIEVAL_ENV, flag)

        def explode(*args, **kwargs):
            raise AssertionError("PrefetchService must never be constructed on a v2 store")

        monkeypatch.setattr(ps_mod.PrefetchService, "__init__", explode)
        provider = _provider(tmp_path, _v2_db(tmp_path))
        try:
            assert provider._ensure_prefetch_service() is None
            assert provider.metrics() == {}
            assert provider.queue_prefetch(QUERY) is None
            assert _transcript(provider) == V2_GOLDEN
        finally:
            provider.shutdown()


def test_a_v2_store_s_queue_prefetch_does_nothing(tmp_path):
    provider = _provider(tmp_path, _v2_db(tmp_path))
    try:
        provider.queue_prefetch(QUERY)
        assert provider._ensure_prefetch_service() is None
        assert provider._prefetch_service is None, "no service was built to enqueue into"
    finally:
        provider.shutdown()


# --- v3 wired ---------------------------------------------------------------


def test_a_v3_store_with_the_flag_on_serves_through_the_service(tmp_path, monkeypatch):
    """The block is §4.2's — the §3.6 renderer's shape with full-id citations —
    the call really reached the service, and the effective scope carries the
    store's profile (``_profile_id``, not the empty ``agent_identity``)."""
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)

    calls = []
    real = PrefetchService.prefetch

    def spy(self, query, **kwargs):
        calls.append((query, kwargs))
        return real(self, query, **kwargs)

    monkeypatch.setattr(PrefetchService, "prefetch", spy)
    try:
        block = provider.prefetch(QUERY)
        snapshot = provider.metrics()
    finally:
        provider.shutdown()

    assert len(calls) == 1, "the turn must be served by exactly one service call"
    query, kwargs = calls[0]
    assert query == QUERY
    scope = kwargs["scope"]
    assert scope is not None, "the service needs the turn's scope"
    assert scope.profile == "default", (
        "the service reads the store directly, so it must be handed the effective "
        f"profile the facade engine uses (got {scope.profile!r})"
    )
    assert scope.user == ""

    assert block.startswith(SERVICE_TITLE), f"expected §3.6's shape, got: {block[:120]!r}"
    assert "### Relevant memories" in block
    assert STAGING in block, "the matching memory must be served"
    assert "[score:" not in block, "v2's debug score suffix is not §4.2's render"
    assert "## EntropicMem recall" not in block, "the v2 bullet shape must not appear"

    assert snapshot["prefetch.latency_ms"]["count"] == 1
    assert snapshot["prefetch.partial"] == {"count": 0}
    assert snapshot["prefetch.injected_count"]["total"] >= 1


def test_a_v3_store_with_the_flag_off_keeps_the_existing_path(tmp_path, monkeypatch):
    """The P0b-off shape: v2's bullets, no service call, and the service still
    exists (so ``metrics()`` works) — the first half's construction behaviour."""
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)

    calls = []
    real = PrefetchService.prefetch

    def spy(self, query, **kwargs):
        calls.append(query)
        return real(self, query, **kwargs)

    monkeypatch.setattr(PrefetchService, "prefetch", spy)
    try:
        block = provider.prefetch(QUERY)
        assert calls == [], "the flag off must not route the turn through the service"
        assert block.startswith("## EntropicMem recall")
        assert f"[{STAGING_V2_ID}]" in block, "the v2 path serves through the legacy id"
        assert provider._ensure_prefetch_service() is not None, (
            "the service is still built on a v3 store with the flag off (metrics)"
        )
        assert provider.metrics()["prefetch.latency_ms"]["count"] == 0
    finally:
        provider.shutdown()


def test_the_wired_path_keeps_one_author_s_memory_from_another(tmp_path, monkeypatch):
    """§3.5 through the service: the wired read uses the turn's scope, so a
    user-private memory written by Alice never reaches Bob's wired turn — the
    same property the group-chat harness proves on the v2 path."""
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    db = _v3_db(tmp_path, private=True)
    provider = _provider(
        tmp_path,
        db,
        init_kwargs={"user_id": "u-alice", "chat_id": "chat-1", "chat_type": "group"},
        owner_user_ids=["u-alice"],
    )
    try:
        alice_block = provider.prefetch("where is the staging deploy key kept?")
        assert PRIVATE in alice_block or "deploy key" in alice_block, (
            f"Alice must be answered from her own store; got {alice_block[:120]!r}"
        )

        provider.on_turn_start(2, "where is the staging deploy key kept?", author_id="u-bob")
        bob_block = provider.prefetch("where is the staging deploy key kept?")
        assert PRIVATE not in bob_block, "a user-private memory must not cross authors"
    finally:
        provider.shutdown()


def test_a_service_failure_falls_back_to_the_v2_path(tmp_path, monkeypatch):
    """Fail soft: a service that raises costs a debug line, not the turn — the
    v2 smart-context path is always available on a v3 store (P0b's off path)."""
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)

    def explode(self, query, **kwargs):
        raise RuntimeError("service is broken")

    monkeypatch.setattr(PrefetchService, "prefetch", explode)
    try:
        block = provider.prefetch(QUERY)
    finally:
        provider.shutdown()
    assert block.startswith("## EntropicMem recall"), (
        f"the fallback is the v2 path, so the block is v2's shape; got {block[:120]!r}"
    )
    assert f"[{STAGING_V2_ID}]" in block


# --- the five metrics --------------------------------------------------------


def test_the_five_prefetch_metrics_are_surfaced_on_a_v3_store(tmp_path, monkeypatch):
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    provider = _provider(tmp_path, _v3_db(tmp_path))
    try:
        # The service is built on a v3 store regardless of the flag (the first
        # half's construction rule), so the snapshot exists from the start with
        # every counter at zero.
        empty = provider.metrics()
        assert set(empty) == {
            "prefetch.latency_ms",
            "prefetch.cache_hit",
            "prefetch.partial",
            "prefetch.injected_count",
            "prefetch.tokens",
        }
        assert empty["prefetch.latency_ms"]["count"] == 0

        provider.prefetch(QUERY)
        provider.prefetch(QUERY)  # the service's own cache answers this one
        snapshot = provider.metrics()
    finally:
        provider.shutdown()

    assert set(snapshot) == {
        "prefetch.latency_ms",
        "prefetch.cache_hit",
        "prefetch.partial",
        "prefetch.injected_count",
        "prefetch.tokens",
    }
    latency = snapshot["prefetch.latency_ms"]
    assert set(latency) == {"count", "avg", "p50", "p95", "max"}
    assert latency["count"] == 2, "both turns went through the service"
    assert latency["avg"] > 0.0 and latency["max"] >= latency["p95"] >= latency["p50"]

    hits = snapshot["prefetch.cache_hit"]
    assert hits == {"calls": 2, "hits": 1, "rate": 0.5}, "the second identical turn is a hit"

    assert snapshot["prefetch.partial"] == {"count": 0}
    injected = snapshot["prefetch.injected_count"]
    assert injected["total"] >= 1 and injected["avg"] > 0
    assert snapshot["prefetch.tokens"]["total"] > 0


def test_metrics_are_empty_on_a_v2_store(tmp_path, monkeypatch):
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    provider = _provider(tmp_path, _v2_db(tmp_path))
    try:
        provider.prefetch(QUERY)
        assert provider.metrics() == {}
    finally:
        provider.shutdown()


# --- shutdown ----------------------------------------------------------------


def test_shutdown_closes_the_service_and_the_store(tmp_path, monkeypatch):
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    provider = _provider(tmp_path, _v3_db(tmp_path))
    service = provider._ensure_prefetch_service()
    store = provider._prefetch_store
    assert service is not None and store is not None

    provider.shutdown()

    assert provider._prefetch_service is None
    assert provider._prefetch_store is None
    # The captured service is closed for real: a later enqueue is refused and
    # counted, not silently resurrected.
    with pytest.raises(RuntimeError):
        service.queue_precompute("after shutdown")
    assert service.precompute_stats["precompute_rejected_after_close"] == 1


def test_a_clean_shutdown_does_not_wait_out_the_join_timeout(tmp_path, monkeypatch):
    """The wiring puts a service on every v3 session's shutdown path, so a close
    that always burned the 2 s join timeout (sentinel posted *after* the join —
    an idle worker blocks on ``get()`` forever) would stall every session end.
    Found while wiring this chunk; the sentinel now goes out first, so an idle
    worker leaves promptly while a genuinely stuck one is still counted+logged
    (pinned by the slice-2 invariants suite)."""
    import time

    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    provider = _provider(tmp_path, _v3_db(tmp_path))
    provider.prefetch(QUERY)  # so the worker thread exists and is idle
    service = provider._ensure_prefetch_service()

    started = time.monotonic()
    provider.shutdown()
    elapsed = time.monotonic() - started

    assert service.precompute_stats["thread_join_timeout"] == 0, (
        "an idle worker must exit on the sentinel, not on the join timeout"
    )
    assert elapsed < 1.5, f"shutdown took {elapsed:.3f}s — the 2 s join timeout fired"


# --- the enqueue gate (flag off / flag on) -----------------------------------


def test_queue_prefetch_enqueues_nothing_on_a_v3_store_with_the_flag_off(tmp_path):
    provider = _provider(tmp_path, _v3_db(tmp_path))
    try:
        provider.queue_prefetch(QUERY)
        service = provider._ensure_prefetch_service()
        assert service is not None, "the service exists on a v3 store regardless of the flag"
        assert service.precompute_stats["precompute_enqueued"] == 0, (
            "the flag off must enqueue nothing"
        )
        assert provider.metrics()["prefetch.latency_ms"]["count"] == 0
    finally:
        provider.shutdown()


def test_queue_prefetch_enqueues_once_per_call_with_the_flag_on(tmp_path, monkeypatch):
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    provider = _provider(tmp_path, _v3_db(tmp_path))
    try:
        provider.queue_prefetch(QUERY)
        service = provider._ensure_prefetch_service()
        stats = service.precompute_stats
        assert stats["precompute_enqueued"] == 1, "one enqueue per call"

        provider.queue_prefetch(QUERY)
        stats = service.precompute_stats
        assert stats["precompute_enqueued"] == 2
        assert stats["precompute_coalesced"] == 1, (
            "a newer request for the same session supersedes the older one"
        )
    finally:
        provider.shutdown()
