"""Write policy + sensitivity tiers for EntropicMem (Phase 2 security)."""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence, Tuple

SENSITIVITY_LEVELS = ("public", "internal", "sensitive", "secret")

# Domains default tier
DOMAIN_DEFAULT_TIER = {
    "Finance": "sensitive",
    "People": "sensitive",
    "Events": "sensitive",
    "Infrastructure": "internal",
    "Acme Corp": "internal",
    "Projects": "internal",
    "Knowledge": "internal",
    "Content-Growth": "internal",
    "Workflows": "internal",
    "Products-Research": "internal",
    "Rules": "internal",
    "Test": "public",
}

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(sk|pk)[_-][A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|secret[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"(?i)-----BEGIN (RSA |OPENSSH |EC )?PRIV" r"ATE KEY-----"),
    re.compile(r"(?i)\b(password|passwd|pwd)\s*[=:]\s*\S+"),
    re.compile(r"(?i)\bVaultKnox master password\b"),
    re.compile(r"(?i)\b(aws_secret_access_key|xox[baprs]-)\S+"),
    re.compile(r"(?i)\bsk_live_[A-Za-z0-9]+\b"),
]


def normalize_sensitivity(value: Optional[str], domain: str = "Knowledge") -> str:
    v = (value or "").strip().lower()
    if v in SENSITIVITY_LEVELS:
        return v
    return DOMAIN_DEFAULT_TIER.get(domain, "internal")


def detect_secret(content: str) -> bool:
    if not content:
        return False
    return any(p.search(content) for p in _SECRET_PATTERNS)


def evaluate_write(
    content: str,
    *,
    domain: str = "Knowledge",
    sensitivity: Optional[str] = None,
    source: str = "agent",
) -> Tuple[str, Optional[str]]:
    """Return (action, reason).

    action: allow | block | quarantine
    """
    tier = normalize_sensitivity(sensitivity, domain)
    if tier == "secret" or detect_secret(content):
        return "block", "secret_or_credential_pattern — store secrets in a secrets manager, not EntropicMem"
    # Auto-extract never lands directly in durable facts
    if source in ("auto_extracted", "auto_extract"):
        return "quarantine", "auto_extracted_requires_promotion"
    # A human vault edit (EM-604) is a proposal too: it enters the review queue
    # rather than the live store, so the user's own note is confirmed first.
    if source == "vault_edit":
        return "quarantine", "vault_edit_requires_review"
    # An ingested document's claims (EM-607) are the same shape of proposal: a
    # fetched article is third-party text, and nothing it says is the user's
    # word. It is queued for review, never written straight into durable recall.
    if source == "ingest":
        return "quarantine", "ingest_requires_review"
    if source in ("promoted", "pending_promoted"):
        return "allow", None
    if domain in ("Finance", "People") and source in ("auto_extracted", "conversation"):
        return "quarantine", "sensitive_domain_needs_explicit_remember"
    return "allow", None


# --- EM-703: the injection trust policy ---------------------------------------

#: Sources whose content is *proposal* text — extracted claims, an ingested
#: document, a human vault edit — rather than a speaker's own word. EM-703's
#: split follows it: a flagged **extracted** source defaults to quarantine
#: (the candidate is already a proposal, so parking it pending is honest), a
#: flagged **direct** source defaults to flag-through (the v2.7 warning-marker
#: behaviour, and the owner's own sentence). Every other source — ``agent``,
#: ``agent_tool``, ``guest_tool``, ``user_stated``, ``promoted`` — is direct.
EXTRACTED_SOURCES = frozenset({
    "auto_extracted",
    "auto_extract",
    "ingest",
    "vault_edit",
})

#: The actions a trust policy may name. A member outside this set fails OPEN to
#: ``flag`` — the write is recorded, never blocked, and never invented: an
#: unusable policy spelling must not be able to take the write path down, and
#: must not quietly launder flagged content either.
_INJECTION_ACTIONS = frozenset({"flag", "quarantine", "drop"})


def _injection_member(value: object) -> str:
    """Normalise one policy member; anything unusable fails open to ``flag``."""
    text = str(value if value is not None else "").strip().lower()
    return text if text in _INJECTION_ACTIONS else "flag"


def evaluate_injection(
    shapes: "Sequence[str]",
    *,
    source: str = "agent",
    policy: "Any | None" = None,
) -> Tuple[str, Optional[str]]:
    """Turn the screen's shapes into a write decision: (action, reason).

    ``action`` is one of ``allow`` (nothing flagged), ``flag`` (write through
    with the ``injection:<shape>`` marks — the default for direct sources),
    ``quarantine`` (the write lands/re-routes pending with
    ``pending_reason='injection_quarantined'``) or ``drop`` (an audited
    refusal with no row — EM-705's purge is the only thing that may erase
    content; the add path may refuse to create it).

    ``policy`` is the ``(extracted, direct)`` pair the typed config's
    ``trust.injection_policy_extracted|_direct`` carries. ``None`` — and an
    unusable member inside the pair — keeps the card's own defaults, so the
    store, the CLI and the job readers all mean the same thing without any
    wiring: **extracted quarantine, direct flag**.
    """
    shapes = tuple(shape for shape in (shapes or ()) if shape)
    if not shapes:
        return "allow", None
    if policy is None:
        member_extracted, member_direct = "quarantine", "flag"
    else:
        try:
            raw_extracted, raw_direct = policy
        except (TypeError, ValueError):
            # A malformed pair fails open as a whole: two unusable members are
            # worth exactly the same write-decision as none at all.
            member_extracted = member_direct = "flag"
        else:
            member_extracted = _injection_member(raw_extracted)
            member_direct = _injection_member(raw_direct)
    action = member_extracted if source in EXTRACTED_SOURCES else member_direct
    if action == "quarantine":
        return "quarantine", "injection_quarantined"
    if action == "drop":
        return "drop", "injection_dropped"
    return "flag", None


def redact_for_prefetch(content: str, sensitivity: str) -> str:
    """Reduce sensitive content before prompt injection."""
    if sensitivity in ("sensitive", "secret"):
        # Keep short summary only
        one = content.strip().split("\n", 1)[0]
        if len(one) > 160:
            one = one[:157] + "..."
        return f"[sensitive] {one}"
    return content
