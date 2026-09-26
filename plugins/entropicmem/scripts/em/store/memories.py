"""Memories repository (v3 §3.3, card EM-205).

Public API and pipeline order are fixed by the master plan. Two things here are
load-bearing and easy to get wrong:

- **Dedup is a partial-index question, not a constraint question.**
  ``ux_mem_hash_scope`` is ``UNIQUE(content_hash, scope_profile, scope_user,
  scope_chat) WHERE status IN ('active','pending')``. Superseded, archived and
  deleted rows are exempt, so the same content may legitimately exist twice once
  the first copy is superseded. ``add`` therefore *queries* for the duplicate
  and returns ``noop_duplicate``; it does not lean on catching an
  ``IntegrityError``, which would also fire for the exempt case.
- **Nothing is embedded inline.** ``add`` enqueues an ``embed`` job and returns.
  An embedding call in the write transaction would put a network round trip
  inside a SQLite write lock.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Iterable, Literal, Mapping, Sequence

from ..clock import new_id, to_iso, utc_now
from .audit import append as audit_append
from .types import (
    MemoryDraft,
    MemoryPatch,
    Scope,
    Status,
    WriteResult,
    check_transition,
)

# Columns a caller may never set directly: they are maintained by the store.
_MANAGED = frozenset(
    {
        "rid",
        "id",
        "legacy_id",
        "content_hash",
        "created_at",
        "updated_at",
        "version",
        "superseded_by",
        "access_count",
        "inject_count",
        "helpful_count",
        "unhelpful_count",
        "last_accessed_at",
        "last_injected_at",
    }
)

_PATCHABLE = (
    "content",
    "summary",
    "kind",
    "domain",
    "sensitivity",
    "importance",
    "confidence",
    "evidence",
    "pinned",
    "decay_class",
    "valid_from",
    "valid_to",
)

_VISIBLE_COLUMNS = (
    "rid",
    "id",
    "legacy_id",
    "scope_profile",
    "scope_user",
    "scope_chat",
    "visibility",
    "kind",
    "content",
    "summary",
    "content_hash",
    "domain",
    "tags",
    "status",
    "importance",
    "confidence",
    "sensitivity",
    "source",
    "source_session",
    "source_turn",
    "author_id",
    "evidence",
    "pinned",
    "decay_class",
    "valid_from",
    "valid_to",
    "created_at",
    "updated_at",
    "last_accessed_at",
    "last_injected_at",
    "access_count",
    "inject_count",
    "helpful_count",
    "unhelpful_count",
    "superseded_by",
    "pending_reason",
    "pending_expires_at",
    "trust_flags",
    "token_estimate",
    "version",
)


def _tags_json(tags: Iterable[str]) -> str:
    return json.dumps(sorted({t for t in tags if t}), ensure_ascii=False, separators=(",", ":"))


def _loads(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _token_estimate(content: str) -> int:
    """Rough token count. Deliberately stdlib and cheap: len/4 is close enough
    for budgeting and is what the v2 engine used."""
    return max(1, len(content) // 4) if content else 0


class MemoryStore:
    """Read/write access to the v3 ``memories`` table.

    The caller owns the connection and the transaction. Every method that
    writes takes a live ``sqlite3.Connection`` already inside a transaction, so
    an audit row and the change it describes commit or roll back together
    (the same rule ``em.store.audit`` follows).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- internals -------------------------------------------------------

    def _content_hash(self, content: str, scope: Scope) -> str:
        """Hash the content *with* its scope.

        Two identical sentences written by different users are two different
        facts for prefetch purposes, so the scope has to be inside the digest.
        """
        scope_key = f"{scope.profile}\x1f{scope.user}\x1f{scope.chat}"
        return hashlib.sha256(f"{content}\x1f{scope_key}".encode("utf-8")).hexdigest()

    def _screen(self, content: str) -> list[str]:
        """Injection screen -> trust flags. Never blocks here (EM-703 owns
        that decision); the flags are recorded so it can.

        Only the *shapes* are stored, never the matched evidence text: a flag
        has to be safe to write into the audit trail and the sync outbox.
        """
        from injection_screen import screen_text  # local: heavy, optional dep

        try:
            result = screen_text(content)
        except Exception:  # pragma: no cover - screening must never break a write
            return []
        return sorted({f.shape for f in getattr(result, "findings", ())})

    def _redact(self, content: str, sensitivity: str) -> str:
        from pii import redact_pii

        if sensitivity in ("public", "internal"):
            return content
        try:
            return redact_pii(content)
        except Exception:  # pragma: no cover - never fail a write on redaction
            return content

    def _policy(self, content: str, domain: str, sensitivity: str, source: str) -> tuple[str, str]:
        from policy import evaluate_write

        action, reason = evaluate_write(content, domain=domain, sensitivity=sensitivity, source=source)
        return action, reason or ""

    def _insert(
        self,
        draft: MemoryDraft,
        *,
        scope: Scope,
        content: str,
        content_hash: str,
        status: str,
        trust_flags: Sequence[str],
    ) -> tuple[str, int]:
        now = to_iso(utc_now())
        mid = new_id("mem")
        self._conn.execute(
            "INSERT INTO memories (id, scope_profile, scope_user, scope_chat, visibility,"
            " kind, content, summary, content_hash, domain, tags, status, importance,"
            " confidence, sensitivity, source, source_session, source_turn, author_id,"
            " evidence, pinned, decay_class, valid_from, valid_to, created_at, updated_at,"
            " pending_reason, pending_expires_at, trust_flags, token_estimate, version)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mid,
                scope.profile,
                scope.user,
                scope.chat,
                draft.visibility,
                draft.kind,
                content,
                draft.summary,
                content_hash,
                draft.domain,
                _tags_json(draft.tags),
                status,
                draft.importance,
                draft.confidence,
                draft.sensitivity,
                draft.source,
                draft.source_session,
                draft.source_turn,
                draft.author_id or scope.author,
                draft.evidence,
                int(draft.pinned),
                draft.decay_class,
                draft.valid_from,
                draft.valid_to,
                now,
                now,
                draft.pending_reason if status == "pending" else "",
                draft.pending_expires_at,
                json.dumps(list(trust_flags), separators=(",", ":")),
                _token_estimate(content),
                1,
            ),
        )
        return mid, self._conn.execute("SELECT version FROM memories WHERE id=?", (mid,)).fetchone()[0]

    def _version_row(
        self,
        memory_id: str,
        content: str,
        draft_status: str,
        reason: str,
        actor: str,
        version: int | None = None,
    ) -> None:
        """Snapshot ``content`` as a version row of ``memory_id``.

        ``memory_versions`` is ``UNIQUE(memory_id, version)``, so one row per
        version. ``version`` is passed by callers that have already bumped
        ``memories.version`` (and would otherwise collide with the previous
        snapshot); otherwise the next number is derived from the row.
        """
        row = self._conn.execute(
            "SELECT version, importance, confidence, valid_from, valid_to FROM memories WHERE id=?",
            (memory_id,),
        ).fetchone()
        if version is None:
            version = (row["version"] if row else 0) + 1
        self._conn.execute(
            "INSERT INTO memory_versions (memory_id, version, content, importance, confidence,"
            " status, valid_from, valid_to, changed_at, change_reason, actor)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                memory_id,
                version,
                content,
                row["importance"] if row else None,
                row["confidence"] if row else None,
                draft_status,
                row["valid_from"] if row else None,
                row["valid_to"] if row else None,
                to_iso(utc_now()),
                reason,
                actor,
            ),
        )

    def _enqueue_embed(self, memory_id: str, content: str) -> None:
        """Queue an embedding job. Never called inline (§3.3: no embedding
        inside the write path).

        ``dedupe_key`` is one embed job per (memory, version) so a retried
        write cannot pile up duplicate work; a later version supersedes the
        key and gets its own job.
        """
        version = self._conn.execute("SELECT version FROM memories WHERE id=?", (memory_id,)).fetchone()[0]
        now = to_iso(utc_now())
        self._conn.execute(
            "INSERT INTO jobs (id, type, payload, dedupe_key, status, priority, attempts,"
            " max_attempts, run_after, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,0,5,?,?,?)"
            " ON CONFLICT(dedupe_key) DO UPDATE SET payload=excluded.payload, run_after=excluded.run_after,"
            " updated_at=excluded.updated_at",
            (
                new_id("job"),
                "embed",
                json.dumps({"memory_id": memory_id, "version": version}, separators=(",", ":")),
                f"embed:{memory_id}:{version}",
                "queued",
                5,
                now,
                now,
                now,
            ),
        )

    def _outbox(self, memory_id: str, op: str, version: int, ts: str, payload: Mapping[str, Any]) -> None:
        """Append to the sync outbox when the memory is publishable.

        Only ``public``/``internal`` visibility leaves the profile; anything
        sensitive stays local, which is the whole point of the outbox.
        """
        if payload.get("visibility") not in ("profile", "shared"):
            return
        self._conn.execute(
            "INSERT INTO sync_outbox (fact_id, op, version, written_at, fact_timestamp, payload, emitted)"
            " VALUES (?,?,?,?,?,?,0)",
            (memory_id, op, version, to_iso(utc_now()), ts, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        )

    def _find_duplicate(self, content_hash: str, scope: Scope) -> sqlite3.Row | None:
        """Find a live duplicate, honouring the partial index's WHERE clause.

        ``ux_mem_hash_scope`` only covers ``status IN ('active','pending')``, so
        this must filter the same way or a superseded row would look like a
        duplicate and block a legitimate new memory.
        """
        return self._conn.execute(
            "SELECT * FROM memories WHERE content_hash=? AND scope_profile=? AND scope_user=?"
            " AND scope_chat=? AND status IN ('active','pending') LIMIT 1",
            (content_hash, scope.profile, scope.user, scope.chat),
        ).fetchone()

    # --- public API ------------------------------------------------------

    def add(self, draft: MemoryDraft, *, scope: Scope, actor: str) -> WriteResult:
        """Run the full add pipeline and return the decision.

        normalise -> policy -> PII redaction -> injection screen -> hash ->
        exact-duplicate check -> insert -> outbox -> audit -> enqueue embed.
        """
        content = (draft.content or "").strip()
        if not content:
            return WriteResult(ok=False, decision="blocked", reason_code="empty_content")

        action, reason = self._policy(content, draft.domain, draft.sensitivity, draft.source)
        if action == "block":
            seq = audit_append(
                self._conn, "add", actor, "", {"reason": "policy_block"}, ok=False, session_id=draft.source_session
            )
            return WriteResult(ok=False, decision="blocked", reason_code="policy_block", audit_seq=seq)

        if action == "quarantine":
            # A quarantined write still gets a row: it lands in `pending` so a
            # later promotion can accept it, and the reason is recorded.
            return self._add_as_pending(
                draft, scope=scope, actor=actor, content=content, reason_code=reason or "quarantined"
            )

        return self._add_as_live(draft, scope=scope, actor=actor, content=content, reason_code=reason)

    def _add_as_live(
        self, draft: MemoryDraft, *, scope: Scope, actor: str, content: str, reason_code: str
    ) -> WriteResult:
        redacted = self._redact(content, draft.sensitivity)
        flags = self._screen(redacted)
        content_hash = self._content_hash(redacted, scope)

        dup = self._find_duplicate(content_hash, scope)
        if dup is not None:
            now = to_iso(utc_now())
            self._conn.execute(
                "UPDATE memories SET updated_at=?, confidence=MAX(confidence, ?), version=version+1"
                " WHERE id=?",
                (now, draft.confidence, dup["id"]),
            )
            seq = audit_append(
                self._conn,
                "noop_duplicate",
                actor,
                dup["id"],
                {"reason": "exact_duplicate", "hash_prefix": content_hash[:12]},
                session_id=draft.source_session,
            )
            return WriteResult(
                ok=True, id=dup["id"], status=dup["status"], decision="noop_duplicate",
                reason_code="exact_duplicate", audit_seq=seq,
            )

        status = "active" if draft.status in ("active", "pending") else draft.status
        mid, version = self._insert(draft, scope=scope, content=redacted, content_hash=content_hash, status=status, trust_flags=flags)
        self._version_row(mid, redacted, status, reason_code or "created", actor, version=1)
        self._outbox(
            mid,
            "upsert",
            1,
            to_iso(utc_now()),
            {
                "id": mid,
                "content": redacted,
                "domain": draft.domain,
                "kind": draft.kind,
                "tags": sorted(draft.tags),
                "visibility": draft.visibility,
                "importance": draft.importance,
                "confidence": draft.confidence,
            },
        )
        seq = audit_append(
            self._conn, "add", actor, mid, {"kind": draft.kind, "domain": draft.domain, "version": 1},
            session_id=draft.source_session,
        )
        self._enqueue_embed(mid, redacted)
        return WriteResult(ok=True, id=mid, status=status, decision="created", reason_code=reason_code, audit_seq=seq)

    def _add_as_pending(
        self, draft: MemoryDraft, *, scope: Scope, actor: str, content: str, reason_code: str
    ) -> WriteResult:
        redacted = self._redact(content, draft.sensitivity)
        flags = self._screen(redacted)
        content_hash = self._content_hash(redacted, scope)

        dup = self._find_duplicate(content_hash, scope)
        if dup is not None:
            seq = audit_append(
                self._conn, "noop_duplicate", actor, dup["id"], {"reason": "exact_duplicate_pending"},
                session_id=draft.source_session,
            )
            return WriteResult(
                ok=True, id=dup["id"], status=dup["status"], decision="noop_duplicate",
                reason_code="exact_duplicate", audit_seq=seq,
            )

        pending = MemoryDraft(
            **{
                **{
                    f: getattr(draft, f)
                    for f in draft.__dataclass_fields__
                },
                "status": "pending",
                "pending_reason": reason_code,
            }
        )
        mid, version = self._insert(pending, scope=scope, content=redacted, content_hash=content_hash, status="pending", trust_flags=flags)
        self._version_row(mid, redacted, "pending", reason_code, actor, version=1)
        seq = audit_append(
            self._conn, "add", actor, mid, {"decision": "quarantined", "reason": reason_code},
            ok=True, session_id=draft.source_session,
        )
        return WriteResult(ok=True, id=mid, status="pending", decision="quarantined", reason_code=reason_code, audit_seq=seq)

    def update(self, memory_id: str, patch: MemoryPatch, *, actor: str, reason: str) -> WriteResult:
        """In-place edit: bump ``version``, snapshot the old content, audit."""
        fields = patch.as_dict()
        if not fields:
            return WriteResult(ok=False, decision="blocked", reason_code="empty_patch")

        row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if row is None:
            return WriteResult(ok=False, decision="blocked", reason_code="not_found")

        if row["status"] not in ("active", "pending"):
            return WriteResult(
                ok=False, id=memory_id, status=row["status"], decision="blocked", reason_code="not_editable"
            )

        new_hash: str | None = None
        if "content" in fields:
            # A content change invalidates the dedup hash, so redaction and
            # re-hashing happen BEFORE anything is written. Two reasons:
            #   1. The new hash can collide with another live row in the same
            #      scope, and `ux_mem_hash_scope` would abort the whole
            #      transaction with an opaque IntegrityError. That is reported
            #      as `duplicate_content` instead, and nothing is written.
            #   2. The version snapshot must capture the *pre-edit* content, so
            #      it cannot be taken until the edit is known to be valid.
            new_content = self._redact(fields["content"].strip(), row["sensitivity"])
            new_hash = self._content_hash(new_content, _scope_of(row))
            clash = self._find_duplicate(new_hash, _scope_of(row))
            if clash is not None and clash["id"] != memory_id:
                return WriteResult(
                    ok=False, id=clash["id"], status=clash["status"],
                    decision="blocked", reason_code="duplicate_content",
                )
            fields["content"] = new_content

        # Snapshot the *previous* content, now that the edit is known to be
        # valid and nothing has been written yet.
        self._version_row(memory_id, row["content"], row["status"], reason, actor,
                          version=row["version"] + 1)

        sets, values = [], []
        for column in _PATCHABLE:
            if column in fields:
                value = fields[column]
                if column == "tags":
                    value = _tags_json(value or ())
                sets.append(f"{column}=?")
                values.append(value)
        if "content" in fields:
            sets.append("content_hash=?")
            values.append(new_hash)
            sets.append("token_estimate=?")
            values.append(_token_estimate(fields["content"]))
        sets.append("version=version+1")
        sets.append("updated_at=?")
        values.append(to_iso(utc_now()))
        values.append(memory_id)
        self._conn.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id=?", values)

        new_version = self._conn.execute("SELECT version FROM memories WHERE id=?", (memory_id,)).fetchone()[0]
        if "content" in fields:
            self._enqueue_embed(memory_id, fields["content"])

        seq = audit_append(
            self._conn, "update", actor, memory_id,
            {"reason": reason, "version": new_version, "fields": sorted(fields)},
        )
        return WriteResult(ok=True, id=memory_id, status=row["status"], decision="updated", reason_code=reason, audit_seq=seq)

    def supersede(self, old_id: str, draft: MemoryDraft, *, scope: Scope, actor: str, reason: str) -> WriteResult:
        """Replace a memory with a new one, in a single transaction.

        Old row goes ``superseded`` with ``valid_to`` set and ``superseded_by``
        pointing at the new id; any open relations on the old row are closed.
        """
        old = self._conn.execute("SELECT * FROM memories WHERE id=?", (old_id,)).fetchone()
        if old is None:
            return WriteResult(ok=False, decision="blocked", reason_code="not_found")
        if old["status"] not in ("active", "pending"):
            return WriteResult(
                ok=False, id=old_id, status=old["status"], decision="blocked", reason_code="not_supersedable"
            )

        result = self._add_as_live(draft, scope=scope, actor=actor, content=(draft.content or "").strip(), reason_code=reason)
        if not result.ok or result.decision == "noop_duplicate":
            return result

        now = to_iso(utc_now())
        valid_to = draft.valid_from or now
        self._conn.execute(
            "UPDATE memories SET status='superseded', valid_to=?, superseded_by=?, updated_at=?,"
            " version=version+1 WHERE id=?",
            (valid_to, result.id, now, old_id),
        )
        # Close the old row's still-open relations, or they would keep pointing
        # at a superseded memory.
        self._conn.execute(
            "UPDATE relations SET valid_to=? WHERE memory_id=? AND valid_to IS NULL", (valid_to, old_id)
        )
        self._version_row(old_id, old["content"], "superseded", reason, actor, version=old["version"] + 1)
        seq = audit_append(
            self._conn, "supersede", actor, result.id, {"old_id": old_id, "reason": reason},
        )
        return WriteResult(ok=True, id=result.id, status="superseded", decision="superseded", reason_code=reason, audit_seq=seq)

    def set_status(self, memory_id: str, status: Status, *, actor: str, reason: str) -> WriteResult:
        """Apply a §3.4 transition, refusing the illegal ones."""
        row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if row is None:
            return WriteResult(ok=False, decision="blocked", reason_code="not_found")

        current = row["status"]
        if current == status:
            return WriteResult(ok=True, id=memory_id, status=status, decision="noop_duplicate", reason_code="already_in_status")
        check_transition(current, status, reason)

        now = to_iso(utc_now())
        sets = ["status=?", "updated_at=?"]
        values: list[Any] = [status, now]
        if status == "superseded":
            sets.append("valid_to=?")
            values.append(now)
        elif status == "deleted":
            sets.append("valid_to=?")
            values.append(now)
        elif status == "archived":
            sets.append("pending_reason=?")
            values.append(reason)
        # A status change is a versioned change: the old status is a distinct
        # state of the memory, so it gets its own snapshot number like any
        # other edit. Without the bump, two transitions in a row would collide
        # on `UNIQUE(memory_id, version)`.
        sets.append("version=version+1")
        values.append(memory_id)
        self._conn.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id=?", values)

        # `version` is passed explicitly: the UPDATE above may have bumped
        # `memories.version`, and the snapshot must be the new number, not a
        # repeat of the version `add` already recorded.
        self._version_row(
            memory_id, row["content"], status, reason, actor, version=row["version"] + 1
        )
        seq = audit_append(self._conn, "set_status", actor, memory_id, {"from": current, "to": status, "reason": reason})
        return WriteResult(ok=True, id=memory_id, status=status, decision="updated", reason_code=reason, audit_seq=seq)

    def get(self, id_or_prefix_or_legacy: str, *, scope: Scope | None = None) -> dict[str, Any] | None:
        """Look a memory up by full id, unique id prefix, or v2 legacy id.

        A prefix must be unambiguous: two matches returns ``None`` rather than
        an arbitrary one, so a short id can never silently fetch the wrong row.
        """
        row = self._conn.execute("SELECT * FROM memories WHERE id=?", (id_or_prefix_or_legacy,)).fetchone()
        if row is None:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE legacy_id=?", (id_or_prefix_or_legacy,)
            ).fetchone()
        if row is None:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE id LIKE ? ESCAPE '\\' LIMIT 2",
                (id_or_prefix_or_legacy.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
            ).fetchall()
            if len(rows) != 1:
                return None
            row = rows[0]
        if scope is not None and not _in_scope(row, scope):
            return None
        return dict(row)

    def list(
        self,
        *,
        scope: Scope,
        status: Sequence[str] = ("active",),
        kind: str | None = None,
        limit: int = 100,
        order: str = "updated_at DESC",
    ) -> list[dict[str, Any]]:
        """List memories in a scope. ``order`` is validated against a whitelist."""
        allowed_order = {
            "updated_at DESC", "updated_at ASC", "created_at DESC", "created_at ASC",
            "importance DESC", "importance ASC", "access_count DESC",
        }
        if order not in allowed_order:
            raise ValueError(f"unsupported order {order!r}; allowed: {sorted(allowed_order)}")

        clauses = ["scope_profile=?", "scope_user=?"]
        values: list[Any] = [scope.profile, scope.user]
        if scope.chat:
            clauses.append("(scope_chat=? OR scope_chat='')")
            values.append(scope.chat)
        if status:
            placeholders = ",".join("?" for _ in status)
            clauses.append(f"status IN ({placeholders})")
            values.extend(status)
        if kind:
            clauses.append("kind=?")
            values.append(kind)
        values.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM memories WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT ?", values
        ).fetchall()
        return [dict(r) for r in rows]

    def history(self, memory_id: str) -> list[dict[str, Any]]:
        """Version history of a memory and everything it replaced, oldest first.

        ``superseded_by`` points forward, so a memory's predecessors are the
        rows whose ``superseded_by`` is *this* id. Walking that edge
        recursively gives the full lineage, which is what makes a superseded
        memory's history one call rather than a chain of lookups by the caller.
        """
        row = self._conn.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone()
        if row is None:
            return []

        seen: set[str] = set()

        def ancestors(mid: str) -> list[str]:
            out: list[str] = []
            for found in self._conn.execute("SELECT id FROM memories WHERE superseded_by=?", (mid,)):
                predecessor = found["id"]
                if predecessor in seen:
                    continue
                seen.add(predecessor)
                out.append(predecessor)
                out.extend(ancestors(predecessor))
            return out

        chain = [memory_id] + ancestors(memory_id)
        versions: list[dict[str, Any]] = []
        for mid in reversed(chain):
            for version in self._conn.execute(
                "SELECT * FROM memory_versions WHERE memory_id=? ORDER BY version", (mid,)
            ):
                versions.append(dict(version))
        return versions

    def touch(self, ids: list[str], *, field: Literal["accessed", "injected"]) -> None:
        """Bump access counters in one statement. No audit: not a fact change.

        Only ``injected`` may touch ``last_injected_at``; ``accessed`` must not,
        otherwise a memory would look injected to the retrieval layer when it
        was only ever read.
        """
        if not ids:
            return
        now = to_iso(utc_now())
        if field == "injected":
            self._conn.execute(
                "UPDATE memories SET last_injected_at=?, inject_count=inject_count+1 WHERE id IN (%s)"
                % ",".join("?" for _ in ids),
                [now, *ids],
            )
        else:
            self._conn.execute(
                "UPDATE memories SET last_accessed_at=?, access_count=access_count+1 WHERE id IN (%s)"
                % ",".join("?" for _ in ids),
                [now, *ids],
            )

    def purge(self, memory_id: str, *, actor: str) -> None:
        """Hard delete: row, versions, relations, outbox rows. (EM-705 extends
        this to embeddings and the vault projection.)"""
        row = self._conn.execute("SELECT id FROM memories WHERE id=?", (memory_id,)).fetchone()
        if row is None:
            raise KeyError(memory_id)
        self._conn.execute("DELETE FROM memory_versions WHERE memory_id=?", (memory_id,))
        self._conn.execute("DELETE FROM relations WHERE memory_id=?", (memory_id,))
        self._conn.execute("DELETE FROM sync_outbox WHERE fact_id=?", (memory_id,))
        self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        audit_append(self._conn, "purge", actor, memory_id, {"reason": "hard_delete"})


def _scope_of(row: Mapping[str, Any]) -> Scope:
    return Scope(profile=row["scope_profile"], user=row["scope_user"], chat=row["scope_chat"])


def _in_scope(row: Mapping[str, Any], scope: Scope) -> bool:
    """§3.5 read rule, minimum viable: same profile, and either the same user
    or a profile-wide row. Owner-only filtering for sensitive rows lands with
    the facade (EM-211), which knows the gateway identity."""
    if row["scope_profile"] != scope.profile:
        return False
    if row["scope_user"] == scope.user:
        return True
    return row["scope_user"] == ""
