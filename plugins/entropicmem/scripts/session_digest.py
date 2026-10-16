"""Extractive session digest - deterministic, no LLM.

Feeds the EntropicMem plugin's lifecycle hooks (P1 Slice 2):

- ``extractive_digest``   - A1/A5 session digest episodes, idempotent by
  construction via a deterministic ``ep_sess_{session_id}`` episode id.
- ``extract_constraints`` - A2: standing constraints fed to the compression
  summary prompt, persisted as a ``pre_compress`` episode.

Pure stdlib: no network, no LLM, no host state.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from textutil import message_text as _message_text  # shared EM-101 normaliser

_TITLE_MAX = 80
_BULLET_MAX = 220
_MAX_SCAN_CHARS = 20000  # per-role cap for the C1 extraction input
_HEAD_TURNS = 2
_TAIL_TURNS = 12
_FACT_CANDIDATE_MAX = 10

# Durable-statement / constraint markers.
_MARKERS = re.compile(
    r"\b(always|never|remember|do not|don't|must|avoid|prefer\w*)\b",
    re.IGNORECASE,
)

# EM-406 handoff markers (§4.6 step 3). The constraints set is the A2 set plus
# the plan's three phrases; decisions and open loops get their own. A sentence
# is classified by its first match in the order constraints → decisions → open
# loops, so "agreed: we must ship X" lands as a constraint, deterministically.
_CONSTRAINT_MARKERS = re.compile(
    r"\b(always|never|remember|do not|don't|must|avoid|prefer\w*"
    r"|from now on|going forward|make sure)\b",
    re.IGNORECASE,
)
_DECISION_MARKERS = re.compile(r"\b(we decided|let's go with|agreed)\b", re.IGNORECASE)
_LOOP_MARKERS = re.compile(r"\b(TODO|next step|remind me|follow up)\b", re.IGNORECASE)

_WS = re.compile(r"\s+")



def _turns(messages: Optional[List[Dict[str, Any]]]) -> List[Tuple[str, str]]:
    """Extract (role, text) turns; tool/system noise is skipped."""
    turns: List[Tuple[str, str]] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _WS.sub(" ", _message_text(msg)).strip()
        if text:
            turns.append((role, text))
    return turns


def _sanitize_session_id(session_id: str) -> str:
    """Slug-safe session id for episode ids."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", (session_id or "").strip())[:80]


def episode_id_for(session_id: str, wave: Optional[int] = None) -> str:
    """Deterministic episode id for a session digest (A1/A5).

    EM-112: cadence flushes pass a monotonically increasing wave number and
    get ``ep_sess_{sid}_w{n}`` (never overwriting earlier waves); the
    session-end digest stays the single ``ep_sess_{sid}`` covering the tail
    (idempotent re-fire replaces the same row).
    """
    base = "ep_sess_" + (_sanitize_session_id(session_id) or "unknown")
    return base if wave is None else f"{base}_w{int(wave)}"


def precompress_episode_id(session_id: str) -> str:
    """Deterministic episode id for a pre-compression constraint digest (A2)."""
    return "ep_precomp_" + (_sanitize_session_id(session_id) or "unknown")


def _timestamp_of(msg: Dict[str, Any]) -> Optional[str]:
    ts = msg.get("timestamp")
    if isinstance(ts, (int, float)):
        try:
            # EM-112: digest timestamps are UTC
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(ts, str) and ts.strip():
        return ts.strip()
    return None


def _joined_text(turns: List[Tuple[str, str]], role: str, max_chars: int = _MAX_SCAN_CHARS) -> str:
    """Joined text for one role, capped to the most recent ``max_chars``."""
    joined = "\n".join(text for r, text in turns if r == role)
    return joined[-max_chars:]


def extractive_digest(
    messages: Optional[List[Dict[str, Any]]],
    *,
    max_chars: int = 2000,
) -> Dict[str, Any]:
    """Extractive session digest. No LLM, no network.

    Returns ``{title, summary, fact_candidates, user_text, assistant_text,
    start_ts, end_ts, message_count}``. Empty / tool-only input yields an
    empty ``summary`` (callers no-op on that).

    Sampling: the first ``_HEAD_TURNS`` turns set context, the last
    ``_TAIL_TURNS`` carry current state; bullets are capped at ``max_chars``.
    """
    turns = _turns(messages)
    if not turns:
        return {
            "title": "",
            "summary": "",
            "fact_candidates": [],
            "user_text": "",
            "assistant_text": "",
            "start_ts": None,
            "end_ts": None,
            "message_count": 0,
        }

    first_user = next((text for role, text in turns if role == "user"), "")
    title = first_user[:_TITLE_MAX]

    def _bullet(role: str, text: str) -> str:
        prefix = "User" if role == "user" else "Assistant"
        return f"{prefix}: {text[:_BULLET_MAX]}"

    if len(turns) <= _HEAD_TURNS + _TAIL_TURNS:
        bullets = [_bullet(r, t) for r, t in turns]
    else:
        bullets = [_bullet(r, t) for r, t in turns[:_HEAD_TURNS]]
        bullets.append("…")
        bullets.extend(_bullet(r, t) for r, t in turns[-_TAIL_TURNS:])
    summary = "\n".join(bullets)
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1] + "…"

    fact_candidates: List[str] = []
    seen = set()
    for role, text in turns:
        if role != "user":
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            s = sentence.strip()
            if len(s) < 10 or len(s) > 240 or not _MARKERS.search(s):
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            fact_candidates.append(s)
            if len(fact_candidates) >= _FACT_CANDIDATE_MAX:
                break
        if len(fact_candidates) >= _FACT_CANDIDATE_MAX:
            break

    start_ts = next(
        (ts for ts in (_timestamp_of(m) for m in messages or [] if isinstance(m, dict)) if ts),
        None,
    )
    end_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "title": title,
        "summary": summary,
        "fact_candidates": fact_candidates,
        "user_text": _joined_text(turns, "user"),
        "assistant_text": _joined_text(turns, "assistant"),
        "start_ts": start_ts or end_ts,
        "end_ts": end_ts,
        "message_count": len(turns),
    }


