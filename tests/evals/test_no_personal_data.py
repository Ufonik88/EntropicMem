"""Privacy guard: no real personal data in the public eval fixtures (N-1).

The repo is public (master plan section 0.1) and every eval fixture must be
synthetic. This fails if real personal identifiers -- names, a live contact
number, an employer, financial account names, or similar -- reappear in the eval
fixtures or their generators. Detection is by SHA-256 so the raw values are never
stored in this public file. See CONTRIBUTING.md and the 2026-09-24 handoff, N-1.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_GLOBS = (
    "evals/**/*.jsonl",
    "evals/**/*.json",
    "tests/regressions/*.py",
    "tests/evals/*.py",
    "benchmarks/*.py",
)
FIXTURE_FILES = sorted({p for g in _FIXTURE_GLOBS for p in ROOT.glob(g)})
FIXTURE_FILES.append(ROOT / "gen_hard_scenarios.py")

# SHA-256 of the lowercased tokens of identifiers that must never appear. The raw
# values are deliberately omitted so this public file re-leaks nothing.
_BANNED_WORD_SHA256 = frozenset({
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000000",
})

# A phone number is treated as real-looking unless its digits are a clear placeholder.
_FAKE_RUNS = ("0000", "1234", "9876", "5432")
_PHONE_RE = re.compile(r"\+27(?:[\s-]?\d){9,12}")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _sha(token: str) -> str:
    return hashlib.sha256(token.strip().lower().encode()).hexdigest()


def _real_looking_phones(text: str) -> list[str]:
    return [
        m.group()
        for m in _PHONE_RE.finditer(text)
        if all(run not in re.sub(r"\D", "", m.group()) for run in _FAKE_RUNS)
    ]


def _banned_hits(text: str) -> list[str]:
    lowered = text.lower()
    return [
        *(f"identifier token {w!r}" for w in _WORD_RE.findall(lowered)
          if _sha(w) in _BANNED_WORD_SHA256),
        *(f"real-looking phone {p!r}" for p in _real_looking_phones(text)),
    ]


def test_no_real_personal_data_in_fixtures() -> None:
    offenders = [
        f"{path.name}: {hit}"
        for path in FIXTURE_FILES
        for hit in _banned_hits(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, "real personal data in public fixtures:\n" + "\n".join(offenders)
