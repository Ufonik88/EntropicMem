"""
pii.py — PII detection and redaction for EntropicMem (Phase 9).

Detects: emails, phone numbers, ID numbers, API keys, passwords, IP addresses.
Modes: warn (report only), redact (replace with [REDACTED]), block (reject storage).

Stdlib-only. No external dependencies.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PIIFinding:
    """A single PII detection in text."""
    pii_type: str
    match: str
    start: int
    end: int
    confidence: float = 1.0


# ── detection patterns ──────────────────────────────────────────────────────

_PII_PATTERNS: List[tuple] = [
    # (name, regex, confidence)
    ("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", 0.95),
    ("phone", r"\b(?:\+?27|0)[6-8][0-9]{8}\b", 0.85),  # South African format
    ("phone_intl", r"\b\+?[1-9]\d{1,2}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b", 0.7),
    ("id_number", r"\b\d{13}\b", 0.6),  # SA ID number (13 digits)
    ("api_key", r"\b(?:sk|pk|api|key|token)[_-][A-Za-z0-9]{20,}\b", 0.9),
    ("password", r"(?:password|passwd|pwd|secret)\s*[=:]\s*\S+", 0.85),
    ("ip_address", r"\b(?:\d{1,3}\.){3}\d{1,3}\b", 0.5),
    ("credit_card", r"\b(?:\d[ -]*?){13,16}\b", 0.6),
]

# Compile patterns once
_COMPILED_PATTERNS = [(name, re.compile(pattern, re.IGNORECASE), conf)
                      for name, pattern, conf in _PII_PATTERNS]


def scan_pii(text: str) -> List[PIIFinding]:
    """
    Scan text for PII patterns. Returns list of findings sorted by position.
    """
    findings: List[PIIFinding] = []
    seen_spans: set = set()

    for name, pattern, confidence in _COMPILED_PATTERNS:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            # Skip overlapping matches (keep first/highest confidence)
            if any(s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1] for s in seen_spans):
                continue
            seen_spans.add(span)
            findings.append(PIIFinding(
                pii_type=name,
                match=m.group(0),
                start=m.start(),
                end=m.end(),
                confidence=confidence,
            ))

    findings.sort(key=lambda f: f.start)
    return findings


def redact_pii(text: str, replacement: str = "[REDACTED]") -> str:
    """
    Replace all detected PII with a replacement string.
    Returns the redacted text.
    """
    findings = scan_pii(text)
    if not findings:
        return text

    # Process in reverse order to preserve positions
    result = text
    for finding in reversed(findings):
        result = result[:finding.start] + replacement + result[finding.end:]
    return result


def check_pii(text: str, mode: str = "warn") -> dict:
    """
    Check text for PII and act according to mode.

    Modes:
      - "warn": return findings, don't modify text
      - "redact": return redacted text
      - "block": return blocked=True if any PII found

    Returns:
      {
        "has_pii": bool,
        "findings": [...],
        "text": str (original or redacted),
        "blocked": bool,
      }
    """
    findings = scan_pii(text)
    has_pii = len(findings) > 0

    result = {
        "has_pii": has_pii,
        "findings": [
            {"type": f.pii_type, "match": f.match[:20] + "..." if len(f.match) > 20 else f.match,
             "confidence": f.confidence}
            for f in findings
        ],
        "text": text,
        "blocked": False,
    }

    if has_pii:
        if mode == "redact":
            result["text"] = redact_pii(text)
        elif mode == "block":
            result["blocked"] = True

    return result


def scan_fact_content(content: str, title: str = "", tags: str = "") -> List[PIIFinding]:
    """Scan a fact's content, title, and tags for PII."""
    combined = f"{title}\n{content}\n{tags}"
    return scan_pii(combined)
