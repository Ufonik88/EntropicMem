"""Hash-chained audit log (v3 §3.3, card EM-206).

The chain is ``sha256(prev_hash || ts || action || actor || target_id || detail)``
where ``detail`` is the canonical JSON text stored in the column. That formula is
frozen: it is what migration ``0002_v3_core`` used to rebuild the chain from v2,
so a change here would make a migrated database fail its own parity check. It is
duplicated rather than imported for that same reason (see EM-204's note on
migration helpers).

``append()`` must be called inside the caller's transaction so an audit row and
the change it describes commit or roll back together.

``detail`` never carries full content: ids, digests and reason codes only. The
enforced rule is that no value longer than ``MAX_DETAIL_VALUE_LEN`` may appear,
which is what keeps a rewritten fact or a transcript chunk out of the log.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

__all__ = ["GENESIS_HASH", "VerifyResult", "append", "audit_hash", "verify"]

#: ``prev_hash`` of the first row. 64 zeros, not empty, so every row's payload
#: is the same shape and a truncated first row cannot look like a valid chain.
GENESIS_HASH = "0" * 64

#: Longest permitted value inside ``detail``. Anything longer is almost certainly
#: content (a fact body, a transcript chunk) rather than an id, hash or code.
MAX_DETAIL_VALUE_LEN = 128


def audit_hash(
    prev_hash: str, ts: str, action: str, actor: str, target_id: str, detail: str
) -> str:
    """Return the chained digest for one row (§3.3)."""
    payload = "".join((prev_hash, ts, action, actor, target_id, detail))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_detail(detail: Mapping[str, Any] | None) -> str:
    """Serialise ``detail`` the way it is stored, so hashing matches the row.

    ``sort_keys`` matters: the digest covers the exact text, so a caller that
    builds ``{"b":1,"a":2}`` and a caller that builds ``{"a":2,"b":1}`` must not
    produce two different hashes for the same event.
    """
    if not detail:
        return "{}"
    return json.dumps(detail, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _check_detail(detail: Mapping[str, Any] | None) -> None:
    """Reject content in ``detail``: ids, hashes and reason codes only."""
    for key, value in (detail or {}).items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if len(text) > MAX_DETAIL_VALUE_LEN:
            raise ValueError(
                f"audit detail {key!r} is {len(text)} chars (max {MAX_DETAIL_VALUE_LEN}); "
                "log ids, hashes or reason codes, never content"
            )


def append(
    conn: sqlite3.Connection,
    action: str,
    actor: str,
    target_id: str = "",
    detail: Mapping[str, Any] | None = None,
    ok: bool = True,
    session_id: str = "",
    ts: str | None = None,
) -> int:
    """Append one chained row and return its ``seq``. Caller owns the txn.

    The chain head is read inside the same transaction as the insert, so two
    concurrent appenders serialise on SQLite's write lock rather than both
    reading the same ``prev_hash`` and forking the chain.
    """
    _check_detail(detail)
    detail_text = _canonical_detail(detail)

    if ts is None:
        row_ts = conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
    else:
        row_ts = ts

    head = conn.execute("SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
    prev_hash = head["hash"] if head is not None else GENESIS_HASH
    digest = audit_hash(prev_hash, row_ts, action, actor, target_id, detail_text)

    cur = conn.execute(
        "INSERT INTO audit_log (ts, action, actor, session_id, target_id,"
        " detail, ok, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?)",
        (row_ts, action, actor, session_id, target_id, detail_text, int(bool(ok)), prev_hash, digest),
    )
    # ponytail: lastrowid is Optional in the stubs; it cannot be None after INSERT.
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of :func:`verify`."""

    ok: bool
    first_bad_seq: int | None = None
    checked: int = 0
    reason: str = ""


def verify(conn: sqlite3.Connection) -> VerifyResult:
    """Walk the chain and report the first row that does not check out.

    Two failure modes are covered: a row whose stored ``hash`` does not match its
    own fields, and a row whose ``prev_hash`` does not match the row before it.
    A rewrite of any earlier row therefore breaks the chain from that point on,
    and the appended rows that inherited the bad digest are reported too.
    """
    prev_hash = GENESIS_HASH
    checked = 0
    for row in conn.execute(
        "SELECT seq, ts, action, actor, target_id, detail, hash, prev_hash"
        " FROM audit_log ORDER BY seq"
    ):
        checked += 1
        seq = int(row["seq"])
        if row["prev_hash"] != prev_hash:
            return VerifyResult(
                False, seq, checked, f"seq {seq}: prev_hash does not match seq {seq - 1 if seq else 0}"
            )
        expected = audit_hash(
            prev_hash, row["ts"], row["action"], row["actor"], row["target_id"], row["detail"]
        )
        if row["hash"] != expected:
            return VerifyResult(False, seq, checked, f"seq {seq}: hash does not match its fields")
        prev_hash = row["hash"]
    return VerifyResult(True, None, checked, "")
