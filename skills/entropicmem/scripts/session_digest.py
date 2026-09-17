"""Extractive session digest - deterministic, no LLM.

Feeds the EntropicMem plugin's lifecycle hooks (P1 Slice 2):

- ``extractive_digest``   - A1/A5 session digest episodes, idempotent by
  construction via a deterministic ``ep_sess_{session_id}`` episode id.
- ``extract_constraints`` - A2: standing constraints fed to the compression
  summary prompt, persisted as a ``pre_compress`` episode.

Pure stdlib: no network, no LLM, no host state.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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

_WS = re.compile(r"\s+")


def _message_text(msg: Dict[str, Any]) -> str:
    """Flatten one OpenAI-style message to plain text ('' for non-text content)."""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # multipart content
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return " ".join(parts)
    return ""


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


def episode_id_for(session_id: str) -> str:
    """Deterministic, idempotent episode id for a session digest (A1/A5)."""
    return "ep_sess_" + (_sanitize_session_id(session_id) or "unknown")


def precompress_episode_id(session_id: str) -> str:
    """Deterministic episode id for a pre-compression constraint digest (A2)."""
    return "ep_precomp_" + (_sanitize_session_id(session_id) or "unknown")


def _timestamp_of(msg: Dict[str, Any]) -> Optional[str]:
    ts = msg.get("timestamp")
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
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
    end_ts = datetime.now().isoformat(timespec="seconds")
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
