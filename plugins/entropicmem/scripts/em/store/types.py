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

#: Tiers that only their owner may read (§3.5). Everything else is readable by
#: anyone in scope, which is the rule ``_in_scope`` already applied.
OWNER_ONLY_TIERS: tuple[str, ...] = ("sensitive", "secret")


def may_read_owner_only(scope: "Scope") -> bool:
    """True when this caller may read a row in :data:`OWNER_ONLY_TIERS` (§3.5).

    The one definition of the owner context. ``MemoryStore._in_scope`` uses it as
    a predicate and ``em.retrieval.candidates.scope_sql`` uses it to decide
    whether to emit the SQL exclusion, so the two cannot drift into disagreeing
    about who the owner is. A profile-wide caller (``user == ''``) is the owner —
    the v2 single-owner, no-gateway and CLI case — and a scoped caller must
    assert ``is_owner``.
    """
    return scope.user == "" or bool(scope.is_owner)


@dataclass(frozen=True)
class Scope:
    """One turn's resolved scope. Mirrors the plan's ``ScopeContext``.

    ``user`` is the gateway id, or the owner id for local CLI sessions, and
    ``scope_user=''`` means profile-wide.

    ``is_owner`` defaults to ``False`` **on purpose** — it is fail-closed. Only a
    scoped caller can leak (a guest is exactly a caller with a non-empty
    ``user``), so the default makes such a caller prove ownership instead of
    inheriting it. A misconfiguration then hides the owner's own sensitive rows,
    which is a visible bug, rather than showing them to a guest, which is a
    silent one. A profile-wide caller (``user == ''``) is the owner context
    regardless — the v2 single-owner, no-gateway and CLI case — so the default
    facade keeps working without every call site asserting ownership.
    """

    profile: str
    user: str = ""
    chat: str = ""
    chat_type: str = ""
    author: str = ""
    is_owner: bool = False

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
    #: Opt-in PII locale packs (EM-115) — e.g. ``("za",)``. Threaded through the
    #: draft because redaction happens inside ``add``, and a write must redact
    #: with the caller's packs, not the process default.
    pii_locales: tuple[str, ...] = ()
    #: The v2-shaped, content-derived id this memory should also answer to.
    #: ``memories.legacy_id`` is UNIQUE and content-derived, so it is only
    #: meaningful for a profile-wide write (v2 had one owner per database); a
    #: user-scoped draft leaves it empty. The v2-to-v3 migration stamps it for
    #: every migrated row and EM-211's facade ``remember`` stamps it the same
    #: way, which is what keeps ``get_fact(StoredFact.make_id(content))``
    #: resolving after a cutover.
    legacy_id: str = ""


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
