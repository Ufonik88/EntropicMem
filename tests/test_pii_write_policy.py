"""PII span-merging, write-time redaction policy and findings sanitisation.

Covers the three pii.py fixes: (a) interval merging replaces the broken
overlap check so nested spans cannot cause stale-offset splices that drop
text; (b) write-time redaction (check_pii mode="redact") auto-redacts only
high-confidence secret classes and leaves other PII types warn-only;
(c) check_pii findings carry pii_type, offsets, confidence and a constant
placeholder — never raw match text.
"""
from __future__ import annotations

import json

from pii import (
    AUTO_REDACT_MIN_CONFIDENCE,
    MATCH_PLACEHOLDER,
    SECRET_TYPES,
    check_pii,
    redact_pii,
    scan_pii,
)


def _api_token() -> str:
    """api_key-shaped test token, assembled at runtime."""
    return "sk-" + "A" * 12 + "B" * 12 + "C" * 5


def _assert_disjoint(findings):
    spans = sorted((f.start, f.end) for f in findings)
    for (_, end), (start, _) in zip(spans, spans[1:]):
        assert end <= start, f"overlapping findings survived: {spans}"


# ── (a) interval merging / no dropped text ──────────────────────────────────

def test_nested_spans_merge_and_tail_survives():
    secret = _api_token()
    text = "password=" + secret + ".txt end"
    findings = scan_pii(text)
    _assert_disjoint(findings)
    assert len(findings) == 1, "strictly nested spans must merge into one finding"
    f = findings[0]
    assert (f.start, f.end) == (0, len("password=" + secret + ".txt"))
    assert redact_pii(text) == "[REDACTED] end", "trailing text must never be dropped"


def test_containment_cluster_reports_secret_class():
    text = "password=" + "hunter2" + "secret@x.com more"
    findings = scan_pii(text)
    _assert_disjoint(findings)
    assert len(findings) == 1
    assert findings[0].pii_type == "password", "secret class must win the merged span"
    assert redact_pii(text) == "[REDACTED] more"


def test_redact_all_types_preserves_unmatched_text():
    text = "server at 192.168.1.100, invoice 1234567890123 tail"
    out = redact_pii(text)
    assert out.startswith("server at ")
    assert out.endswith(" tail")
    assert out.count("[REDACTED]") == 2


def test_spans_disjoint_on_mixed_input():
    text = ("contact a@b.co or 0821234567 from 10.0.0.8 using " + _api_token()
            + " with password=" + _api_token() + ".txt end")
    _assert_disjoint(scan_pii(text))
    out = redact_pii(text)
    assert out.endswith(" end")
    assert "a@b.co" not in out


# ── (b) write-time policy: secrets redacted, other PII warn-only ────────────

def test_check_pii_redact_policy_leaves_low_confidence_pii():
    text = "server at 192.168.1.100, invoice 1234567890123"
    result = check_pii(text, mode="redact")
    assert result["has_pii"] is True
    assert result["text"] == text, "low-confidence PII types must be warn-only at write time"
    assert all(f["type"] not in SECRET_TYPES for f in result["findings"])


def test_check_pii_redact_destroys_secret_classes():
    secret_line = "password=" + _api_token()
    result = check_pii("note " + secret_line + " kept tail", mode="redact")
    assert secret_line not in result["text"]
    assert result["text"].endswith(" kept tail")

    key_result = check_pii("key " + _api_token() + " end", mode="redact")
    assert _api_token() not in key_result["text"]
    assert key_result["text"].endswith(" end")


def test_check_pii_email_warn_only_by_default():
    result = check_pii("my email is test@test.com", mode="redact")
    assert result["has_pii"] is True
    assert "test@test.com" in result["text"], "email is warn-only under the write-time policy"


def test_check_pii_override_redacts_all_types():
    result = check_pii("my email is test@test.com", mode="redact",
                       redact_types=None, min_confidence=0.0)
    assert "test@test.com" not in result["text"]
    assert result["text"] == "my email is [REDACTED]"


def test_check_pii_min_confidence_floor():
    text = "server at 192.168.1.100"
    result = check_pii(text, mode="redact", redact_types=None, min_confidence=0.6)
    assert "192.168.1.100" in result["text"], "0.5-confidence ip must not clear a 0.6 floor"
    assert AUTO_REDACT_MIN_CONFIDENCE >= 0.8


def test_check_pii_warn_mode_never_modifies():
    text = "password=" + _api_token()
    result = check_pii(text, mode="warn")
    assert result["text"] == text


# ── (c) findings never contain raw match text ───────────────────────────────

def test_check_pii_findings_sanitized():
    secret = _api_token()
    result = check_pii("password=" + secret + " end", mode="warn")
    assert result["findings"], "expected findings"
    dumped = json.dumps(result["findings"])
    assert secret not in dumped
    assert "password=" not in dumped
    for f in result["findings"]:
        assert set(f) == {"type", "start", "end", "confidence", "match"}
        assert f["match"] == MATCH_PLACEHOLDER
        assert isinstance(f["start"], int) and isinstance(f["end"], int)
        assert 0.0 <= f["confidence"] <= 1.0


def test_check_pii_findings_offsets_are_accurate():
    text = "reach me at test@test.com please"
    result = check_pii(text, mode="warn")
    (f,) = [x for x in result["findings"] if x["type"] == "email"]
    assert text[f["start"]:f["end"]] == "test@test.com"
