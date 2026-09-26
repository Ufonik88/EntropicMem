"""Episodes and transcript chunks (v3 §3.2, card EM-207).

Two things are load-bearing here:

- **Chunks are content-addressed.** ``transcript_chunks`` is keyed by a digest
  of the normalised text, not by (session, seq). That is what makes a retried
  ``upsert_chunks`` idempotent: the same message at the same position produces
  the same digest and the INSERT OR IGNORE is a no-op. The AC ("retries produce
  zero new rows") holds because the primary key is the content, not a counter.
- **Retention never deletes a chunk an episode still needs.** ``prune_chunks``
  keeps any chunk belonging to a session whose episode is still pending, so
  summarising an in-flight session cannot be starved of its own transcript.

Config note: ``older_than_days`` defaults to the plan's
``privacy.transcript_retention_days`` of 30. The typed config module is EM-407,
so the value is a parameter with that default rather than a config lookup here.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

from ..clock import new_id, to_iso, utc_now
from .types import Scope

DEFAULT_RETENTION_DAYS = 30

EPISODE_KINDS = ("session", "window", "precompress", "delegation", "manual")


def chunk_digest(session_id: str, seq: int, role: str, text: str) -> str:
    """Content address for one chunk.

    ``session_id`` and ``seq`` are part of the digest so the same sentence
    appearing twice in one session stays two chunks, while a retry of the same
    message at the same position collapses to one row.
    """
    payload = f"{session_id}\x1f{seq}\x1f{role}\x1f{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalise_text(message: Any) -> str:
    """Flatten one message to plain text via ``textutil.message_text``."""
    from textutil import message_text

    return (message_text(message) or "").strip()


def _redact(text: str) -> str:
    from pii import redact_pii

    if not text:
        return ""
    try:
        return redact_pii(text)
    except Exception:  # pragma: no cover - never fail a capture on redaction
        return text


class EpisodeStore:
    """Writes to ``episodes`` and ``transcript_chunks``.

    The caller owns the connection and transaction, matching ``MemoryStore``.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- transcript chunks ------------------------------------------------

    def upsert_chunks(
        self,
        session_id: str,
        messages: Sequence[Any],
        source: str,
        *,
        start_seq: int = 0,
        sensitivity: str = "internal",
    ) -> int:
        """Store transcript chunks, returning the number of NEW rows.

        A retried call with the same messages inserts nothing and returns 0.
        Roles come from ``role``/``author_id``/``ts`` keys when the message is
        a mapping, and default sensibly otherwise.
        """
        now = to_iso(utc_now())
        new_rows = 0
        for offset, message in enumerate(messages):
            seq = start_seq + offset
            text = normalise_text(message)
            if not text:
                continue
            role, author_id, ts = _message_meta(message)
            if sensitivity not in ("public", "internal"):
                text = _redact(text)
            digest = chunk_digest(session_id, seq, role, text)
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO transcript_chunks (digest, session_id, seq, role,"
                " author_id, text, ts, captured_at, source) VALUES (?,?,?,?,?,?,?,?,?)",
                (digest, session_id, seq, role, author_id, text, ts, now, source),
            )
            new_rows += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        return new_rows

    def chunk_count(self, session_id: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM transcript_chunks WHERE session_id=?", (session_id,)
        ).fetchone()[0]

    # --- episodes ---------------------------------------------------------

    def add_episode(
        self,
        *,
        scope: Scope,
        kind: str,
        title: str,
        summary: str = "",
        session_id: str = "",
        importance: float = 0.5,
        summarizer: str = "extractive",
        decisions: Iterable[str] = (),
        open_loops: Iterable[str] = (),
        entities: Iterable[str] = (),
        start_at: str | None = None,
        end_at: str | None = None,
        legacy_id: str | None = None,
    ) -> str:
        """Insert an episode under ``UNIQUE(session_id, kind, window_seq)``.

        ``window_seq`` is the next number for that ``(session_id, kind)``, so a
        long session accumulates ordered windows without the caller tracking
        them. This is an INSERT, not an upsert on a caller-supplied key: the
        uniqueness constraint is what makes a duplicate attempt fail loudly
        rather than silently overwrite a window.

        A *manual* episode uses its own id as the session key so it can never
        collide with a real session's window numbering. Any other kind needs an
        explicit ``session_id``: guessing one from the scope would make every
        episode its own window 0 and destroy the ordering.

        Returns the new episode id.
        """
        if kind not in EPISODE_KINDS:
            raise ValueError(f"unknown episode kind {kind!r}; expected one of {EPISODE_KINDS}")

        now = to_iso(utc_now())
        episode_id = new_id("ep")
        if kind == "manual":
            session_id = episode_id
        elif not session_id:
            raise ValueError(
                f"session_id is required for kind={kind!r}; only 'manual' may omit it"
            )

        row = self._conn.execute(
            "SELECT window_seq FROM episodes WHERE session_id=? AND kind=?"
            " ORDER BY window_seq DESC LIMIT 1",
            (session_id, kind),
        ).fetchone()
        window_seq = (row["window_seq"] + 1) if row is not None else 0

        self._conn.execute(
            "INSERT INTO episodes (id, scope_profile, scope_user, scope_chat, kind, session_id,"
            " window_seq, title, summary, decisions, open_loops, entities, start_at, end_at,"
            " importance, summarizer, created_at, updated_at, legacy_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                episode_id,
                scope.profile,
                scope.user,
                scope.chat,
                kind,
                session_id,
                window_seq,
                title,
                summary,
                json.dumps(list(decisions), separators=(",", ":")),
                json.dumps(list(open_loops), separators=(",", ":")),
                json.dumps(list(entities), separators=(",", ":")),
                start_at,
                end_at,
                importance,
                summarizer,
                now,
                now,
                legacy_id,
            ),
        )
        return episode_id

    def upsert_episode(
        self,
        *,
        scope: Scope,
        kind: str,
        session_id: str,
        window_seq: int,
        title: str,
        summary: str = "",
        importance: float = 0.5,
        summarizer: str = "extractive",
        decisions: Iterable[str] = (),
        open_loops: Iterable[str] = (),
        entities: Iterable[str] = (),
        start_at: str | None = None,
        end_at: str | None = None,
        legacy_id: str | None = None,
    ) -> str:
        """Upsert one specific ``(session_id, kind, window_seq)``.

        Use this when the caller *does* know which window it is filling or
        refining, and wants a retry to converge instead of raising. Returns the
        existing id when the window is already present.
        """
        if kind not in EPISODE_KINDS:
            raise ValueError(f"unknown episode kind {kind!r}; expected one of {EPISODE_KINDS}")
        if kind == "manual":
            raise ValueError("manual episodes use add_episode, which assigns its own session_id")

        now = to_iso(utc_now())
        existing = self._conn.execute(
            "SELECT id FROM episodes WHERE session_id=? AND kind=? AND window_seq=?",
            (session_id, kind, window_seq),
        ).fetchone()
        if existing is not None:
            self._conn.execute(
                "UPDATE episodes SET title=?, summary=?, decisions=?, open_loops=?, entities=?,"
                " importance=?, summarizer=?, end_at=?, updated_at=? WHERE id=?",
                (
                    title,
                    summary,
                    json.dumps(list(decisions), separators=(",", ":")),
                    json.dumps(list(open_loops), separators=(",", ":")),
                    json.dumps(list(entities), separators=(",", ":")),
                    importance,
                    summarizer,
                    end_at,
                    now,
                    existing["id"],
                ),
            )
            return existing["id"]

        episode_id = new_id("ep")
        self._conn.execute(
            "INSERT INTO episodes (id, scope_profile, scope_user, scope_chat, kind, session_id,"
            " window_seq, title, summary, decisions, open_loops, entities, start_at, end_at,"
            " importance, summarizer, created_at, updated_at, legacy_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                episode_id,
                scope.profile,
                scope.user,
                scope.chat,
                kind,
                session_id,
                window_seq,
                title,
                summary,
                json.dumps(list(decisions), separators=(",", ":")),
                json.dumps(list(open_loops), separators=(",", ":")),
                json.dumps(list(entities), separators=(",", ":")),
                start_at,
                end_at,
                importance,
                summarizer,
                now,
                now,
                legacy_id,
            ),
        )
        return episode_id

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
        return dict(row) if row else None

    def list_episodes(
        self, *, scope: Scope, kind: str | None = None, session_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        clauses = ["scope_profile=?", "scope_user=?"]
        values: list[Any] = [scope.profile, scope.user]
        if kind:
            clauses.append("kind=?")
            values.append(kind)
        if session_id:
            clauses.append("session_id=?")
            values.append(session_id)
        values.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM episodes WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ?", values
        ).fetchall()
        return [dict(r) for r in rows]

    def search_episodes(
        self,
        q: str,
        scope: Scope,
        time_range: tuple[str, str] | None = None,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """FTS search over episode title and summary.

        Falls back to a LIKE scan when the query has no FTS-safe tokens (a bare
        stopword or punctuation would make MATCH raise), so a search never
        fails on the user's phrasing.
        """
        terms = [t for t in _fts_tokens(q) if t]
        if not terms:
            return self._like_search(q, scope, time_range, limit)

        match = " OR ".join(f'"{t}"' for t in terms)
        # Parameter order must mirror the SQL's placeholder order exactly:
        # MATCH first, then the scope/time clauses, then LIMIT.
        params: list[Any] = [match, scope.profile, scope.user]
        clauses = ["e.scope_profile=?", "e.scope_user=?"]
        if time_range:
            clauses.append("e.created_at >= ? AND e.created_at <= ?")
            params.extend(time_range)
        params.append(limit)
        rows = self._conn.execute(
            "SELECT e.* FROM episodes_fts f JOIN episodes e ON e.rid = f.rowid"
            f" WHERE episodes_fts MATCH ? AND {' AND '.join(clauses)}"
            " ORDER BY rank LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def _like_search(
        self, q: str, scope: Scope, time_range: tuple[str, str] | None, limit: int
    ) -> list[dict[str, Any]]:
        clauses = ["scope_profile=?", "scope_user=?", "(title LIKE ? OR summary LIKE ?)"]
        like = f"%{q}%"
        values: list[Any] = [scope.profile, scope.user, like, like]
        if time_range:
            clauses.append("created_at >= ? AND created_at <= ?")
            values.extend(time_range)
        values.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM episodes WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ?", values
        ).fetchall()
        return [dict(r) for r in rows]

    # --- retention --------------------------------------------------------

    def prune_chunks(
        self,
        older_than_days: int = DEFAULT_RETENTION_DAYS,
        *,
        keep_if_episode_pending: bool = True,
        now: str | None = None,
    ) -> int:
        """Delete transcript chunks older than the retention window.

        Returns the number of rows removed.

        With ``keep_if_episode_pending``, chunks belonging to a session that has
        at least one episode with no summary yet are kept, so summarising an
        in-flight session is never starved of the transcript it needs. The test
        is "some episode for this session still has an empty summary", not "the
        session's newest episode does": a long session can have a summarised
        first window and an unsummarised third one, and that third window still
        needs its chunks.
        """
        cutoff = _days_ago(older_than_days, now)
        if keep_if_episode_pending:
            pending = [
                r["session_id"]
                for r in self._conn.execute(
                    "SELECT DISTINCT session_id FROM episodes WHERE TRIM(summary) = ''"
                )
            ]
            if pending:
                placeholders = ",".join("?" for _ in pending)
                cur = self._conn.execute(
                    f"DELETE FROM transcript_chunks WHERE captured_at < ?"
                    f" AND session_id NOT IN ({placeholders})",
                    [cutoff, *pending],
                )
                return max(0, cur.rowcount or 0)
        cur = self._conn.execute("DELETE FROM transcript_chunks WHERE captured_at < ?", (cutoff,))
        return max(0, cur.rowcount or 0)

    def prune_episodes(
        self, older_than_days: int, *, now: str | None = None
    ) -> int:
        """Delete episodes older than the window, cascades handled by caller."""
        cutoff = _days_ago(older_than_days, now)
        cur = self._conn.execute("DELETE FROM episodes WHERE created_at < ?", (cutoff,))
        return max(0, cur.rowcount or 0)


def _days_ago(days: int, now: str | None = None) -> str:
    from datetime import timedelta

    base = utc_now()
    if now:
        from ..clock import parse_iso

        base = parse_iso(now)
    return to_iso(base - timedelta(days=days))


def _message_meta(message: Any) -> tuple[str, str, str | None]:
    """(role, author_id, ts) from a message mapping, with safe defaults."""
    if isinstance(message, Mapping):
        role = str(message.get("role") or "user")
        author = str(message.get("author_id") or message.get("author") or "")
        ts = message.get("ts") or message.get("timestamp")
        return role, author, str(ts) if ts else None
    return "user", "", None


def _fts_tokens(q: str) -> list[str]:
    """Quote-safe FTS tokens. Anything with a FTS operator character is dropped
    rather than escaped, so a search string can never become a query."""
    out = []
    for raw in q.split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if token and len(token) > 1:
            out.append(token)
    return out


if __name__ == "__main__":  # pragma: no cover
    import sys

    print(f"transcript_chunks retention: {DEFAULT_RETENTION_DAYS} days (config key privacy.transcript_retention_days)", file=sys.stderr)
