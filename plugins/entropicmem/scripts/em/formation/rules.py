"""The deterministic rule extractor — the fallback half of §3.7 extraction
(EM-502 slice 1).

Formation must work with **no LLM configured** (§3.7's "LLM-assisted, never
LLM-dependent"), so the rule path is not a lesser copy of the model path — it is
the path that always runs. It reads a turn's text and returns candidate memories
with the same shape the model path produces: ``kind``/``content``/
``evidence_quote``/``speaker``/``author_id``/``source_turn``/``confidence``.

The patterns are EM-111's generic first-person set, extended per the card with
**correction** ("actually", "no, it's", "not X but Y") and **commitment**
("I'll", "we will", "by Friday") detection. Three rules keep it honest:

* **`evidence_quote` is verbatim.** Every quote is ``match.group(0)`` from the
  input, so it is a substring by construction — the substring check in
  :mod:`em.formation.extract` is the *guard*, not the source (a model path can
  invent a quote; this one cannot).
* **Assistant claims are capped.** §3.7: an assistant-originated claim gets
  ``confidence ≤ 0.6`` unless the user confirmed it, so the caller's ``speaker``
  decides the cap, not the pattern.
* **No domain-specific vocabularies.** EM-111's lesson: keyword lists for one
  employer's world leak that world into a generic engine and miss everything
  else. These patterns are about *grammar*, not topics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

__all__ = [
    "ASSISTANT_CONFIDENCE_CAP",
    "Candidate",
    "KINDS",
    "extract_candidates",
]

#: Appendix C.1's kind enum.
KINDS = ("fact", "preference", "profile", "procedure", "event", "constraint")

#: §3.7: assistant-originated claims are no more than half-believed until the
#: user confirms them.
ASSISTANT_CONFIDENCE_CAP = 0.6

#: A candidate shorter than this is almost always a pattern fragment.
_MIN_CONTENT = 8

#: ``(kind, domain, confidence, importance, pattern)``. Order sets the output
#: order within one turn; a longer, more specific rule is listed first so its
#: match is not shadowed by a broader one (dedupe keeps the first).
_RULES: Tuple[Tuple[str, str, float, float, str], ...] = (
    # Commitments before preferences: "I'll use Postgres" names a future act,
    # not a taste.
    ("event", "Knowledge", 0.75, 0.6,
     r"\b(?:i'll|i will|we'll|we will|i'm going to|we're going to)\s+[^.!?\n]{3,200}"),
    ("event", "Knowledge", 0.75, 0.6,
     r"\b[^.!?\n]{0,120}\bby\s+(?:monday|tuesday|wednesday|thursday|friday|saturday"
     r"|sunday|tomorrow|next week|end of (?:the )?(?:day|week|month))\b[^.!?\n]{0,80}"),
    # Corrections: the user overturning a prior fact.
    ("fact", "Knowledge", 0.7, 0.6,
     r"\b(?:actually|no,?\s+it'?s|it'?s not|not\s+\w+\s+but)\b[^.!?\n]{3,200}"),
    # Preferences.
    ("preference", "Preferences", 0.8, 0.6,
     r"\b(?:i|we)\s+(?:always |usually |often |also |still |really |generally "
     r"|typically |tend to |prefer to )?(?:prefer|like|love|want|need|hate|dislike"
     r"|use|using|keep|choose|avoid|work with|work on|live in|run|manage|maintain"
     r"|build|drive|own)\b[^.!?\n]{3,200}"),
    # Profile: identity and possessions stated in the first person.
    ("profile", "People", 0.85, 0.7,
     r"\bmy\s+[a-z][\w\- ]{2,40}?\s+(?:is|are|was|were|has|have|runs|uses|needs"
     r"|works)\b[^.!?\n]{2,200}"),
    ("profile", "People", 0.8, 0.7,
     r"\b(?:i am|i'm)\s+(?:a|an|the)\s+[^.!?\n]{3,150}"),
    # Constraints and rules the user sets on their world.
    ("constraint", "Preferences", 0.8, 0.7,
     r"\b(?:i|we)\s+(?:always|never|must|should|have to|need to|can't|cannot|won't"
     r"|will not)\b[^.!?\n]{3,200}"),
    ("constraint", "Preferences", 0.8, 0.7,
     r"\b(?:from now on|going forward|make sure|remember to|never use|always use)\b"
     r"[^.!?\n]{3,200}"),
    # A stated procedure: an ordered step list.
    ("procedure", "Knowledge", 0.7, 0.6,
     r"\b(?:first|then)\b[^.!?\n]{3,150}[,;]\s*(?:then|next|after that|finally)\b"
     r"[^.!?\n]{0,150}"),
)

_COMPILED = tuple(
    (kind, domain, confidence, importance, re.compile(pattern, re.IGNORECASE))
    for kind, domain, confidence, importance, pattern in _RULES
)


@dataclass(frozen=True)
class Candidate:
    """One extracted memory, in Appendix C.1's shape.

    ``evidence_quote`` is the verbatim substring the rule matched (or, on the
    model path, the model's claimed quote); ``content`` is the memory the
    extractor would store. They are equal for rule extractions — the sentence
    *is* the memory — and may differ for a model's summarised phrasing.
    """

    kind: str
    content: str
    evidence_quote: str
    speaker: str = "user"
    author_id: str = ""
    source_turn: int = -1
    confidence: float = 0.5
    importance: float = 0.5
    domain: str = "Knowledge"
    entities: Tuple[str, ...] = ()
    valid_from: str = ""


def _cap_for_speaker(confidence: float, speaker: str) -> float:
    if str(speaker).lower() == "assistant":
        return min(confidence, ASSISTANT_CONFIDENCE_CAP)
    return confidence


def extract_candidates(
    text: str,
    *,
    speaker: str = "user",
    author_id: str = "",
    source_turn: int = -1,
) -> List[Candidate]:
    """Every candidate a turn's *text* states, in reading order.

    A turn is one speaker's message, so ``speaker`` applies to all of it. The
    quote is the matched substring (never a paraphrase) and is capped at 300
    characters by prefix, which keeps it a substring.
    """
    if not text:
        return []
    found: List[Candidate] = []
    seen: set = set()
    for kind, domain, confidence, importance, pattern in _COMPILED:
        for match in pattern.finditer(text):
            quote = match.group(0).strip()
            if len(quote) < _MIN_CONTENT:
                continue
            quote = quote[:300]
            key = (kind, quote.casefold())
            if key in seen:
                continue
            seen.add(key)
            found.append(
                Candidate(
                    kind=kind,
                    content=quote,
                    evidence_quote=quote,
                    speaker=str(speaker),
                    author_id=str(author_id),
                    source_turn=int(source_turn),
                    confidence=_cap_for_speaker(confidence, speaker),
                    importance=importance,
                    domain=domain,
                )
            )
    return found
