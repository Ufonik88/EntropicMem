"""Window extraction: segmentation, validation, and the two paths (§3.7, EM-502
slice 1).

This module owns the *shape* of extraction — how a window's turns become
segments, what makes a candidate acceptable, and how the rule path and the
model path combine. It does **not** yet run as a job: wiring
``extract_window``/``extract_session`` into the worker (and carrying the turn's
scope into the write) is EM-502 slice 2, kept separate because the write's scope
is the isolation-sensitive half.

What is pinned here:

* **Segmentation** — a window is split into ≤ 6,000-character segments with one
  turn of overlap, so a fact spanning a boundary is seen whole by the segment
  that continues it (and, deliberately, seen *twice* — dedupe is downstream).
* **The evidence guard** — a candidate whose ``evidence_quote`` is not a
  verbatim substring of the transcript is **rejected**. The rule path cannot
  fail it; the model path can, and a fabricated quote must never reach a write.
* **The model path** — Appendix C.1's prompt and schema, called through the
  EM-501 :class:`~em.formation.llm.FormationLLM` seam, so a configured LLM is
  bounded by the same breaker and budget as everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .rules import Candidate, extract_candidates

__all__ = [
    "EXTRACT_SCHEMA",
    "EXTRACT_SYSTEM_PROMPT",
    "MAX_EVIDENCE_CHARS",
    "MAX_SEGMENT_CHARS",
    "Turn",
    "build_transcript",
    "extract_rules",
    "extract_window",
    "extract_with_llm",
    "render_turn",
    "segment_turns",
    "validate_candidates",
]

#: §3.7: segments stay under this so one bad turn cannot blow the prompt budget.
MAX_SEGMENT_CHARS = 6000
#: Appendix C.1's `evidence_quote` cap.
MAX_EVIDENCE_CHARS = 300

#: Appendix C.1, verbatim.
EXTRACT_SYSTEM_PROMPT = (
    "You extract long-term memories from a conversation between a USER and an ASSISTANT.\n"
    "Keep only information useful in future conversations: the user's identity, preferences, goals,\n"
    "projects, relationships, decisions, commitments, procedures they use, constraints they set,\n"
    "and facts about their world. Skip small talk, transient task details, and anything the\n"
    "assistant merely suggested unless the user accepted it. Never output secrets or credentials.\n"
    "Each memory must be self-contained (resolve pronouns; include names, versions, numbers).\n"
    "evidence_quote MUST be copied verbatim from the transcript."
)

#: Appendix C.1's response schema, shaped for `em.util.jsonschema_lite`.
EXTRACT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["memories"],
    "properties": {
        "memories": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "required": ["kind", "content", "confidence", "evidence_quote", "speaker"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["fact", "preference", "profile", "procedure", "event", "constraint"],
                    },
                    "content": {"type": "string", "maxLength": 1200},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "valid_from": {"type": "string"},
                    "confidence": {"type": "number"},
                    "importance": {"type": "number"},
                    "evidence_quote": {"type": "string", "maxLength": MAX_EVIDENCE_CHARS},
                    "speaker": {"type": "string", "enum": ["user", "assistant"]},
                    "source_turn": {"type": "integer"},
                },
            },
        }
    },
}


@dataclass(frozen=True)
class Turn:
    """One message of a window: its speaker, text, and provenance."""

    role: str  # "user" | "assistant"
    text: str
    author_id: str = ""
    turn: int = -1


def render_turn(turn: Turn) -> str:
    """Appendix C.1's line form: ``[turn 12][user:<author>] …``."""
    if turn.role == "user" and turn.author_id:
        who = f"user:{turn.author_id}"
    else:
        who = turn.role
    prefix = f"[turn {turn.turn}]" if turn.turn >= 0 else ""
    return f"{prefix}[{who}] {turn.text}"


def build_transcript(turns: Sequence[Turn]) -> str:
    return "\n".join(render_turn(turn) for turn in turns)


def segment_turns(
    turns: Sequence[Turn], *, max_chars: int = MAX_SEGMENT_CHARS, overlap: int = 1
) -> List[List[Turn]]:
    """Group turns into ≤ *max_chars* segments, carrying *overlap* turns over.

    The overlap is the last ``overlap`` turns of a full segment, repeated as the
    head of the next — so a fact whose first half ends one segment is completed
    in the next rather than cut. An empty input yields no segments.
    """
    segments: List[List[Turn]] = []
    current: List[Turn] = []
    size = 0
    for turn in turns:
        rendered = len(render_turn(turn)) + 1
        if current and size + rendered > max_chars:
            segments.append(current)
            current = current[-overlap:] if overlap > 0 else []
            size = sum(len(render_turn(t)) + 1 for t in current)
        current.append(turn)
        size += rendered
    if current:
        segments.append(current)
    return segments


