"""Time and identifier primitives for the v3 storage core (EM-201).

Single source of time truth: every v3 timestamp is produced by
:func:`to_iso` from a :func:`utc_now` reading, and every v3 identifier by
:func:`new_id`. Keeping both here means tests and evals can freeze time in
one place and IDs stay sortable by creation.

Formats:

* ``to_iso`` emits UTC ISO-8601 with millisecond precision and a ``Z``
  suffix (``2026-09-23T14:05:09.123Z``), per plan §3.3.
* ``parse_iso`` additionally accepts the legacy shapes the v2 engine wrote:
  SQLite ``CURRENT_TIMESTAMP`` (``YYYY-MM-DD HH:MM:SS``, naive, treated as
  UTC), ``…+00:00`` offsets, and any ISO offset (converted to UTC).

IDs are ULIDs (48-bit millisecond timestamp + 80 random bits, Crockford
base32) with a type prefix (``mem_``, ``ep_``, ``ent_``, ``job_``); stdlib
only, sortable by creation time within the lexicographic order.

Stdlib only; no Hermes imports; no environment reads (plan §0.1, §3.2).
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

__all__ = [
    "freeze",
    "new_id",
    "parse_iso",
    "short_id",
    "to_iso",
    "utc_now",
]

# Crockford base32: excludes I, L, O, U to avoid transcription ambiguity.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIME_CHARS = 10  # 48-bit ms in 10 base32 chars (50 bits of headroom)
_RANDOM_BYTES = 10  # 80 random bits -> 16 base32 chars
_MAX_MS = 1 << 48

# Module-level frozen clock. Production never freezes; tests/evals do, from
# one thread. No locking on purpose: a lock here would only paper over a
# multi-threaded freeze, which is a test bug, not a runtime mode.
_frozen_now: Optional[datetime] = None

_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*_?$")


@contextmanager
def freeze(dt: datetime) -> Iterator[datetime]:
    """Context manager pinning :func:`utc_now` (and :func:`new_id` timestamps)
    to ``dt``. Naive input is interpreted as UTC. Restores any outer freeze
    on exit, so freezes nest.
    """
    global _frozen_now
    previous = _frozen_now
    _frozen_now = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    try:
        yield _frozen_now
    finally:
        _frozen_now = previous


def utc_now() -> datetime:
    """Current time as an aware UTC datetime (or the frozen test time)."""
    if _frozen_now is not None:
        return _frozen_now
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    """UTC ISO-8601 with millisecond precision and a ``Z`` suffix.

    Naive input is interpreted as UTC. Microseconds are truncated (never
    rounded up) so ``parse_iso(to_iso(x))`` round-trips at ms precision.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=(dt.microsecond // 1000) * 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse a timestamp into an aware UTC datetime.

    Accepts:
    * v3 canonical: ``2026-09-23T14:05:09.123Z``
    * SQLite ``CURRENT_TIMESTAMP``: ``2026-09-23 14:05:09`` (naive → UTC)
    * ISO with any offset: ``2026-09-23T14:05:09+02:00`` (converted to UTC)
    * fractional seconds at any precision

    Raises ``ValueError`` on anything else. Python 3.10's
    ``datetime.fromisoformat`` rejects ``Z`` and space separators unevenly,
    so both are normalised before parsing (the 3.11+ parser would accept
    them, but the CI floor is 3.10).
    """
    text = (s or "").strip()
    if not text:
        raise ValueError("empty timestamp")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    # SQLite CURRENT_TIMESTAMP uses a space separator; fromisoformat on 3.10
    # accepts it only in some builds, so normalise to 'T'.
    if len(text) > 10 and text[10] == " ":
        text = text[:10] + "T" + text[11:]
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _encode_base32(value: int, chars: int) -> str:
    out = []
    for _ in range(chars):
        out.append(_ALPHABET[value & 0x1F])
        value >>= 5
    if value:
        raise ValueError(f"value too large for {chars} base32 chars")
    out.reverse()
    return "".join(out)


def new_id(prefix: str, *, now: Optional[datetime] = None) -> str:
    """Type-prefixed ULID: ``<prefix>_<26-char ULID>`` (e.g. ``mem_01J…``).

    48-bit millisecond timestamp (big-endian base32, so lexicographic order
    matches creation order) + 80 random bits from :func:`os.urandom`. The
    timestamp comes from ``now`` or :func:`utc_now` — so a frozen clock also
    freezes ID time, which is what eval fixtures rely on.

    ``prefix`` must be a short ASCII identifier (letters/digits, optional
    trailing underscore); the underscore separator is normalised to exactly
    one. Raises ``ValueError`` for an empty prefix, a bad prefix shape, or a
    time outside the 48-bit ms range (before 1970 or after year 10889).
    """
    if not prefix or not _PREFIX_RE.match(prefix):
        raise ValueError(f"invalid id prefix: {prefix!r}")
    prefix = prefix.rstrip("_") + "_"
    dt = now if now is not None else utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ms = int(dt.timestamp() * 1000)
    if ms < 0 or ms >= _MAX_MS:
        raise ValueError(f"timestamp out of ULID range: {dt!r}")
    return prefix + _encode_base32(ms, _TIME_CHARS) + _encode_base32(
        int.from_bytes(os.urandom(_RANDOM_BYTES), "big"), 16
    )


def short_id(id_or_ulid: str) -> str:
    """Last 8 characters of an ID (the ULID part for prefixed IDs).

    Tools accept unique prefixes of ≥ 6 chars; the short form is what the
    rendered prefetch block cites (``[m·7Q4F2K9A]``).
    """
    return (id_or_ulid or "")[-8:]
