"""Write policy + sensitivity tiers for EntropicMem (Phase 2 security)."""

from __future__ import annotations

import re
from typing import Optional, Tuple

SENSITIVITY_LEVELS = ("public", "internal", "sensitive", "secret")

# Domains default tier
DOMAIN_DEFAULT_TIER = {
    "Finance": "sensitive",
    "People": "sensitive",
    "Wedding": "sensitive",
    "Infrastructure": "internal",
    "Ajax Systems": "internal",
    "Projects": "internal",
    "Knowledge": "internal",
    "X-Growth": "internal",
    "Workflows": "internal",
    "Products-Research": "internal",
    "Rules": "internal",
    "Test": "public",
}

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(sk|pk)[_-][A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|secret[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"(?i)-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----"),
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
        return "block", "secret_or_credential_pattern — use VaultKnox, not EntropicMem"
    # Auto-extract never lands directly in durable facts
    if source in ("auto_extracted", "auto_extract"):
        return "quarantine", "auto_extracted_requires_promotion"
    if source in ("promoted", "pending_promoted"):
        return "allow", None
    if domain in ("Finance", "People") and source in ("auto_extracted", "conversation"):
        return "quarantine", "sensitive_domain_needs_explicit_remember"
    return "allow", None


def redact_for_prefetch(content: str, sensitivity: str) -> str:
    """Reduce sensitive content before prompt injection."""
    if sensitivity in ("sensitive", "secret"):
        # Keep short summary only
        one = content.strip().split("\n", 1)[0]
        if len(one) > 160:
            one = one[:157] + "..."
        return f"[sensitive] {one}"
    return content
