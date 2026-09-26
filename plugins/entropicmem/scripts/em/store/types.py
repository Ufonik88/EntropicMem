"""Types shared by the v3 storage layer (§3.5 scope model, §3.4 status machine).

Stdlib-only, like everything under ``em.store``: no Hermes host imports, no
``os.environ`` reads. Values are frozen dataclasses so a draft cannot be
mutated after it is handed to ``MemoryStore.add``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

# --- §3.4 status machine -------------------------------------------------

Status = Literal["pending", "active", "superseded", "archived", "deleted"]

ALL_STATUSES: tuple[str, ...] = ("pending", "active", "superseded", "archived", "deleted")

# The only status eligible for prefetch (§3.4).
LIVE_STATUSES: tuple[str, ...] = ("active",)

# Legal edges, read straight off the §3.4 diagram:
#   pending   --promote/auto-commit--> active
#   pending   --ttl/discard--------> deleted
#   active    --update/supersede----> superseded
#   active    --archive------------> archived
#   active    --forget-------------> deleted
#   archived  --purge/hard---------> deleted
#   superseded--restore------------> active   (drawn as the return arrow)
#   superseded--archive------------> archived
# `pending -> active` and `active -> pending` are deliberately absent: a memory
# is never demoted into the pending queue.
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"active", "deleted"}),
    "active": frozenset({"superseded", "archived", "deleted"}),
    "superseded": frozenset({"active", "archived", "deleted"}),
    "archived": frozenset({"deleted"}),
    "deleted": frozenset(),  # terminal
}

TRANSITION_REASONS: dict[tuple[str, str], frozenset[str]] = {
    ("pending", "active"): frozenset({"promote", "auto_commit"}),
    ("pending", "deleted"): frozenset({"ttl_expired", "discard"}),
    ("active", "superseded"): frozenset({"supersede", "update"}),
    ("active", "archived"): frozenset({"archive", "consolidate", "decay"}),
    ("active", "deleted"): frozenset({"forget"}),
    ("superseded", "active"): frozenset({"restore"}),
    ("superseded", "archived"): frozenset({"archive", "consolidate", "decay"}),
    ("superseded", "deleted"): frozenset({"forget", "purge"}),
    ("archived", "deleted"): frozenset({"forget", "purge"}),
}


class InvalidTransition(ValueError):
    """Raised when a status change is not one of the legal §3.4 edges."""

    def __init__(self, current: str, target: str, reason: str = "") -> None:
        self.current = current
        self.target = target
        allowed = ", ".join(sorted(LEGAL_TRANSITIONS.get(current, frozenset()))) or "none (terminal)"
        msg = f"illegal transition {current!r} -> {target!r}; allowed from {current!r}: {allowed}"
        if reason:
            msg += f"; reason {reason!r} is not valid for this edge"
        super().__init__(msg)


def check_transition(current: str, target: str, reason: str = "") -> None:
    """Raise :class:`InvalidTransition` unless ``current -> target`` is legal."""
    if target not in LEGAL_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(current, target, reason)
    allowed_reasons = TRANSITION_REASONS.get((current, target))
    if allowed_reasons and reason and reason not in allowed_reasons:
        raise InvalidTransition(current, target, reason)


# --- scope (§3.5) ---------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """One turn's resolved scope. Mirrors the plan's ``ScopeContext``.

    ``user`` is the gateway id, or the owner id for local CLI sessions, and
    ``scope_user=''`` means profile-wide.
    """

    profile: str
    user: str = ""
    chat: str = ""
    chat_type: str = ""
    author: str = ""
    is_owner: bool = True

    @property
    def profile_wide(self) -> bool:
        return self.user == ""


# --- write inputs --------------------------------------------------------


@dataclass(frozen=True)
class MemoryDraft:
    """A proposed new memory. ``add`` runs the full pipeline over this."""

    content: str
    kind: str = "fact"
    domain: str = "Knowledge"
    sensitivity: str = "internal"
    source: str = "agent"
    source_session: str = ""
    source_turn: int | None = None
    author_id: str = ""
    evidence: str = ""
    summary: str = ""
    tags: tuple[str, ...] = ()
    visibility: str = "user"
    importance: float = 0.5
    confidence: float = 0.8
    pinned: bool = False
    decay_class: str = "standard"
    valid_from: str | None = None
    valid_to: str | None = None
    status: str = "pending"
    pending_reason: str = ""
    pending_expires_at: str | None = None


@dataclass(frozen=True)
class MemoryPatch:
    """A partial in-place edit. Only the fields set here are applied."""

    content: str | None = None
    summary: str | None = None
    tags: tuple[str, ...] | None = None
    kind: str | None = None
    domain: str | None = None
    sensitivity: str | None = None
    importance: float | None = None
    confidence: float | None = None
    evidence: str | None = None
    pinned: bool | None = None
    decay_class: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in (
            "content",
            "summary",
            "tags",
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
        ):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out

    def __bool__(self) -> bool:
        return bool(self.as_dict())


def with_content(draft: MemoryDraft, content: str) -> MemoryDraft:
    return replace(draft, content=content)


@dataclass(frozen=True)
class WriteResult:
    """Outcome of one write. ``audit_seq`` links the write to its audit row."""

    ok: bool
    id: str = ""
    status: str = ""
    decision: str = ""
    reason_code: str = ""
    audit_seq: int = 0


DECISIONS = (
    "created",
    "noop_duplicate",
    "updated",
    "superseded",
    "quarantined",
    "blocked",
)

_KINDS = (
    "fact",
    "preference",
    "profile",
    "procedure",
    "event",
    "constraint",
    "insight",
    "note",
)
