"""The ``extract_window`` / ``extract_session`` job handlers (EM-502 slice 2).

Slice 1 built the extraction itself (rules, segmentation, the evidence guard).
This module is the half that runs it as a job: it reads a window's transcript
chunks, extracts candidates, and quarantines them as **pending** memories.

**The scope is carried in the payload, never guessed.** ``transcript_chunks``
has no scope column, so a handler that defaulted to "profile-wide" would write
every extracted memory into a bucket no scoped read looks at — or, worse, into a
profile-wide bucket every user of the profile can read. §4.1's worker therefore
receives the *turn's effective scope* (the provider's ``_turn_scope()``,
serialized at enqueue time) and refuses a payload without one
(``PermanentJobError`` — never guess who may read what). That is the invariant
the scope-consistency test pins: the profile a job writes is the profile the
same turn's reads use.

**Commit is EM-503's.** These handlers only quarantine (``status='pending'``,
``pending_reason='extracted'``); reconciliation decides ADD/UPDATE/SUPERSEDE and
applies the §3.7 step-3 auto-commit policy. Keeping extraction and commit apart
means a bad extractor cannot silently publish.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ..jobs.worker import PermanentJobError
from ..store.episodes import EpisodeStore
from ..store.memories import MemoryStore
from ..store.types import MemoryDraft, Scope
from .extract import Turn
from .extract import extract_window as extract_window_candidates

__all__ = [
    "EXTRACT_ACTOR",
    "EXTRACT_SESSION",
    "EXTRACT_WINDOW",
    "make_extract_session_handler",
    "make_extract_window_handler",
    "scope_from_payload",
]

EXTRACT_WINDOW = "extract_window"
EXTRACT_SESSION = "extract_session"
EXTRACT_ACTOR = "formation_extract"


def scope_from_payload(payload: Dict[str, Any]) -> Scope:
    """Rebuild the turn's ``Scope`` from the job payload.

    A missing or profile-less scope is **permanent**: retrying cannot invent the
    identity the write must carry, and defaulting to a profile would be the
    cross-profile leak this design exists to prevent.
    """
    raw = payload.get("scope")
    if not isinstance(raw, dict) or not raw:
        raise PermanentJobError(
            "extraction job has no scope; refusing to guess who may read the result"
        )
    profile = str(raw.get("profile") or "").strip()
    if not profile:
        raise PermanentJobError("extraction job scope has no profile")
    return Scope(
        profile=profile,
        user=str(raw.get("user") or ""),
        chat=str(raw.get("chat") or ""),
        chat_type=str(raw.get("chat_type") or ""),
        author=str(raw.get("author") or ""),
        is_owner=bool(raw.get("is_owner", False)),
    )


def _turns(rows: Iterable[Dict[str, Any]]) -> List[Turn]:
    return [
        Turn(
            role=str(row.get("role") or "user"),
            text=str(row.get("text") or ""),
            author_id=str(row.get("author_id") or ""),
            turn=int(row.get("seq") or -1),
        )
        for row in rows
    ]


def _write_candidates(
    conn,
    candidates: Iterable[Any],
    *,
    scope: Scope,
    session_id: str,
    origin: str,
    confidence_cap: Optional[float] = None,
) -> int:
    """Quarantine each candidate as a pending memory; return how many were new.

    ``source="auto_extracted"`` is deliberate for **both** handlers: that is the
    write policy's quarantine input (§3.7: an extracted candidate is not a
    durable fact until it is promoted). The extraction's own origin
    (``extracted_llm`` for a delegation, ``auto_extracted`` for a window) is kept
    as a tag, not as the policy source, so an LLM-extracted delegation cannot
    bypass quarantine.

    ``MemoryStore.add`` collapses an exact ``(content, scope)`` duplicate to a
    no-op, so a retried job converges onto the rows the first run wrote.
    """
    store = MemoryStore(conn)
    tags = ("extracted",)
    if origin and origin not in ("auto_extracted", "auto_extract"):
        tags = ("extracted", f"origin:{origin}")
    written = 0
    for candidate in candidates:
        confidence = float(candidate.confidence)
        if confidence_cap is not None:
            confidence = min(confidence, float(confidence_cap))
        draft = MemoryDraft(
            content=candidate.content,
            kind=candidate.kind,
            domain=candidate.domain,
            importance=float(candidate.importance),
            confidence=confidence,
            source="auto_extracted",
            source_session=session_id,
            source_turn=(candidate.source_turn if candidate.source_turn >= 0 else None),
            author_id=candidate.author_id,
            evidence=candidate.evidence_quote,
            tags=tags,
            status="pending",
            pending_reason="extracted",
            legacy_id="",
            visibility="",
        )
        result = store.add(draft, scope=scope, actor=EXTRACT_ACTOR)
        if result.ok:
            written += 1
    return written


def make_extract_window_handler():
    """Handler for ``extract_window``: ``{session_id, seq_start, seq_end, scope}``."""

    def handle(job, ctx) -> None:
        payload = job.payload
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise PermanentJobError("extract_window needs a non-empty session_id")
        seq_start = payload.get("seq_start")
        seq_end = payload.get("seq_end")
        if (
            not isinstance(seq_start, int)
            or isinstance(seq_start, bool)
            or not isinstance(seq_end, int)
            or isinstance(seq_end, bool)
            or seq_start > seq_end
        ):
            raise PermanentJobError("extract_window needs integer seq_start <= seq_end")
        scope = scope_from_payload(payload)

        with ctx.store.transaction() as conn:
            rows = EpisodeStore(conn).read_chunks(
                session_id, seq_start=seq_start, seq_end=seq_end
            )
        candidates = extract_window_candidates(_turns(rows))
        if not candidates:
            return
        if not ctx.heartbeat():
            return  # another worker owns the job; it will run (at-least-once)
        with ctx.store.transaction() as conn:
            _write_candidates(
                conn,
                candidates,
                scope=scope,
                session_id=session_id,
                origin="auto_extracted",
            )

    return handle


def make_extract_session_handler():
    """Handler for ``extract_session``: the session's chunks, or its episode."""

    def handle(job, ctx) -> None:
        payload = job.payload
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise PermanentJobError("extract_session needs a non-empty session_id")
        scope = scope_from_payload(payload)
        cap = payload.get("confidence_cap")
        confidence_cap = (
            float(cap) if isinstance(cap, (int, float)) and not isinstance(cap, bool) else None
        )
        source = str(payload.get("source") or "auto_extracted")

        with ctx.store.transaction() as conn:
            rows = EpisodeStore(conn).read_chunks(session_id)
            if not rows:
                # A delegation is summarised as an episode, not captured as
                # chunks; extract over the episode text with the payload's cap.
                episode_id = str(payload.get("episode_id") or "").strip()
                if episode_id:
                    row = conn.execute(
                        "SELECT title, summary FROM episodes WHERE id=?", (episode_id,)
                    ).fetchone()
                    if row is not None:
                        text = f"{row['title']}\n{row['summary']}".strip()
                        if text:
                            rows = [{"seq": 0, "role": "assistant", "author_id": "", "text": text}]
        candidates = extract_window_candidates(_turns(rows))
        if not candidates:
            return
        if not ctx.heartbeat():
            return
        with ctx.store.transaction() as conn:
            _write_candidates(
                conn,
                candidates,
                scope=scope,
                session_id=session_id,
                origin=source,
                confidence_cap=confidence_cap,
            )

    return handle
