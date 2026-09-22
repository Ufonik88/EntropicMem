"""
pii.py — PII detection and redaction for EntropicMem (Phase 9).

Detects: emails, phone numbers, ID numbers, API keys, passwords, IP addresses.
Modes: warn (report only), redact (replace with [REDACTED]), block (reject storage).

Write-time policy (the default of check_pii mode="redact"): only
high-confidence secret classes (api_key, password) are auto-redacted; every
other PII type is a warn-only finding so legitimate content is never
permanently destroyed at write time. Overlapping detections are
interval-merged and redaction splices in a single pass from the end, so
non-matched text is never dropped. check_pii findings never include raw
match text.

Stdlib-only. No external dependencies.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


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

# ── write-time redaction policy ──────────────────────────────────────────────
# Write-time redaction (check_pii mode="redact") is intentionally narrow: only
# high-confidence secret classes are destroyed, because a wrong guess is
# irreversible while a missed PII match stays recoverable (warn-only finding).
SECRET_TYPES = frozenset({"api_key", "password"})
# Confidence floor applied on top of the per-type policy.
AUTO_REDACT_MIN_CONFIDENCE = 0.8
# Constant value substituted for raw match text in check_pii findings.
MATCH_PLACEHOLDER = "[REDACTED]"


def _raw_findings(text: str) -> List[PIIFinding]:
    """All raw matches across the patterns, in pattern order (overlaps kept)."""
    findings: List[PIIFinding] = []
    for name, pattern, confidence in _COMPILED_PATTERNS:
        for m in pattern.finditer(text):
            findings.append(PIIFinding(
                pii_type=name,
                match=m.group(0),
                start=m.start(),
                end=m.end(),
                confidence=confidence,
            ))
    return findings


def _merge_spans(findings: Sequence[PIIFinding]) -> List[Tuple[int, int]]:
    """Interval-merge intersecting spans; returns sorted ``(start, end)`` pairs.

    Touching spans (end == next start) stay separate; anything intersecting,
    including strict containment in either direction, collapses to its union.
    """
    spans: List[List[int]] = []
    for f in sorted(findings, key=lambda x: (x.start, x.end)):
        if spans and f.start < spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], f.end)
        else:
            spans.append([f.start, f.end])
    return [(start, end) for start, end in spans]


def _represent(members: Sequence[PIIFinding], end: int, text: str) -> PIIFinding:
    """One finding for a merged cluster: secret classes beat raw confidence."""
    best = max(members, key=lambda m: (m.pii_type in SECRET_TYPES, m.confidence))
    start = members[0].start
    return PIIFinding(pii_type=best.pii_type, match=text[start:end],
                      start=start, end=end, confidence=best.confidence)


def _merge_findings(findings: Sequence[PIIFinding], text: str) -> List[PIIFinding]:
    """Interval-merge findings to at most one finding per overlapping cluster."""
    merged: List[PIIFinding] = []
    members: List[PIIFinding] = []
    end = -1
    for f in sorted(findings, key=lambda x: (x.start, x.end)):
        if members and f.start < end:
            members.append(f)
            end = max(end, f.end)
            continue
        if members:
            merged.append(_represent(members, end, text))
        members, end = [f], f.end
    if members:
        merged.append(_represent(members, end, text))
    return merged


def scan_pii(text: str) -> List[PIIFinding]:
    """
    Scan text for PII patterns. Returns findings sorted by position, with
    intersecting spans interval-merged so a nested match never survives on its
    own and downstream splices can never see stale offsets.
    """
    return _merge_findings(_raw_findings(text), text)


def redact_pii(text: str, replacement: str = "[REDACTED]",
               types: Optional[frozenset] = None,
               min_confidence: float = 0.0) -> str:
    """
    Replace detected PII with a replacement string. Returns the redacted text.

    ``types`` limits redaction to those pii_type names (None = every type) and
    ``min_confidence`` to findings at or above that confidence. Redaction works
    on raw spans, so a secret nested inside a larger match is still redacted.
    Selected spans are interval-merged and spliced in a single pass from the
    end: text outside the redacted spans is never dropped.
    """
    selected = [f for f in _raw_findings(text)
                if (types is None or f.pii_type in types)
                and f.confidence >= min_confidence]
    result = text
    for start, end in reversed(_merge_spans(selected)):
        result = result[:start] + replacement + result[end:]
    return result


def check_pii(text: str, mode: str = "warn",
              redact_types: Optional[frozenset] = SECRET_TYPES,
              min_confidence: float = AUTO_REDACT_MIN_CONFIDENCE) -> dict:
    """
    Check text for PII and act according to mode.

    Modes:
      - "warn": return findings, don't modify text
      - "redact": return text with auto-redactable findings replaced
      - "block": return blocked=True if any PII found

    Write-time policy (the default of mode="redact"): only high-confidence
    secret classes (``redact_types`` = ``SECRET_TYPES``: api_key, password) are
    auto-redacted; every other PII type is a warn-only finding whose text is
    preserved. Pass ``redact_types=None`` to redact all types (and lower
    ``min_confidence`` to include weak matches).

    Findings never contain raw match text -- only pii_type, offsets,
    confidence and the constant ``MATCH_PLACEHOLDER``.

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
            {"type": f.pii_type, "start": f.start, "end": f.end,
             "confidence": f.confidence, "match": MATCH_PLACEHOLDER}
            for f in findings
        ],
        "text": text,
        "blocked": False,
    }

    if has_pii:
        if mode == "redact":
            result["text"] = redact_pii(text, types=redact_types,
                                        min_confidence=min_confidence)
        elif mode == "block":
            result["blocked"] = True

    return result


def scan_fact_content(content: str, title: str = "", tags: str = "") -> List[PIIFinding]:
    """Scan a fact's content, title, and tags for PII."""
    combined = f"{title}\n{content}\n{tags}"
    return scan_pii(combined)
