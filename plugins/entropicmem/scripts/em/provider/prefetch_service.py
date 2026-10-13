"""``PrefetchService`` — §4.2's prefetch core (EM-403 slice 1).

One synchronous prefetch call, built exactly as §4.2 specifies and measured by
the card's acceptance harness (``tests/harness/test_prefetch_service_ac.py``):

* **cache** keyed ``(session_id, scope_key, sha1(normalized_query),
  write_generation)``; a hit renders from the cached candidate pool;
* **deadline** ``prefetch.max_latency_ms`` (default 1200) over the generator
  stage — §4.2's priority order ``pinned → bm25 → entity → vector → episodic →
  recent``, remaining generators skipped when the deadline passes, the result
  marked ``partial``;
* **dedup across turns**: a memory injected in any of the last ``dedup_turns``
  (6) turns is skipped unless its score ≥ 0.8 and it was injected more than 2
  turns ago; pinned constraints re-show only every ``constraint_repeat_turns``
  (10) turns, since earlier injections remain in the replayed history;
* **output hard cap** ``min(token_budget * 4, 9000)`` chars (under the host's
  10,000-char spill threshold);
* **the five metrics** ``prefetch.latency_ms/cache_hit/partial/injected_count/
  tokens``.

Four decisions the card leaves open, recorded here rather than left to be
discovered:

* **The read connection is persistent.** §4.2's cross-process invalidation is
  "``PRAGMA data_version`` on the read connection", and that pragma is
  *per-connection*: measured 2026-10-13, a fresh connection always reads ``1``
  while a living connection's value moves when another connection commits. So
  the service keeps one read connection across calls (the factory must return a
  connection usable across threads — ``em.store.db.Store.reader()`` does) and a
  second connection lives on the worker thread, so an abandoned generator can
  never touch the caller's.
* **A generator is abandonable.** "When the deadline passes, remaining
  generators are skipped" cannot interrupt a *blocked* generator (a stuck
  SQLite read, a stuck disk page), and the AC demands the 1.5 s hard cap hold
  for a **forced-slow** generator. Each generator therefore runs on the
  service's single worker thread (created through the injected ``spawn_thread``
  seam — F-005b: no bare ``threading.Thread`` outside ``_spawn``) and is joined
  with the remaining deadline; an overrun is abandoned, its result discarded,
  and while the worker is still stuck the next call fails fast to ``partial``
  (the v2 host's own rule: skipped until the stuck call returns).
* **A partial build is never cached**, and a cache hit re-runs the turn-level
  dedup filter before rendering. A cached block replayed verbatim would be
  exactly the "prompt tokens that grow linearly with turn count" §4.2's dedup
  exists to stop — "Hit → return rendered block" is honoured as *render from
  cache*, the only reading consistent with the AC's "(dedup working)".
* **A supplied query vector is part of the query digest.** The card's key names
  ``sha1(normalized_query)``; when a caller supplies a vector the query *as
  used* includes the model and the vector, so the digest covers them too. The
  default path (no caller-supplied vector) is exactly the card's key, and
  nothing here embeds anything — a query with no caller-supplied vector still
  does no vector work (EM-403's guard).

This module is stdlib-only (plan §3.2) and reads no config (``em/config.py``
stays unwired, EM-407): every knob is a constructor parameter.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import queue
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    FrozenSet,
    List,
    Optional,
    Sequence,
    Tuple,
)

from ..retrieval.packer import (
    DEFAULT_TOKEN_BUDGET,
    PackItem,
    estimate_tokens,
    load_pack_items,
)
from ..retrieval.pipeline import GeneratorDeadline
from ..retrieval.pipeline import retrieve as pipeline_retrieve
from ..retrieval.query import VocabularyCache, strip_memory_context
from ..store.types import Scope
from .render import pack_chosen, render, render_line

log = logging.getLogger("em.provider.prefetch")

__all__ = [
    "OUTPUT_CHAR_CAP",
    "DEFAULT_CONSTRAINT_REPEAT_TURNS",
    "DEFAULT_DEDUP_TURNS",
    "DEFAULT_MAX_LATENCY_MS",
    "GENERATOR_PRIORITY",
    "InjectedRow",
    "PrefetchCall",
    "PrefetchMetrics",
    "PrefetchResult",
    "PrefetchService",
    "normalize_query",
    "scope_key",
]

#: §4.2's output hard cap — under the host's 10,000-char spill threshold.
OUTPUT_CHAR_CAP = 9000

#: §4.2's internal deadline: ``prefetch.max_latency_ms``, default 1200. §4.1's
#: hard internal cap is 1.5 s, which leaves room for the work around the
#: generator stage before the watchdog gives up.
DEFAULT_MAX_LATENCY_MS = 1200.0

#: §4.2's ``prefetch.dedup_turns``.
DEFAULT_DEDUP_TURNS = 6

#: §4.2's ``prefetch.constraint_repeat_turns``.
DEFAULT_CONSTRAINT_REPEAT_TURNS = 10

#: §4.2's generator priority order — the order partial results are kept in.
GENERATOR_PRIORITY: Tuple[str, ...] = (
    "pinned",
    "bm25",
    "entity",
    "vector",
    "episodic",
    "recent",
)

#: The dedup rule's hot threshold ("its score ≥ 0.8") and minimum gap ("it was
#: injected > 2 turns ago"). §3.6's fusion score is the score in ``[0, 1]``.
_HOT_SCORE = 0.8
_HOT_MIN_GAP_TURNS = 2

#: Cache entries kept (§4.2 does not name a size; bounded so a long session
#: cannot grow the map without limit — eviction is LRU).
_CACHE_MAX_ENTRIES = 64

#: Milliseconds the watchdog waits past the deadline before abandoning a
#: generator. The deadline is also the cooperative stop signal ("return what you
#: have"), and without this grace a generator returning its partial result *at*
#: the deadline would lose the race with ``Event.wait`` and have good work
#: discarded. 50 ms keeps the worst case at ``max_latency_ms + 0.05 s``, well
#: under §4.1's 1.5 s cap.
_ABANDON_GRACE_MS = 50.0

#: The owner_type §4.2's dedup rule counts ("a memory injected …").
MEMORY = "memory"


def normalize_query(text: str) -> str:
    """§4.2 step 1 — normalize before anything keys on the query.

    ``<memory-context>…</memory-context>`` blocks are stripped defensively
    (§3.6; a replayed injection is not the user's question) and whitespace is
    collapsed, so two spellings of one question share one cache entry.
    """
    return " ".join(strip_memory_context(text or "").split())


def scope_key(scope: Scope) -> str:
    """A stable hash of the readable set, for the cache key.

    Same guarantee as :attr:`em.policy.scopes.ScopeContext.scope_key` (EM-402):
    every field a read rule can depend on is included, so two scopes with one
    key are guaranteed to read the same rows. Never ``hash()`` — stable across
    processes and runs.
    """
    parts = (
        scope.profile,
        scope.user,
        scope.chat,
        scope.chat_type,
        scope.author,
        "1" if scope.is_owner else "0",
    )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


# --- metrics -------------------------------------------------------------


@dataclass(frozen=True)
class PrefetchCall:
    """One ``prefetch()`` call, as the metrics record it."""

    latency_ms: float
    cache_hit: bool
    partial: bool
    injected_count: int
    tokens: int


class PrefetchMetrics:
    """The five §4.2 metrics, in one holder.

    Counts and totals are lifetime; the latency distribution is a bounded
    rolling window (the histogram ``em.provider.hooks`` deliberately deferred to
    this card). ``snapshot()``'s keys are **exactly** the five metric names.
    """

    def __init__(self, window: int = 256) -> None:
        self._lock = threading.Lock()
        self._window: Deque[float] = deque(maxlen=max(1, int(window)))
        self._calls = 0
        self._latency_total = 0.0
        self._hits = 0
        self._partial = 0
        self._injected_total = 0
        self._tokens_total = 0

    def record(self, call: PrefetchCall) -> None:
        with self._lock:
            self._window.append(call.latency_ms)
            self._calls += 1
            self._latency_total += call.latency_ms
            if call.cache_hit:
                self._hits += 1
            if call.partial:
                self._partial += 1
            self._injected_total += call.injected_count
            self._tokens_total += call.tokens

    @property
    def last_latency_ms(self) -> Optional[float]:
        with self._lock:
            return self._window[-1] if self._window else None

    def reset(self) -> None:
        """Fresh counters — tests only, never product code."""
        with self._lock:
            self._window.clear()
            self._calls = 0
            self._latency_total = 0.0
            self._hits = 0
            self._partial = 0
            self._injected_total = 0
            self._tokens_total = 0

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            samples = sorted(self._window)
            calls = self._calls
            latency_total = self._latency_total
            hits = self._hits
            partial = self._partial
            injected = self._injected_total
            tokens = self._tokens_total
        if samples:
            p50 = samples[max(0, int(round(0.50 * (len(samples) - 1))))]
            p95 = samples[max(0, int(round(0.95 * (len(samples) - 1))))]
            peak = samples[-1]
        else:
            p50 = p95 = peak = 0.0
        return {
            "prefetch.latency_ms": {
                "count": calls,
                "avg": (latency_total / calls) if calls else 0.0,
                "p50": p50,
                "p95": p95,
                "max": peak,
            },
            "prefetch.cache_hit": {
                "calls": calls,
                "hits": hits,
                "rate": (hits / calls) if calls else 0.0,
            },
            "prefetch.partial": {"count": partial},
            "prefetch.injected_count": {
                "total": injected,
                "avg": (injected / calls) if calls else 0.0,
            },
            "prefetch.tokens": {
                "total": tokens,
                "avg": (tokens / calls) if calls else 0.0,
            },
        }


# --- outcomes ------------------------------------------------------------


@dataclass(frozen=True)
class InjectedRow:
    """One row the block actually contains, and what it cost in tokens."""

    owner_type: str
    owner_id: str
    tokens: int


@dataclass(frozen=True)
class PrefetchResult:
    """What one ``prefetch()`` call produced.

    ``injected`` is what survived the budget **and** the hard cap — the set the
    dedup history remembers and ``prefetch.injected_count`` counts. ``partial``
    is §4.2's marker: the deadline cut the generator stage short.
    """

    text: str
    injected: Tuple[InjectedRow, ...] = ()
    cache_hit: bool = False
    partial: bool = False

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    @property
    def injected_count(self) -> int:
        return len(self.injected)


@dataclass(frozen=True)
class _CacheEntry:
    """The turn-independent half of one prefetch: the packer's row pool."""

    items: Tuple[PackItem, ...]
    pinned: FrozenSet[str]


class _GeneratorRequest:
    """One generator call handed to the worker thread."""

    __slots__ = ("name", "fn", "ctx", "done", "result", "error")

    def __init__(self, name: str, fn: Callable[[Any], Any], ctx: Any) -> None:
        self.name = name
        self.fn = fn
        self.ctx = ctx
        self.done = threading.Event()
        self.result: Any = None
        self.error: Optional[BaseException] = None


class PrefetchService:
    """§4.2's prefetch core: cache, deadline, dedup, cap, metrics.

    ``connect()`` returns a read connection usable across the threads that call
    :meth:`prefetch` (``em.store.db.Store.reader()`` does); the service keeps
    one such connection for its whole life, because ``PRAGMA data_version`` is
    only meaningful on a connection that lives across calls. ``spawn_thread
    (target, name)`` starts a background thread (the host's
    ``spawn_context_thread``-based helper in production) and returns anything.
    """

    def __init__(
        self,
        *,
        connect: Callable[[], sqlite3.Connection],
        spawn_thread: Callable[[Callable[[], None], str], Any],
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        max_latency_ms: float = DEFAULT_MAX_LATENCY_MS,
        dedup_turns: int = DEFAULT_DEDUP_TURNS,
        constraint_repeat_turns: int = DEFAULT_CONSTRAINT_REPEAT_TURNS,
        is_trivial: Optional[Callable[[str], bool]] = None,
        retrieve: Optional[Callable[..., Any]] = None,
        metrics: Optional[PrefetchMetrics] = None,
    ) -> None:
        self._connect = connect
        self._spawn_thread = spawn_thread
        self._token_budget = int(token_budget)
        self._max_latency_ms = float(max_latency_ms)
        self._dedup_turns = int(dedup_turns)
        self._constraint_repeat_turns = int(constraint_repeat_turns)
        self._is_trivial = is_trivial
        self._retrieve = pipeline_retrieve if retrieve is None else retrieve
        self._metrics = PrefetchMetrics() if metrics is None else metrics

        self._conn_lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._write_lock = threading.Lock()
        self._local_generation = 0
        self._idf_cache = VocabularyCache()

        self._cache: "OrderedDict[Tuple[str, str, str, str], _CacheEntry]" = OrderedDict()
        self._recent: Dict[str, int] = {}
        self._turn = 0

        self._job_lock = threading.Lock()
        self._requests: "queue.Queue[Any]" = queue.Queue()
        self._outstanding: Optional[_GeneratorRequest] = None
        self._worker_started = False
        self._worker_conn: Optional[sqlite3.Connection] = None

    # -- public surface ---------------------------------------------------

    @property
    def metrics(self) -> PrefetchMetrics:
        return self._metrics

    def note_write(self) -> None:
        """Tell the service a memory write landed in this process.

        The in-process half of §4.2's ``write_generation``; the cross-process
        half is ``PRAGMA data_version`` on the read connection.
        """
        with self._write_lock:
            self._local_generation += 1

    def reset(self) -> None:
        """Clear the cache and the dedup history (``on_session_switch(reset)``).

        The turn counter keeps rising on purpose: it only ever measures gaps
        between injections, and a gap that spans a reset is still a gap.
        """
        self._cache.clear()
        self._recent.clear()

    def close(self) -> None:
        """Stop the worker and close the read connection (``shutdown()``)."""
        if self._worker_started:
            self._requests.put(None)
        with self._conn_lock:
            conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - closing twice is not a failure
                pass

    def prefetch(
        self,
        query: str,
        *,
        scope: Scope,
        session_id: str = "",
        query_vector: Optional[Sequence[float]] = None,
        embedding_model: Optional[str] = None,
    ) -> PrefetchResult:
        """One turn's memory block — §4.2's ``prefetch(query)``.

        ``query_vector``/``embedding_model`` are the caller-supplied EM-303
        seam; with neither (the default) no vector work happens anywhere. The
        service never embeds: a query embedding is computed off this thread by
        the async half (chunk 34) and handed in.
        """
        text = normalize_query(query)
        if not text:
            return PrefetchResult("")
        if self._is_trivial is not None and self._is_trivial(query):
            return PrefetchResult("")

        started = time.perf_counter()
        deadline = time.monotonic() + self._max_latency_ms / 1000.0
        with self._conn_lock:
            conn = self._read_conn()
            generation = self._write_generation(conn)
            key = self._cache_key(generation, text, scope, session_id, query_vector, embedding_model)
            entry = self._cache.get(key)
            hit = entry is not None
            retrieval = None
            if hit:
                self._cache.move_to_end(key)
            else:
                retrieval = self._retrieve(
                    conn,
                    scope=scope,
                    query=text,
                    with_gate=True,
                    query_vector=query_vector,
                    embedding_model=embedding_model,
                    deadline=deadline,
                    generator_order=GENERATOR_PRIORITY,
                    generator_runner=self._run_generator,
                    idf_cache=self._idf_cache,
                    write_generation=generation,
                )
                items = load_pack_items(
                    conn, retrieval.rankings, predecessors=retrieval.predecessors
                )
                pinned = frozenset(
                    owner_id
                    for (_owner_type, owner_id), info in retrieval.rows.items()
                    if getattr(info, "pinned", False)
                )
                entry = _CacheEntry(tuple(items), pinned)
                # A partial build is not a complete answer to cache: the next
                # turn must re-run rather than replay what the deadline cut.
                if not retrieval.partial:
                    self._cache[key] = entry
                    self._cache.move_to_end(key)
                    while len(self._cache) > _CACHE_MAX_ENTRIES:
                        self._cache.popitem(last=False)

            turn = self._turn = self._turn + 1
            kept = self._dedup_filter(entry.items, entry.pinned, turn)
            chosen = pack_chosen(
                kept, budget=self._token_budget, on_flagged="mark", cite="full"
            )
            block = render(chosen, cite="full")
            cap = min(self._token_budget * 4, OUTPUT_CHAR_CAP)
            while chosen and len(block) > cap:
                chosen = chosen[:-1]
                block = render(chosen, cite="full")

            injected = tuple(
                InjectedRow(
                    row.item.owner_type,
                    row.item.owner_id,
                    estimate_tokens(render_line(row, cite="full")),
                )
                for row in chosen
            )
            for row in injected:
                if row.owner_type == MEMORY:
                    self._recent[row.owner_id] = turn
            self._prune_recent(turn)

        partial = bool(retrieval is not None and retrieval.partial)
        result = PrefetchResult(
            text=block, injected=injected, cache_hit=hit, partial=partial
        )
        self._metrics.record(
            PrefetchCall(
                latency_ms=(time.perf_counter() - started) * 1000.0,
                cache_hit=hit,
                partial=partial,
                injected_count=len(injected),
                tokens=result.tokens,
            )
        )
        return result

    # -- cache ------------------------------------------------------------

    def _cache_key(
        self,
        generation: str,
        text: str,
        scope: Scope,
        session_id: str,
        query_vector: Optional[Sequence[float]],
        embedding_model: Optional[str],
    ) -> Tuple[str, str, str, str]:
        """§4.2's key: ``(session_id, scope_key, sha1(normalized_query), write_generation)``.

        With a caller-supplied vector the query *as used* includes the model and
        the vector, so the digest covers them (the default path is exactly the
        card's key).
        """
        material = text
        if query_vector is not None:
            vector_digest = hashlib.sha1(
                repr(tuple(float(v) for v in query_vector)).encode("utf-8")
            ).hexdigest()
            material = f"{text}\x1f{embedding_model or ''}\x1f{vector_digest}"
        return (
            session_id,
            scope_key(scope),
            hashlib.sha1(material.encode("utf-8")).hexdigest(),
            generation,
        )

    def _write_generation(self, conn: sqlite3.Connection) -> str:
        with self._write_lock:
            local = self._local_generation
        row = conn.execute("PRAGMA data_version").fetchone()
        return f"{local}:{row[0] if row else 0}"

    def _read_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    # -- dedup (§4.2) -----------------------------------------------------

    def _dedup_filter(
        self,
        items: Sequence[PackItem],
        pinned: FrozenSet[str],
        turn: int,
    ) -> List[PackItem]:
        """§4.2's rule, for memories only.

        A memory injected in any of the last ``dedup_turns`` turns is skipped
        unless its score ≥ 0.8 and it was injected more than 2 turns ago;
        pinned constraints re-show only every ``constraint_repeat_turns`` turns.
        """
        kept: List[PackItem] = []
        for item in items:
            if item.owner_type != MEMORY:
                kept.append(item)
                continue
            last = self._recent.get(item.owner_id)
            if last is None:
                kept.append(item)
                continue
            gap = turn - last
            if item.owner_id in pinned:
                if gap >= self._constraint_repeat_turns:
                    kept.append(item)
                continue
            if gap > self._dedup_turns:
                kept.append(item)
            elif gap > _HOT_MIN_GAP_TURNS and item.score >= _HOT_SCORE:
                kept.append(item)
        return kept

    def _prune_recent(self, turn: int) -> None:
        horizon = max(self._dedup_turns, self._constraint_repeat_turns) + 1
        self._recent = {
            owner_id: last
            for owner_id, last in self._recent.items()
            if turn - last <= horizon
        }

    # -- the generator watchdog -------------------------------------------

    def _run_generator(self, name: str, fn: Callable[[Any], Any], ctx: Any) -> Any:
        """``pipeline.retrieve``'s ``generator_runner`` seam.

        Runs one generator on the service's worker thread and joins it with the
        remaining deadline; an overrun raises :class:`GeneratorDeadline`, which
        marks the result partial and skips the rest. While the worker is still
        busy with an abandoned call, every call fails fast the same way.
        """
        self._ensure_worker()
        request = _GeneratorRequest(name, fn, ctx)
        with self._job_lock:
            previous = self._outstanding
            if previous is not None and not previous.done.is_set():
                raise GeneratorDeadline(f"worker busy with {previous.name!r}")
            self._outstanding = request
            self._requests.put(request)
        timeout: Optional[float] = None
        if ctx.deadline is not None:
            timeout = (
                max(0.0, ctx.deadline - time.monotonic()) + _ABANDON_GRACE_MS / 1000.0
            )
        if not request.done.wait(timeout):
            raise GeneratorDeadline(name)
        if request.error is not None:
            raise request.error
        return request.result

    def _ensure_worker(self) -> None:
        with self._job_lock:
            if self._worker_started:
                return
            self._worker_started = True
        self._spawn_thread(self._worker_loop, "em-prefetch-worker")

    def _worker_loop(self) -> None:
        """The single worker thread (§4.2). It owns its own read connection.

        An abandoned request still runs to completion here; its result lands on
        a request nobody reads, which is the cost of not being able to kill a
        thread in Python — bounded, and the fail-fast path above means it never
        blocks a later call.
        """
        try:
            while True:
                request = self._requests.get()
                if request is None:
                    return
                try:
                    if self._worker_conn is None:
                        self._worker_conn = self._connect()
                    ctx = dataclasses.replace(request.ctx, conn=self._worker_conn)
                    request.result = request.fn(ctx)
                except BaseException as exc:  # noqa: BLE001 - carried to the caller
                    request.error = exc
                finally:
                    request.done.set()
        finally:
            conn, self._worker_conn = self._worker_conn, None
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001 - closing twice is not a failure
                    pass
