"""Deterministic reconciliation and the commit policy (§3.7 steps 2-3, EM-503).

A candidate extracted by EM-502 is quarantined `pending`. This module decides
what it *means* against the memories already in scope, and whether it may become
durable:

* **Decide** — `ADD | UPDATE(target) | SUPERSEDE(target) | NOOP | CONFLICT`.
  The deterministic path (the one that runs with `formation.llm=none`) is the
  law: an exact content hash is `NOOP`; the same subject+attribute with a
  **different value** is `SUPERSEDE`; a near-duplicate (token cosine ≥ 0.92)
  whose numbers and negations agree is `UPDATE`; everything else is `ADD`.
  `CONFLICT` — "contradictory, but I cannot tell which is true" — is the
  **model's** uncertain verdict; the deterministic path never invents it.
* **Commit** — §3.7 step 3: `user_stated` or (confidence ≥
  `formation.auto_commit_min_confidence`, kind ∈ `formation.auto_commit_kinds`,
  tier ≤ internal, no trust flags) commits to `active`; everything else stays
  `pending` for review.
* **Apply** — the store's own versioned writes do the work: `UPDATE` bumps the
  target's version and snapshots the old content, `SUPERSEDE` links the old row
  to a successor, `NOOP`/`UPDATE`/`SUPERSEDE` discard the redundant candidate,
  `CONFLICT` keeps it pending with a `conflict:<target>` trust flag. Every
  decision appends an audit record naming the decision and the target.

Candidate retrieval (the top-5 neighbours) is the caller's job — the same
retrieval seam the pipeline owns — so this module stays testable without an
index. `reconcile_candidate` is the one entry point: decide, apply, audit.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..store.audit import append as audit_append
from ..store.memories import MemoryStore
from ..store.types import MemoryDraft, MemoryPatch, Scope

__all__ = [
    "ADD",
    "CONFLICT",
    "CONFLICT_PREFIX",
    "DECISIONS",
    "NOOP",
    "RECONCILE_ACTOR",
    "SUPERSEDE",
    "UPDATE",
    "Attribute",
    "CommitPlan",
    "Reconciliation",
    "apply_decision",
    "commit_policy",
    "decide",
    "extract_attribute",
    "reconcile_candidate",
    "token_cosine",
]

ADD = "ADD"
UPDATE = "UPDATE"
SUPERSEDE = "SUPERSEDE"
NOOP = "NOOP"
CONFLICT = "CONFLICT"
DECISIONS = (ADD, UPDATE, SUPERSEDE, NOOP, CONFLICT)

SIMILARITY_UPDATE = 0.92
DEFAULT_MIN_CONFIDENCE = 0.75
DEFAULT_AUTO_COMMIT_KINDS = ("preference", "profile", "constraint", "procedure", "fact")
CONFLICT_PREFIX = "conflict:"
RECONCILE_ACTOR = "reconcile"

#: The §3.7 attribute detector: ``<subject> <copula|preference|location|cost> <value>``.
_ATTRIBUTE = re.compile(
    r"(?P<subject>[A-Za-z][\w\- ]{0,50}?)\s+"
    r"(?P<attribute>is|are|was|were|uses|prefers|lives in|works at|works for"
    r"|moved to|switched to|runs on|costs)\s+"
    r"(?P<value>.{1,120}?)(?=[.!?](?:\s|$)|\n|$)",
    re.IGNORECASE,
)
_POSSESSIVE = re.compile(r"^(?:my|our|the|this|his|her|their)\s+", re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_NEGATION = re.compile(r"\b(?:not|never|no|none|without|cannot|can't|won't)\b", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be been but by for from has have in into is it its of on or "
    "that the their there these this to was were will with".split()
)


@dataclass(frozen=True)
class Attribute:
    """A normalised ``subject + attribute -> value`` fact statement."""

    subject: str
    attribute: str
    value: str

    @property
    def key(self) -> Tuple[str, str]:
        return (self.subject, self.attribute)


@dataclass(frozen=True)
class Reconciliation:
    decision: str
    target_id: Optional[str] = None
    merged_content: str = ""
    reason: str = ""


@dataclass(frozen=True)
class CommitPlan:
    status: str  # "active" | "pending"
    reason: str
    pending_ttl_days: int = 30


# --- deterministic reading ---------------------------------------------------


def _normalise_subject(subject: str) -> str:
    cleaned = _POSSESSIVE.sub("", subject.strip().casefold())
    return " ".join(cleaned.split())


def _normalise_value(value: str) -> str:
    text = value.strip().rstrip(".").casefold()
    for tail in (" now", " currently", " today"):
        if text.endswith(tail):
            text = text[: -len(tail)]
    return " ".join(text.split())


def extract_attribute(text: str) -> Optional[Attribute]:
    """The first ``subject attribute value`` statement, normalised."""
    if not text:
        return None
    match = _ATTRIBUTE.search(text)
    if not match:
        return None
    subject = _normalise_subject(match.group("subject"))
    value = _normalise_value(match.group("value"))
    if not subject or not value:
        return None
    return Attribute(subject, match.group("attribute").casefold(), value)


def _numbers(text: str) -> Tuple[str, ...]:
    return tuple(sorted(_NUMBER.findall(text)))


def _negated(text: str) -> bool:
    return bool(_NEGATION.search(text))


def _tokens(text: str) -> Counter:
    return Counter(t for t in _WORD.findall(text.casefold()) if t not in _STOP)


def token_cosine(left: str, right: str) -> float:
    """Bag-of-words cosine — the deterministic stand-in for the vector cosine."""
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    dot = sum(count * b[token] for token, count in a.items() if token in b)
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


# --- the decision ------------------------------------------------------------


def decide(
    candidate: Mapping[str, Any],
    neighbours: Sequence[Mapping[str, Any]],
    *,
    llm: Any = None,
    similarity=token_cosine,
) -> Reconciliation:
    """Decide how *candidate* relates to its neighbours (§3.7 step 2)."""
    if llm is not None:
        modelled = _decide_with_llm(candidate, neighbours, llm)
        if modelled is not None:
            return modelled

    content = str(candidate.get("content") or "")
    if not content.strip():
        return Reconciliation(ADD, reason="empty")

    content_hash = candidate.get("content_hash")
    for neighbour in neighbours:
        if content_hash and neighbour.get("content_hash") == content_hash:
            return Reconciliation(NOOP, str(neighbour.get("id") or ""), reason="exact_duplicate")

    mine = extract_attribute(content)
    if mine is not None:
        for neighbour in neighbours:
            theirs = extract_attribute(str(neighbour.get("content") or ""))
            if theirs is not None and mine.key == theirs.key and mine.value != theirs.value:
                return Reconciliation(
                    SUPERSEDE,
                    str(neighbour.get("id") or ""),
                    reason=f"attribute_changed:{mine.attribute}",
                )

    best: Optional[Mapping[str, Any]] = None
    best_score = 0.0
    for neighbour in neighbours:
        score = similarity(content, str(neighbour.get("content") or ""))
        if score > best_score:
            best, best_score = neighbour, score
    if best is not None and best_score >= SIMILARITY_UPDATE:
        other = str(best.get("content") or "")
        if _numbers(content) == _numbers(other) and _negated(content) == _negated(other):
            return Reconciliation(
                UPDATE, str(best.get("id") or ""), reason=f"near_duplicate:{best_score:.2f}"
            )
    return Reconciliation(ADD, reason="new_information")


RECONCILE_SYSTEM_PROMPT = (
    "Decide how a NEW memory relates to EXISTING memories. Options:\n"
    "ADD (new information), NOOP (already known), UPDATE (same fact, better wording or more detail),\n"
    "SUPERSEDE (the fact changed; the old one is no longer true), CONFLICT (contradiction but unclear which is true).\n"
    "Prefer SUPERSEDE when the new memory states a newer value for the same attribute."
)

RECONCILE_SCHEMA = {
    "type": "object",
    "required": ["decision"],
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["ADD", "NOOP", "UPDATE", "SUPERSEDE", "CONFLICT"],
        },
        "target_id": {"type": "string"},
        "merged_content": {"type": "string", "maxLength": 1200},
        "reason": {"type": "string", "maxLength": 200},
    },
}


def _decide_with_llm(
    candidate: Mapping[str, Any], neighbours: Sequence[Mapping[str, Any]], llm: Any
) -> Optional[Reconciliation]:
    if not neighbours:
        return None
    lines = [
        f"[{n.get('id')}] {n.get('content')}" for n in neighbours
    ]
    user = (
        f"<candidate>\n{str(candidate.get('content') or '')}\n</candidate>\n"
        f"<existing>\n" + "\n".join(lines) + "\n</existing>"
    )
    result = llm.complete_json(
        task="reconcile", system=RECONCILE_SYSTEM_PROMPT, user=user, schema=RECONCILE_SCHEMA
    )
    if not result:
        return None
    decision = str(result.get("decision") or "").upper()
    if decision not in DECISIONS:
        return None
    target = str(result.get("target_id") or "").strip() or None
    if decision in (UPDATE, SUPERSEDE, CONFLICT):
        if target is None or target not in {str(n.get("id")) for n in neighbours}:
            return None  # a target outside the provided neighbours is unusable
    else:
        target = None
    return Reconciliation(
        decision, target, str(result.get("merged_content") or ""), str(result.get("reason") or "")
    )


# --- the commit policy -------------------------------------------------------


def _trust_flags(candidate: Mapping[str, Any]) -> List[str]:
    raw = candidate.get("trust_flags")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    return [str(flag) for flag in (raw or [])]


def commit_policy(
    candidate: Mapping[str, Any],
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    kinds: Sequence[str] = DEFAULT_AUTO_COMMIT_KINDS,
    pending_ttl_days: int = 30,
) -> CommitPlan:
    """§3.7 step 3: may this candidate become durable, or must it stay pending?"""
    source = str(candidate.get("source") or "")
    if source in ("user_stated", "promoted", "pending_promoted"):
        return CommitPlan("active", "user_stated", pending_ttl_days)
    confidence = float(candidate.get("confidence") or 0.0)
    kind = str(candidate.get("kind") or "fact")
    tier = str(candidate.get("sensitivity") or "internal")
    if (
        confidence >= float(min_confidence)
        and kind in kinds
        and tier in ("public", "internal")
        and not _trust_flags(candidate)
    ):
        return CommitPlan("active", "confident_candidate", pending_ttl_days)
    return CommitPlan("pending", "needs_review", pending_ttl_days)


# --- applying a decision -----------------------------------------------------


def _draft_from(candidate: Mapping[str, Any]) -> MemoryDraft:
    return MemoryDraft(
        content=str(candidate.get("content") or ""),
        kind=str(candidate.get("kind") or "fact"),
        domain=str(candidate.get("domain") or "Knowledge"),
        importance=float(candidate.get("importance") or 0.5),
        confidence=float(candidate.get("confidence") or 0.5),
        source="auto_extracted",
        source_session=str(candidate.get("source_session") or ""),
        source_turn=candidate.get("source_turn"),
        evidence=str(candidate.get("evidence") or ""),
        tags=("extracted",),
        status="pending",
        pending_reason="extracted",
        legacy_id="",
        visibility="",
    )


def apply_decision(
    conn,
    candidate: Mapping[str, Any],
    decision: Reconciliation,
    *,
    scope: Scope,
    plan: CommitPlan,
    actor: str = RECONCILE_ACTOR,
) -> Dict[str, Any]:
    """Apply one reconciled decision, then audit it. Returns a small outcome."""
    store = MemoryStore(conn)
    candidate_id = str(candidate.get("id") or "")
    outcome: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "decision": decision.decision,
        "target_id": decision.target_id or "",
        "status": "",
    }

    if decision.decision == ADD:
        if plan.status == "active":
            result = store.set_status(candidate_id, "active", actor=actor, reason="auto_commit")
            outcome["status"] = result.status or ""
        else:
            outcome["status"] = "pending"

    elif decision.decision == UPDATE:
        if plan.status != "active":
            outcome["status"] = "pending"  # keep it for review; no write
        else:
            # The candidate shares the target's new content, so discard it
            # *first*: leaving it live would make the edit collide with it
            # (`duplicate_content`, the store's exact-hash guard).
            store.set_status(candidate_id, "deleted", actor=actor, reason="discard")
            result = store.update(
                str(decision.target_id),
                MemoryPatch(content=str(candidate.get("content") or "")),
                actor=actor,
                reason="update",
            )
            outcome["status"] = "merged" if result.ok else "blocked"

    elif decision.decision == SUPERSEDE:
        if plan.status != "active":
            outcome["status"] = "pending"  # keep it for review; no write
        else:
            # Discard the candidate first: `supersede` inserts live and its
            # dedupe would otherwise collapse onto this same-content pending
            # row and skip marking the old memory superseded.
            store.set_status(candidate_id, "deleted", actor=actor, reason="discard")
            result = store.supersede(
                str(decision.target_id),
                _draft_from(candidate),
                scope=scope,
                actor=actor,
                reason="supersede",
            )
            if result.ok:
                outcome["status"] = "superseded"
                outcome["successor_id"] = result.id
            else:
                outcome["status"] = "blocked"

    elif decision.decision == NOOP:
        store.set_status(candidate_id, "deleted", actor=actor, reason="discard")
        outcome["status"] = "discarded"

    elif decision.decision == CONFLICT:
        store.set_trust_flags(
            candidate_id,
            [f"{CONFLICT_PREFIX}{decision.target_id or ''}"],
            actor=actor,
            reason="conflict",
        )
        outcome["status"] = "pending"

    audit_append(
        conn,
        "reconcile",
        actor,
        candidate_id,
        {
            "decision": decision.decision,
            "target": decision.target_id or "",
            "reason": decision.reason[:200],
        },
    )
    return outcome


def reconcile_candidate(
    conn,
    candidate: Mapping[str, Any],
    neighbours: Sequence[Mapping[str, Any]],
    *,
    scope: Scope,
    plan: Optional[CommitPlan] = None,
    llm: Any = None,
    actor: str = RECONCILE_ACTOR,
) -> Tuple[Reconciliation, Dict[str, Any]]:
    """The one entry point: decide, apply, audit."""
    decision = decide(candidate, neighbours, llm=llm)
    resolved = plan if plan is not None else commit_policy(candidate)
    outcome = apply_decision(conn, candidate, decision, scope=scope, plan=resolved, actor=actor)
    return decision, outcome
