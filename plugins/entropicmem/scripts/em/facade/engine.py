"""EM-211: the v3 facade engine — the v2 ``MemoryEngine`` API over ``em.store``.

``V3Engine`` keeps the v2 engine API (the exact surface the Hermes provider
uses is pinned in ``em.facade.contract``) on top of the v3 storage core.

Chunk 4 landed the READ half: ``get_fact`` (including ``legacy_id``
resolution, which is what the provider's mirror lookup needs), ``stats``,
``recall_with_relevance``, ``recall_hybrid`` and ``next_episode_wave``.
Chunk 5 landed the WRITE half: ``remember``, ``forget``, ``touch``,
``extract_and_store``, ``prune_pending``, ``add_episode`` and ``consolidate``.
The mirror call and the entity linker are chunks 6 and 7. Nothing here is wired
into the provider yet.

Design notes for reviewers:

* The load-bearing pair is ``remember`` + ``get_fact``. The provider finds a
  mirror row with ``get_fact(StoredFact.make_id(content))`` where
  ``make_id = sha256(content)[:16]``; v3 ids are ULIDs, so ``remember`` stamps
  that value as ``legacy_id`` and ``MemoryStore.get`` resolves it. Because
  ``memories.legacy_id`` is UNIQUE and content-derived, it is stamped only for
  a profile-wide write (v2 had one owner per database); a user-scoped row
  leaves it empty so two users can store the same sentence.
* A v2 write did its policy, PII, duplicate, version, outbox and audit work
  inline. Here ``MemoryStore.add`` owns all of it, so ``remember`` is
  translation rather than reimplementation — that is the point of the size
  guard in the plan.
* Writes that mean to destroy or archive first take a throttled snapshot
  (``snapshot_if_due``), outside the write transaction: EM-210's "100 forget
  calls give at most one snapshot an hour" is met here, by the facade, rather
  than by v2's unthrottled per-call ``_backup()``.
* Recall borrows v2's ``StoredFact`` and scoring helpers
  (``build_fts_query``, ``coverage``, ``run_fts_match``, the LIKE fallback)
  from ``memory_engine`` — lazily, because at 3.0 ``memory_engine.py`` becomes
  a back-compat shim over this facade and a module-level import would be a
  cycle — so the parity suite pins identical behaviour while S3 builds the
  real v3 retriever. Returned ``StoredFact.id`` is ``legacy_id`` when the row
  carries one (migrated or mirrored rows) else the v3 id, the card's rule.
* Only ``status='active'`` memories recall, and a ``deleted`` row reads as
  absent through ``get_fact`` too: v2's ``forget`` removed the row outright.
  Pending rows surface through ``get_fact`` by id (v2 kept them in a separate
  table the recall paths never touched) but never through recall.
* ``recall_hybrid``'s vector leg is EM-303; until it lands, hybrid is the
  FTS-only pass — exactly what v2 does when embeddings are off.
  ``expand_links`` and ``auto_reinforce`` are accepted and inert: graph
  expansion needs the v2 ``graph_edges`` (it moves with the mirror chunk) and
  reinforcement is a graph-edge write that moves with the linker chunk.
  Recorded as ``Deviation:`` in the PR.

Recorded v3 semantic changes from v2, each pinned by a test:

* ``remember`` does not fuzzy-overwrite. v2's EM-109 near-duplicate rule could
  rewrite a stored fact in place; v3 only collapses *exact* duplicates
  (``noop_duplicate``) and otherwise inserts, with the version row recording
  the change. Silent overwrite of a memory is what the card forbids.
* ``forget`` and ``consolidate`` move rows through the §3.4 state machine
  (``deleted`` / ``archived``) instead of deleting them or copying them into a
  side ``facts_archive`` table. ``get_fact`` and ``stats`` read a terminal row
  as absent, so callers see v2's behaviour; the row and its versions stay for
  the audit trail.
* ``add_episode`` has nowhere to put ``linked_fact_ids``, ``domain`` or
  ``source``: v3's ``episodes`` table carries ``decisions``/``open_loops``/
  ``entities`` instead, and adding a column would mean a migration, which this
  chunk does not take. They are accepted and ignored.
* No deprecation warnings. The card asks for once-per-process warnings on
  methods "suled for removal in 3.1"; v2 emits none, no list of which methods
  is recorded anywhere, and the provider calls all of them on every session.
  Emitting warnings v2 never emitted would be a behaviour change nobody asked
  for, so the facade matches v2 and the requirement stays open.

Stdlib-only apart from the v2 helpers named above; never imports the provider
or the Hermes host (plan §3.2).
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..clock import parse_iso, to_iso, utc_now
from ..store.audit import append as audit_append
from ..store.backup import BackupManager
from ..store.db import Store
from ..store.episodes import EpisodeStore
from ..store.memories import MemoryStore, _in_scope  # noqa: F401  (the one §3.5 rule)
from ..store.migrations import migrate
from ..store.types import MemoryDraft, Scope

logger = logging.getLogger("em.facade.engine")

__all__ = ["V3Engine"]

#: fts columns on ``memories_fts`` the facade searches (v2's ``title`` lives
#: in ``summary`` in v3).
_FTS_FIELDS = ("content", "summary", "tags")

#: How many rows a listing write may consider. A consolidate/prune pass walks
#: candidate rows, so it cannot use ``MemoryStore.list``'s page default; a
#: million-row store is not a real profile, and an unbounded walk would be a
#: long transaction, which invariant 2 forbids.
_SCAN_LIMIT = 10_000

#: v2's ``_EXTRACTION_PATTERNS`` lives on the class, so the preference
#: patterns that v2 wrote inline in ``extract_and_store`` are repeated here
#: rather than imported. They are pure regex with no store access; keeping the
#: copy next to the comment that names the source makes the drift visible.
_PREFERENCE_PATTERNS: tuple[tuple[str, str, float], ...] = (
    (r"(?:i|we)\s+(?:prefer|want|like|use|using|need)\s+(.+?)(?:\.\s|$)", "People", 0.5),
    (r"(?:don't|do not|never)\s+(?:want|like|need|use)\s+(.+?)(?:\.\s|$)", "People", 0.5),
)

#: v2's ``MemoryEngine._sanitize_fact_text`` patterns, mirrored exactly. It is
#: a bound method on a class the facade must not construct, and stripping the
#: host's fence tags is a write-path rule that has to hold before anything is
#: stored. ``test_remember_sanitizer_matches_the_v2_engine_byte_for_byte``
#: pins this against v2 so the two copies cannot drift.
_SANITIZE_PATTERNS: tuple[str, ...] = (
    r"</?\s*memory-context\s*>",
    r"(?im)^\s*ignore (all |any )?(previous|prior|above) instructions\s*:?\s*",
    r"(?im)^\s*system\s*:\s*",
    r"(?im)^\s*developer\s*:\s*",
)


def _sanitize_fact_text(content: str) -> str:
    """Strip prompt-injection markers and fence tags before durable storage."""
    if not content:
        return content
    out = content
    for pattern in _SANITIZE_PATTERNS:
        out = re.sub(pattern, "", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()



def _v2():
    """The v2 ``memory_engine`` module, resolved lazily.

    Chunk 4 borrows v2's ``StoredFact`` and scoring helpers so the parity
    suite pins identical behaviour until S3 ships the v3 retriever. The
    import must NOT be at module level: at 3.0 ``memory_engine.py`` turns into
    a back-compat shim over this facade, and a top-level import there×here
    would deadlock. ``sys.modules`` makes the repeated call a dict lookup.
    """
    mod = sys.modules.get("memory_engine")
    if mod is None:
        import memory_engine as mod
    return mod


def _row_to_fact(row: Dict[str, Any]) -> Any:
    """Build the v2 view of one v3 ``memories`` row.

    ``id`` is ``legacy_id`` when present (migrated v2 rows and mirrored rows
    carry the content-derived id), else the v3 id — the card's rule.
    """
    StoredFact = _v2().StoredFact
    legacy = row.get("legacy_id") or ""
    try:
        tags = json.loads(row.get("tags") or "[]")
    except (TypeError, ValueError):
        tags = []
    return StoredFact(
        id=legacy or row["id"],
        content=row["content"],
        title=row.get("summary") or "",
        source=row.get("source") or "agent",
        importance=row["importance"] if row.get("importance") is not None else 0.5,
        domain=row.get("domain") or "Knowledge",
        tags=list(tags) if isinstance(tags, list) else [],
        created_at=row.get("created_at") or "",
        updated_at=row.get("updated_at") or "",
        last_accessed=row.get("last_accessed_at") or "",
        access_count=row.get("access_count") or 0,
        sensitivity=row.get("sensitivity") or "internal",
    )


def _parse_ts(stamp: Optional[str]) -> Optional[datetime]:
    """Parse a v3 timestamp, or ``None`` if it is missing or malformed.

    The facade must **not** borrow v2's ``_parse_ts``. v3 timestamps are written
    by :func:`em.clock.to_iso` with a trailing ``Z``, and Python 3.10's
    ``datetime.fromisoformat`` rejects that suffix — so on 3.10 v2's parser
    returns ``None`` for every v3 timestamp. That silently made ``consolidate``
    archive nothing (every row looked unparseable, so never old enough) and
    ``_decay_factor`` return 1.0 for everything. ``em.clock.parse_iso``
    normalises the suffix on purpose and is the v3 layer's own parser; this is
    the None-safe wrapper the scoring and consolidation paths need.
    """
    if not stamp:
        return None
    try:
        return parse_iso(stamp)
    except (TypeError, ValueError):
        return None


def _decay_factor(
    fact: Any,
    now_ts: datetime,
    half_life_days: float,
    decay_floor: float,
    evergreen_domains: set,
) -> float:
    """EM-106 decay semantics, the same rule the v2 engine applies (parity)."""
    if (
        fact.importance >= 0.75
        or fact.domain in evergreen_domains
        or fact.source in ("built_in_memory", "promoted")
        or "pinned" in (fact.tags or [])
    ):
        return 1.0
    parse = _parse_ts
    stamps = [s for s in (parse(fact.updated_at), parse(fact.last_accessed)) if s]
    if not stamps:
        return 1.0
    age_days = max(0.0, (now_ts - max(stamps)).total_seconds() / 86400.0)
    lam = math.log(2) / half_life_days if half_life_days > 0 else 0.0
    return max(decay_floor, math.exp(-lam * age_days))


class V3Engine:
    """The v2 engine API over the v3 store (EM-211: reads and writes)."""

    def __init__(
        self,
        db_path: "Path | str",
        *,
        profile_id: str = "default",
        scope_user: str = "",
        scope_chat: str = "",
        is_owner: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.store = Store(self.db_path)
        # Profile-wide by default (v2 had one owner per DB): the facade maps a
        # v2 profile onto Scope(profile=..., user="") — §3.5's profile-wide
        # read, which is also the owner context, so the default facade reads and
        # writes exactly as v2 did.
        #
        # ``scope_user`` and ``is_owner`` are the gateway identity the provider
        # will supply when it is wired onto this facade. ``is_owner`` defaults to
        # False (fail-closed): a scoped caller must assert ownership to read a
        # `sensitive`/`secret` row, so a wiring mistake hides the owner's own
        # sensitive rows — a visible bug — instead of showing them to a guest,
        # which is a silent one. The provider computes it as `not _is_guest()`.
        # Never an environment read: identity is passed in, always.
        self.scope = Scope(
            profile=profile_id, user=scope_user, chat=scope_chat, is_owner=is_owner
        )
        with self.store.writer() as conn:
            migrate(conn)

    # --- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "V3Engine":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # --- reads ---------------------------------------------------------------

    def _reader(self) -> sqlite3.Connection:
        return self.store.reader()

    def get_fact(self, entropic_id: str) -> Optional[Any]:
        """Resolve by v3 id, v2 ``legacy_id`` (the mirror-lookup path) or id prefix.

        A ``deleted`` row reads as absent: v2's ``forget`` removed the row, so
        callers test absence with ``is None``. The read is scoped: a sensitive or
        secret row resolves only for its owner, so a guest gets ``None`` exactly
        as if it were not there.
        """
        row = MemoryStore(self._reader()).get(entropic_id, scope=self.scope)
        if row is None or row["status"] == "deleted":
            return None
        return _row_to_fact(row)

    def find_mirrored(self, needle: Optional[str]) -> Optional[str]:
        """EM-110 mirror fallback, v3: the id of an ``active`` mirrored memory.

        The v2 engine owns the same method with the same contract, so the
        provider's ``_locate_mirror`` can call it without knowing which engine
        it holds — that is the whole point of moving the scan off ``engine.db``,
        which was the last raw-connection read the provider made and the one
        thing this facade could not serve.

        Three filters v2 got for free and v3 has to state, because a forgotten
        mirror that is still locatable would let a replace resurrect it:

        * ``status='active'``, so a ``deleted`` or ``archived`` row never matches;
        * the §3.5 scope rule (invariant 5), so one user cannot locate another
          user's mirror — a profile-wide row stays visible to everyone in the
          profile, which is what ``_in_scope`` allows;
        * ``mirrored`` as a whole tag. v3 stores tags as a JSON list, so the SQL
          ``LIKE`` is only a cheap pre-filter; the parsed list is what decides.
          The parse also has to insist on a *list*, because ``tags`` holding the
          JSON scalar ``"mirrored"`` would pass both the ``LIKE`` and a plain
          ``in`` test on the decoded string.

        The returned id resolves through ``get_fact`` and ``forget``, which is
        what the provider does with it.
        """
        text = (needle or "").strip()
        if not text:
            return None

        clauses = ["status='active'", "scope_profile=?", "tags LIKE ?"]
        params: List[Any] = [self.scope.profile, '%"mirrored"%']
        if self.scope.user:
            clauses.append("(scope_user=? OR scope_user='')")
            params.extend([self.scope.user])

        rows = self._reader().execute(
            f"SELECT id, content, tags, scope_profile, scope_user, sensitivity"
            f" FROM memories WHERE {' AND '.join(clauses)}"
            " ORDER BY rid",
            params,
        ).fetchall()
        for row in rows:
            # §3.5 again: a sensitive mirror is owner-only like any other read,
            # so a guest cannot locate (and therefore cannot replace or remove)
            # the owner's mirrored row.
            if not _in_scope(dict(row), self.scope):
                continue
            try:
                tag_list = json.loads(row["tags"] or "[]")
            except (TypeError, ValueError):
                tag_list = []
            if not isinstance(tag_list, list):
                tag_list = []
            if "mirrored" in tag_list and text in (row["content"] or ""):
                return row["id"]
        return None

    def stats(self) -> dict:
        conn = self._reader()
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status='active'"
        ).fetchone()[0]
        domains = conn.execute(
            "SELECT domain, COUNT(*) AS cnt FROM memories WHERE status='active'"
            " GROUP BY domain ORDER BY cnt DESC"
        ).fetchall()
        return {
            "fact_count": int(count),
            "db_path": str(self.db_path),
            "domains": {r["domain"]: int(r["cnt"]) for r in domains},
        }

    def next_episode_wave(self, episode_base: str) -> int:
        """Next ``{base}_wN`` for migrated/legacy-tagged episode ids (v2 parity).

        v3 episode ids are ULIDs; the wave naming lives in ``legacy_id`` (what
        the v2-to-v3 migration writes, and what the writes chunk will keep
        writing), so the cadence-digest logic survives the cutover untouched.
        """
        like = _v2().escape_like(episode_base) + "_w%"
        rows = self._reader().execute(
            "SELECT legacy_id FROM episodes WHERE legacy_id LIKE ? ESCAPE '\\'",
            (like,),
        ).fetchall()
        n = 0
        for row in rows:
            tail = str(row["legacy_id"]).rsplit("_w", 1)[-1]
            if tail.isdigit():
                n = max(n, int(tail))
        return n + 1

    def recall_with_relevance(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        min_relevance: float = 0.0,
        decay_enabled: bool = True,
        decay_half_life_days: float = 90.0,
        decay_floor: float = 0.5,
        evergreen_domains: Optional[Sequence[str]] = None,
        reinforcement_boost: float = 0.1,
        auto_reinforce: bool = False,
    ) -> List[Any]:
        """EM-105/EM-106 scoring over the v3 ``memories_fts`` index.

        Same formula as v2 — relevance = 0.75*coverage + 0.25*rank_bonus,
        combined = relevance * decay * (0.85 + 0.3*importance), clipped — so
        the parity suite pins identical behaviour while S3 replaces this with
        the v3 retriever. ``auto_reinforce`` is accepted and inert here:
        reinforcement is a write and lands with Chunk 5 (``Deviation``).
        """
        if not query.strip():
            return []

        v2 = _v2()
        fts_query = v2.build_fts_query(query, fields=_FTS_FIELDS)
        where = ""
        params: tuple = ()
        if domain:
            where = "AND m.domain = ?"
            params = (domain,)

        match_failed = False
        rows: list = []
        if fts_query:
            found, fts_reason = v2.run_fts_match(
                self._reader(),
                "SELECT m.*, bm25(memories_fts) AS rank"
                " FROM memories_fts JOIN memories m ON memories_fts.rowid = m.rid"
                f" WHERE memories_fts MATCH ? AND m.status='active' {where}"
                " ORDER BY rank LIMIT ?",
                (fts_query, *params, top_k * 2),
            )
            match_failed = fts_reason == v2.FTS_REASON_MATCH_ERROR
            # §3.5: the authoritative rule, applied through the one function that
            # defines it, so recall cannot drift from get_fact. The SQL already
            # narrowed by status; this adds scope and the owner-only tier.
            rows = [row for row in found if _in_scope(dict(row), self.scope)]

        if not rows:
            if not v2._like_fallback_ok(query, match_failed):
                return []
            return self._like_fallback(query, top_k, domain, min_relevance, match_failed)

        query_terms = v2.coverage_terms(query)
        evergreen: set = (
            set(evergreen_domains) if evergreen_domains is not None else {"People"}
        )
        now_ts = utc_now()

        results: List[Any] = []
        for idx, row in enumerate(rows):
            fact = _row_to_fact(dict(row))
            text = " ".join(
                p for p in (fact.title, fact.content, " ".join(fact.tags or [])) if p
            )
            lex = v2.coverage(query_terms, text)
            rank_bonus = 1.0 / (1.0 + 0.15 * idx)
            relevance = 0.75 * lex + 0.25 * rank_bonus
            fact.decay_score = (
                _decay_factor(fact, now_ts, decay_half_life_days, decay_floor, evergreen)
                if decay_enabled
                else 1.0
            )
            combined = min(
                1.0, max(0.0, relevance * fact.decay_score * (0.85 + 0.3 * fact.importance))
            )
            if combined >= min_relevance:
                fact.relevance_score = combined
                fact.why_retrieved = v2.MemoryEngine._build_reasons(
                    fts_match=True,
                    recency_applied=decay_enabled,
                    importance_applied=True,
                    domain_filtered=bool(domain),
                ) + [{"signal": "coverage", "value": round(lex, 4)}]
                results.append(fact)

        results.sort(key=lambda f: f.relevance_score, reverse=True)
        return results[:top_k]

    def _like_fallback(
        self,
        query: str,
        top_k: int,
        domain: Optional[str],
        min_relevance: float,
        match_error: bool,
    ) -> List[Any]:
        """Escaped literal LIKE sweep — v2's symbol-query path, same rule."""
        v2 = _v2()
        where = ""
        params: tuple = ()
        if domain:
            where = "AND domain = ?"
            params = (domain,)
        like = f"%{v2.escape_like(query)}%"
        rows = self._reader().execute(
            "SELECT * FROM memories"
            " WHERE status='active' AND (content LIKE ? ESCAPE '\\'"
            "  OR summary LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\')"
            f" {where} ORDER BY importance DESC LIMIT ?",
            (like, like, like, *params, top_k),
        ).fetchall()
        results = []
        for row in rows:
            # §3.5, the same rule as the FTS path — the exact-query fallback must
            # not become a way around the owner-only tier.
            if not _in_scope(dict(row), self.scope):
                continue
            fact = _row_to_fact(dict(row))
            fact.relevance_score = fact.importance * 0.8
            if fact.relevance_score >= min_relevance:
                fact.why_retrieved = v2.MemoryEngine._build_reasons(
                    like_fallback=True,
                    importance_applied=True,
                    domain_filtered=bool(domain),
                    match_error=match_error,
                )
                results.append(fact)
        return results

    def recall_hybrid(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        fts_weight: float = 0.6,
        vec_weight: float = 0.4,
        expand_links: bool = False,
        auto_reinforce: bool = False,
    ) -> List[Any]:
        """Hybrid recall. Chunk 4: the FTS leg only.

        v2 already falls back to exactly this when embeddings are off, and the
        v3 vector search is EM-303's job (the ``embed`` queue is not wired to
        a retriever yet). ``expand_links`` needs the v2 graph tables and moves
        with the mirror chunk; both differences are ``Deviation:`` in the PR.
        """
        return self.recall_with_relevance(query, top_k=top_k, domain=domain)

    # --- writes ---------------------------------------------------------------

    def _legacy_id(self, content: str) -> str:
        """The v2-shaped id to stamp on this write, or ``""`` for a scoped one.

        ``memories.legacy_id`` is UNIQUE and content-derived. v2 used that id as
        the primary key with one owner per database; v3 scopes every row to a
        user, so two users storing the same sentence are two facts that would
        collide on one hash. Stamping only the profile-wide case keeps the
        provider's mirror lookup (``get_fact(make_id(content))``, which only
        ever looks for the owner's own mirrored content) exactly as reliable as
        v2, and leaves a user-scoped row to resolve by its v3 id.
        """
        if self.scope.user:
            return ""
        return _v2().StoredFact.make_id(content)

    def remember(
        self,
        content: str = "",
        title: str = "",
        source: str = "agent",
        importance: float = 0.5,
        domain: str = "Knowledge",
        tags: Optional[List[str]] = None,
        session_id: str = "",
        sensitivity: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> str:
        """Store a durable fact and return its id.

        ``MemoryStore.add`` runs the whole v2 pipeline — policy, PII redaction,
        injection screening, exact-duplicate collapse, the version row, the
        sync outbox, the audit row and the queued embed job — so this is
        translation, not a second implementation. A repeated write of identical
        content collapses onto the existing row and returns its id
        (``remember-idempotent``); a policy block raises, as v2 did; a policy
        quarantine lands in ``pending``, as v2's quarantine did.
        """
        from policy import normalize_sensitivity  # local: shared optional module

        text = _sanitize_fact_text(content or "")
        if not text.strip():
            raise ValueError("empty content after sanitize")

        draft = MemoryDraft(
            content=text,
            summary=title,
            domain=domain,
            sensitivity=normalize_sensitivity(sensitivity, domain),
            source=source,
            source_session=session_id,
            importance=importance,
            tags=tuple(tags or ()),
            status="active",
            legacy_id=self._legacy_id(text),
        )
        with self.store.transaction() as conn:
            result = MemoryStore(conn).add(
                draft, scope=self.scope, actor=actor or "facade"
            )
        if not result.ok:
            # The store already wrote the refusal to the audit chain.
            raise ValueError(result.reason_code or "write blocked by policy")
        return result.id

    def forget(self, entropic_id: str, *, confirm: bool = False) -> bool:
        """Forget a fact by id; requires ``confirm=True``.

        A status transition to ``deleted``, not a row delete: ``get_fact``
        reads a terminal row as absent and ``stats`` leaves it out of the live
        count, so callers see v2's behaviour, while the row and its version
        history stay for the audit trail. Returns True when a row went and
        False when there was nothing left to take — so forgetting twice is
        False the second time, exactly as v2's DELETE reported it.
        """
        if not confirm:
            with self.store.transaction() as conn:
                audit_append(conn, "forget_denied", "facade", entropic_id,
                             {"reason": "confirm_false"}, ok=False)
            raise ValueError("forget requires confirm=True")

        row = MemoryStore(self._reader()).get(entropic_id)
        if row is None or row["status"] == "deleted":
            return False

        # Outside the write transaction on purpose (§3.3): copying the database
        # is slow work and must not hold the single writer while it happens.
        # Throttled, so a run of forgets cannot fill the backup directory.
        BackupManager(self.db_path).snapshot_if_due(reason="pre-forget")

        with self.store.transaction() as conn:
            result = MemoryStore(conn).set_status(
                row["id"], "deleted", actor="facade", reason="forget"
            )
        return result.ok

    def touch(self, fact_ids: Sequence[str]) -> int:
        """Batched ``last_accessed`` bump; returns how many ids matched.

        ``last_accessed`` is the decay clock, so this is the same call v2 made.
        Ids are resolved through ``MemoryStore.get``, which also accepts a v2
        ``legacy_id`` or a unique id prefix — the provider passes back whatever
        ``get_fact`` handed it, and on a migrated profile that is a legacy id.
        """
        wanted = [i for i in fact_ids if i]
        if not wanted:
            return 0
        with self.store.transaction() as conn:
            store = MemoryStore(conn)
            resolved: list[str] = []
            for one in wanted:
                row = store.get(one)
                if row is not None and row["id"] not in resolved:
                    resolved.append(row["id"])
            if resolved:
                store.touch(resolved, field="accessed")
        return len(resolved)

    def extract_and_store(
        self,
        user_text: str = "",
        assistant_text: str = "",
        session_id: str = "",
        source: str = "auto_extracted",
        min_confidence: float = 0.4,
        promote: bool = True,
    ) -> List[Dict[str, Any]]:
        """Regex extraction of candidate facts; no LLM and no new call.

        Every candidate is quarantined into ``pending`` — the write policy
        routes an ``auto_extracted`` source there — and ``promote=True`` then
        commits it over the ``pending -> active`` edge, which is what v2's
        separate promotion write did. One versioned row instead of v2's two,
        and the extraction record is the same row.
        """
        combined = f"{user_text}\n{assistant_text}"
        if not combined.strip():
            return []

        candidates: List[tuple[str, str, float, str, str]] = []
        for pattern, domain, importance, tag in _v2()._EXTRACTION_PATTERNS:
            for match in re.finditer(pattern, combined, re.IGNORECASE):
                content = match.group(0).strip()
                if len(content) < 10 or len(content) > 500:
                    continue
                if importance < min_confidence:
                    continue
                candidates.append((content, domain, importance, tag, "auto_extract"))
        for pattern, domain, importance in _PREFERENCE_PATTERNS:
            for match in re.finditer(pattern, combined, re.IGNORECASE):
                content = f"Preference: {match.group(1).strip().capitalize().rstrip('.')}."
                if len(content) < 15 or len(content) > 300:
                    continue
                candidates.append(
                    (content, domain, importance, "preference", "auto_extract_preference")
                )

        extracted: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for content, domain, importance, tag, reason in candidates:
            if content in seen:
                continue
            seen.add(content)
            stored = self._store_candidate(
                content=content, domain=domain, importance=importance, tag=tag,
                reason=reason, session_id=session_id, promote=promote,
            )
            if stored is not None:
                extracted.append(stored)
        return extracted

    def _store_candidate(
        self, *, content: str, domain: str, importance: float, tag: str,
        reason: str, session_id: str, promote: bool,
    ) -> Optional[Dict[str, Any]]:
        """Quarantine one extracted candidate, optionally promoting it."""
        draft = MemoryDraft(
            content=content,
            domain=domain,
            importance=importance,
            tags=(tag,),
            source="auto_extracted",
            source_session=session_id,
            status="pending",
            pending_reason=reason,
            # No legacy_id: an extracted candidate is not a content-addressed
            # mirror row, so it must not claim the profile-wide content id.
            legacy_id="",
        )
        with self.store.transaction() as conn:
            store = MemoryStore(conn)
            result = store.add(draft, scope=self.scope, actor="facade")
            if not result.ok or not result.id:
                return None
            pending = result.status == "pending"
            if promote and pending:
                promoted = store.set_status(
                    result.id, "active", actor="facade", reason="auto_commit"
                )
                if promoted.ok:
                    pending = False
        return {
            "id": result.id,
            "content": content,
            "domain": domain,
            "importance": importance,
            "tag": tag,
            "pending": pending,
        }

    def prune_pending(self, older_than_days: int = 30) -> int:
        """TTL purge of the pending quarantine; returns how many went.

        v2 deleted the rows outright. Here each one takes the §3.4
        ``pending -> deleted`` edge with reason ``ttl_expired``, so the purge is
        audited and versioned like every other change.
        """
        cutoff = to_iso(utc_now() - timedelta(days=older_than_days))
        removed = 0
        with self.store.transaction() as conn:
            store = MemoryStore(conn)
            rows = store.list(scope=self.scope, status=("pending",),
                              limit=_SCAN_LIMIT, order="created_at ASC")
            for row in rows:
                if (row.get("created_at") or "") >= cutoff:
                    continue
                gone = store.set_status(row["id"], "deleted", actor="facade",
                                        reason="ttl_expired")
                if gone.ok:
                    removed += 1
        return removed

    def add_episode(
        self,
        title: str = "",
        summary: str = "",
        *,
        start_ts: Optional[str] = None,
        end_ts: Optional[str] = None,
        source_session: str = "",
        linked_fact_ids: Optional[List[str]] = None,
        importance: float = 0.5,
        domain: str = "Knowledge",
        source: str = "agent",
        episode_id: Optional[str] = None,
    ) -> str:
        """Store a distilled episodic record (session summary / timeline entry).

        The episode id lands in ``episodes.legacy_id``, which is what
        ``next_episode_wave`` reads, so the cadence-digest numbering survives
        the cutover. A caller-supplied ``episode_id`` is replaced in place: the
        provider derives it from the session id and refires it, and v2's
        ``INSERT OR REPLACE`` made that convergent. Without a session key the
        episode is ``manual``, which keeps it out of a session's window
        numbering.

        ``linked_fact_ids``, ``domain`` and ``source`` are accepted and
        ignored: v3's ``episodes`` table has no column for them and giving it
        one would mean a migration, which this chunk does not take.
        """
        legacy = episode_id or ("ep_" + uuid.uuid4().hex[:12])
        fields = {
            "title": title,
            "summary": summary,
            "importance": importance,
            "start_at": start_ts,
            "end_at": end_ts,
            "legacy_id": legacy,
        }
        with self.store.transaction() as conn:
            store = EpisodeStore(conn)
            existing = conn.execute(
                "SELECT id, session_id, kind, window_seq FROM episodes WHERE legacy_id=?",
                (legacy,),
            ).fetchone()
            if existing is not None:
                return store.upsert_episode(
                    scope=self.scope, kind=existing["kind"],
                    session_id=existing["session_id"],
                    window_seq=existing["window_seq"], **fields,
                )
            if source_session:
                return store.add_episode(scope=self.scope, kind="session",
                                         session_id=source_session, **fields)
            return store.add_episode(scope=self.scope, kind="manual", **fields)

    def consolidate(
        self,
        max_age_days: int = 90,
        min_access_count: int = 0,
        dry_run: bool = True,
        confirm: bool = False,
        evergreen_domains: Optional[Sequence[str]] = None,
    ) -> dict:
        """Archive old, low-value facts (I3; safe selection per EM-108/L2).

        A fact is a candidate only when ALL hold: importance < 0.6, domain not
        in ``evergreen_domains``, source not in ``('built_in_memory',
        'promoted')``, no ``pinned`` tag, age from
        ``max(updated_at, last_accessed)`` >= ``max_age_days``, and
        ``access_count <= min_access_count``. Candidates sort lowest
        importance first, oldest first within a tier.

        Archiving is the ``active -> archived`` edge, not v2's copy into a side
        ``facts_archive`` table: the row keeps its sensitivity and its history
        and leaves the live count. ``dry_run`` or a missing ``confirm`` reports
        what would go and changes nothing.
        """
        evergreen = set(evergreen_domains) if evergreen_domains is not None else {"People"}
        now = utc_now()
        candidates: List[Dict[str, Any]] = []
        with self.store.transaction() as conn:
            rows = MemoryStore(conn).list(scope=self.scope, status=("active",),
                                          limit=_SCAN_LIMIT, order="created_at ASC")
            for row in rows:
                found = self._consolidation_candidate(
                    row, now=now, evergreen=evergreen, max_age_days=max_age_days,
                    min_access_count=min_access_count,
                )
                if found is not None:
                    candidates.append(found)

        candidates.sort(key=lambda c: (c["importance"], c["newest"]))
        candidate_ids = [c["id"] for c in candidates]
        if dry_run or not confirm:
            return {
                "archived": 0,
                "would_archive": len(candidate_ids),
                "candidates": [
                    {
                        "id": c["id"],
                        "title": c["title"],
                        "age": round(c["age_days"], 1),
                        "importance": c["importance"],
                    }
                    for c in candidates
                ],
                "cutoff_days": max_age_days,
                "dry_run": True,
                "confirm_required": not confirm,
            }

        # Outside the write transaction (§3.3), and throttled: archiving a
        # whole profile is one event, not one per row.
        BackupManager(self.db_path).snapshot_if_due(reason="pre-consolidate")

        archived = 0
        with self.store.transaction() as conn:
            store = MemoryStore(conn)
            for memory_id in candidate_ids:
                moved = store.set_status(memory_id, "archived", actor="facade",
                                         reason="consolidate")
                if moved.ok:
                    archived += 1
        return {"archived": archived, "cutoff_days": max_age_days, "dry_run": False}

    @staticmethod
    def _consolidation_candidate(
        row: Dict[str, Any], *, now: datetime, evergreen: set,
        max_age_days: int, min_access_count: int,
    ) -> Optional[Dict[str, Any]]:
        """One row's candidacy, or ``None``. v2's rule, unchanged."""
        if (row.get("importance") or 0.0) >= 0.6:
            return None
        if (row.get("domain") or "Knowledge") in evergreen:
            return None
        if (row.get("source") or "agent") in ("built_in_memory", "promoted"):
            return None
        tags = row.get("tags")
        try:
            tag_list = json.loads(tags) if isinstance(tags, str) else list(tags or [])
        except (TypeError, ValueError):
            tag_list = []
        if "pinned" in tag_list:
            return None
        if (row.get("access_count") or 0) > min_access_count:
            return None

        parse = _parse_ts
        stamps = [
            s for s in (parse(row.get("updated_at") or ""),
                        parse(row.get("last_accessed_at") or ""))
            if s
        ]
        newest = max(stamps) if stamps else parse(row.get("created_at") or "")
        if newest is None:
            return None
        age_days = (now - newest).total_seconds() / 86400.0
        if age_days < max_age_days:
            return None
        return {
            "id": row["id"],
            "title": row.get("summary") or "",
            "importance": row.get("importance") or 0.0,
            "newest": newest,
            "age_days": age_days,
        }