def extract_constraints(
    messages: Optional[List[Dict[str, Any]]],
    *,
    max_chars: int = 2000,
) -> str:
    """Extractive standing-constraints list for the pre-compress summary prompt.

    Scans user + assistant text for constraint markers ("always", "never",
    "remember", "do not", "must", "avoid", "prefer*") and returns a bounded
    bullet list ("" when nothing salient). No LLM.
    """
    lines: List[str] = []
    seen = set()
    total = 0
    for role, text in _turns(messages):
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            s = sentence.strip()
            if len(s) < 8 or len(s) > 240 or not _MARKERS.search(s):
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            line = f"- {s}"
            if total + len(line) + 1 > max_chars:
                return "\n".join(lines)[:max_chars]
            lines.append(line)
            total += len(line) + 1
    return "\n".join(lines)[:max_chars]


def build_handoff(
    messages: Optional[List[Dict[str, Any]]],
    *,
    pinned: Optional[Sequence[str]] = None,
    max_chars: int = 1500,
) -> str:
    """§4.6's deterministic pre-compress handoff (EM-406). No LLM, no network.

    Scans user + assistant turns for standing constraints (the A2 markers plus
    "from now on" / "going forward" / "make sure"), decisions ("we decided",
    "let's go with", "agreed") and open loops ("TODO", "next step", "remind
    me", "follow up"). Each sentence lands in the first group it matches;
    duplicates are dropped case-insensitively; ``pinned`` (the scope's active
    pins, resolved by the caller) comes last. The whole text is bounded to
    ``max_chars`` by dropping from the tail — pinned first, constraints never
    — and "" means nothing was salient.
    """
    groups: List[Tuple[str, List[str]]] = [
        ("Constraints:", []),
        ("Decisions:", []),
        ("Open loops:", []),
    ]
    pinned_items: List[str] = []
    seen: set = set()

    def _take(bucket: List[str], sentence: str) -> None:
        key = sentence.lower()
        if key in seen:
            return
        seen.add(key)
        bucket.append(sentence)

    matchers = (
        (_CONSTRAINT_MARKERS, groups[0][1]),
        (_DECISION_MARKERS, groups[1][1]),
        (_LOOP_MARKERS, groups[2][1]),
    )
    for _role, text in _turns(messages):
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            s = sentence.strip()
            if len(s) < 8 or len(s) > 240:
                continue
            for pattern, bucket in matchers:
                if pattern.search(s):
                    _take(bucket, s)
                    break
    for item in pinned or ():
        s = (item or "").strip()
        if s:
            _take(pinned_items, s)

    blocks: List[List[str]] = [
        [header, *[f"- {s}" for s in bucket]] for header, bucket in groups if bucket
    ]
    if pinned_items:
        blocks.append(["Pinned:", *[f"- {s}" for s in pinned_items]])

    lines: List[str] = []
    total = 0
    for block in blocks:
        header, bullets = block[0], block[1:]
        # A header only lands with at least one bullet under it; once the
        # budget stops a block it stops the whole handoff (priority order:
        # constraints, decisions, open loops, pinned).
        if total + len(header) + 1 + len(bullets[0]) + 1 > max_chars:
            break
        lines.append(header)
        total += len(header) + 1
        for bullet in bullets:
            if total + len(bullet) + 1 > max_chars:
                return "\n".join(lines)
            lines.append(bullet)
            total += len(bullet) + 1
    return "\n".join(lines)


def handoff_fingerprint(messages: Optional[List[Dict[str, Any]]]) -> str:
    """sha256[:12] of the normalised (role, text) evidence sequence (EM-406).

    The episode key suffix for the pre-compress handoff: a retried compression
    of the same evidence produces the same fingerprint and converges onto the
    same ``precompress`` window, while new evidence opens the next one.
    """
    payload = "\x1f".join(f"{role}\x1e{text}" for role, text in _turns(messages))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