def validate_candidates(
    candidates: Iterable[Candidate], *, transcript: str
) -> List[Candidate]:
    """Keep only candidates whose ``evidence_quote`` is verbatim in *transcript*.

    This is §3.7's anti-hallucination rule: a quote that is not a substring of
    the input is a fabricated citation, and the whole candidate is dropped
    rather than written with a quote nobody can check.
    """
    kept: List[Candidate] = []
    for candidate in candidates:
        quote = candidate.evidence_quote or ""
        if not quote or len(quote) > MAX_EVIDENCE_CHARS:
            continue
        if quote not in transcript:
            continue
        if not (candidate.content or "").strip():
            continue
        kept.append(candidate)
    return kept


def extract_rules(turns: Sequence[Turn]) -> List[Candidate]:
    """The deterministic path: each turn through the rule extractor."""
    out: List[Candidate] = []
    for turn in turns:
        out.extend(
            extract_candidates(
                turn.text,
                speaker=turn.role,
                author_id=turn.author_id,
                source_turn=turn.turn,
            )
        )
    return out


def _candidate_from_model(raw: Dict[str, Any]) -> Optional[Candidate]:
    kind = str(raw.get("kind") or "").strip()
    content = str(raw.get("content") or "").strip()
    quote = str(raw.get("evidence_quote") or "").strip()
    speaker = str(raw.get("speaker") or "user").strip() or "user"
    if kind not in ("fact", "preference", "profile", "procedure", "event", "constraint"):
        return None
    if not content or not quote:
        return None
    entities = raw.get("entities") or []
    try:
        source_turn = int(raw.get("source_turn", -1))
    except (TypeError, ValueError):
        source_turn = -1
    return Candidate(
        kind=kind,
        content=content,
        evidence_quote=quote,
        speaker=speaker,
        source_turn=source_turn,
        confidence=float(raw.get("confidence", 0.5) or 0.5),
        importance=float(raw.get("importance", 0.5) or 0.5),
        entities=tuple(str(e) for e in entities if str(e).strip()),
        valid_from=str(raw.get("valid_from") or ""),
    )


def extract_with_llm(
    turns: Sequence[Turn], llm: Any, *, entities: Sequence[str] = ()
) -> List[Candidate]:
    """The model path: Appendix C.1 per segment, through the EM-501 seam.

    A segment that yields nothing (no LLM, a breaker-open ``None``, malformed
    JSON) simply contributes no candidates — fail-soft, never a raise.
    """
    known = ", ".join(str(e) for e in entities if str(e).strip())
    out: List[Candidate] = []
    for segment in segment_turns(turns):
        prompt = (
            f"<known_entities>{known}</known_entities>\n"
            f"<transcript>\n{build_transcript(segment)}\n</transcript>"
        )
        result = llm.complete_json(
            task="extract",
            system=EXTRACT_SYSTEM_PROMPT,
            user=prompt,
            schema=EXTRACT_SCHEMA,
        )
        if not result:
            continue
        for raw in result.get("memories") or []:
            if isinstance(raw, dict):
                candidate = _candidate_from_model(raw)
                if candidate is not None:
                    out.append(candidate)
    return out


def _dedupe(candidates: Iterable[Candidate]) -> List[Candidate]:
    seen: set = set()
    out: List[Candidate] = []
    for candidate in candidates:
        key = (candidate.kind, candidate.content.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def extract_window(
    turns: Sequence[Turn],
    *,
    llm: Any = None,
    use_rules: bool = True,
    entities: Sequence[str] = (),
) -> List[Candidate]:
    """The window's candidates: rules (always, unless disabled) + the model.

    Both paths pass through the same evidence guard, so a fabricated model
    quote is dropped exactly as a rule fragment would be.
    """
    candidates: List[Candidate] = []
    if use_rules:
        candidates.extend(extract_rules(turns))
    if llm is not None:
        candidates.extend(extract_with_llm(turns, llm, entities=entities))
    return validate_candidates(_dedupe(candidates), transcript=build_transcript(turns))
