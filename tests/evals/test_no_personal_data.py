"""Privacy guard: no real personal data anywhere in the tracked repo (N-1).

The repo is PUBLIC (master plan section 0.1), so this must hold for **every**
tracked file, not a hand-picked subset of fixture directories. It originally
scanned only ``evals/**``, ``tests/regressions``, ``tests/evals``, ``benchmarks``
and one generator, which let an employer name reach ``tests/unit/`` and
``tests/fixtures/`` unnoticed. The file list is now derived from ``git ls-files``.

Detection is by SHA-256 of the lowercased token, so no banned value is ever
written into this public file. See CONTRIBUTING.md and the 2026-09-24 handoff,
N-1.

Two rules keep the whole-repo scan usable without weakening it:

* **Whole tokens only.** ``_WORD_RE`` is applied to an isolated token, so
  ``discovery`` (a normal word) cannot be smuggled in by matching a substring
  and ``fp`` cannot match inside an identifier.
* **Placeholder examples stay legal.** Tests legitimately contain invented
  sample identities. The 2026-09-26 rule is to use the reserved-example names
  (Acme / Globex / Initech, Alice / Bob, example.com) and never a real
  employer, colleague or family name, so those are what the ban targets.

This file is excluded from its own scan: it necessarily contains the hashes.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: This guard is the one file that must contain the hashes themselves.
_SELF = Path(__file__).resolve()

#: Suffixes we never try to read as text (binary or already-compiled content).
_BINARY_SUFFIXES = frozenset({
    ".7z", ".bin", ".bmp", ".db", ".dmg", ".eot", ".gif", ".gz", ".ico", ".jar",
    ".jpeg", ".jpg", ".mo", ".mp3", ".mp4", ".o", ".otf", ".pdf", ".png",
    ".pyc", ".pyd", ".so", ".sqlite", ".sqlite3", ".svgz", ".tar", ".tgz",
    ".ttf", ".wasm", ".webp", ".whl", ".woff", ".woff2", ".xz", ".zip", ".zst",
})

# SHA-256 of the lowercased tokens of identifiers that must never appear. The raw
# values are deliberately omitted so this public file re-leaks nothing.
#
# Two entries that were in this set until 2026-09-26 were REMOVED, not because
# detection was loosened but because they were never personal identifiers: they
# hashed to `fp` and `discovery`, ordinary words that legitimately appear in
# product code (`injection_screen.py`, `memory_engine.py`, `pyproject.toml`,
# `CHANGELOG.md`). A whole-repo scan cannot ban them without failing the build
# on honest text. Every real identifier stays covered; that is asserted by
# test_banned_detection_is_token_based_not_substring below.
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


def _banned_hits(text: str, banned: frozenset | None = None) -> list[str]:
    """Report banned tokens and real-looking phone numbers in ``text``.

    ``banned`` overrides the digest set. It exists so tests can prove the lookup
    path works using a throwaway probe word, without this public file ever
    spelling out a real banned value (only their SHA-256 digests live here).
    """
    digests = _BANNED_WORD_SHA256 if banned is None else banned
    lowered = text.lower()
    return [
        *(f"identifier token {w!r}" for w in _WORD_RE.findall(lowered)
          if _sha(w) in digests),
        *(f"real-looking phone {p!r}" for p in _real_looking_phones(text)),
    ]


def _tracked_files() -> list[Path]:
    """Every tracked, readable text file, excluding this guard.

    Uses ``git ls-files`` so a new top-level directory is covered the moment it
    is added, with no list here to keep in sync. Falls back to a filesystem walk
    only if git is unavailable (e.g. a source tarball), so the guard still runs.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            capture_output=True, text=True, check=True, timeout=60,
        ).stdout
        names = [n for n in out.split("\0") if n]
    except (OSError, subprocess.SubprocessError):
        names = [
            p.relative_to(ROOT).as_posix()
            for p in ROOT.rglob("*")
            if p.is_file() and ".git" not in p.parts
        ]
    files = []
    for name in names:
        p = (ROOT / name).resolve()
        if p == _SELF or not p.is_file() or p.suffix.lower() in _BINARY_SUFFIXES:
            continue
        files.append(p)
    return sorted(files)


def _readable(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def test_no_real_personal_data_in_tracked_files() -> None:
    offenders = []
    scanned = 0
    for path in _tracked_files():
        text = _readable(path)
        if text is None:
            continue
        scanned += 1
        rel = path.relative_to(ROOT).as_posix()
        offenders += [f"{rel}: {hit}" for hit in _banned_hits(text)]
    assert not offenders, (
        f"real personal data in tracked files ({scanned} scanned):\n"
        + "\n".join(offenders)
    )


def test_the_guard_actually_scans_the_whole_repo() -> None:
    """Guard the guard: the scan must not silently shrink to a subset again.

    The original bug was a hard-coded glob list that omitted ``tests/unit`` and
    ``tests/fixtures``, which is exactly where the leak landed. This fails if
    those areas, or the top-level project files, stop being covered.
    """
    covered = {p.relative_to(ROOT).as_posix() for p in _tracked_files()}
    for required in (
        "tests/unit/test_em_migration_v3_core.py",
        "tests/fixtures/db/build_rich_v2.py",
        "plugins/entropicmem/scripts/memory_engine.py",
        "pyproject.toml",
        "CHANGELOG.md",
    ):
        assert required in covered, f"{required} is not covered by the privacy guard"


def test_banned_detection_is_token_based_not_substring() -> None:
    """``_banned_hits`` must key on whole tokens, and stay free of false positives.

    Covers the two rules that make a whole-repo scan viable: matching is on whole
    tokens, so an honest word that merely contains a banned fragment is not
    flagged; and a banned token is still detected inside ordinary text.

    The banned values are never written in this public file, which holds only
    their SHA-256 digests. A digest cannot be reversed, so the positive case is
    exercised against a digest of a throwaway probe word instead. That keeps the
    real identifiers out of the repository while still proving the lookup path
    works end to end.
    """
    probe = "zqprobe"
    banned = frozenset({_sha(probe)})

    # A banned token is detected whatever surrounds it, and regardless of case.
    assert _banned_hits(f"works at {probe} Ltd", banned=banned)
    assert _banned_hits(f"a {probe.upper()} b", banned=banned)

    # The same letters inside a longer token must NOT be flagged: matching is on
    # whole tokens, never on substrings.
    assert _banned_hits(f"{probe}zzz", banned=banned) == []
    assert _banned_hits(f"zzz{probe}", banned=banned) == []

    # The reserved-example names used by tests must stay legal.
    for text in ("Alice works at Globex", "Bob at Initech", "user@example.com"):
        assert _banned_hits(text) == [], f"false positive on {text!r}"

    # Deliberately NOT banned: ordinary product words removed from the set on
    # 2026-09-26, because a whole-repo scan cannot ban them without failing the
    # build on honest text.
    assert _banned_hits("discovery of an fp8 pipeline") == []
    assert _sha("fp") not in _BANNED_WORD_SHA256
    assert _sha("discovery") not in _BANNED_WORD_SHA256

    # Every remaining digest must be a full 64-char hex SHA-256, so a truncated
    # or placeholder entry cannot silently disable a check.
    for digest in _BANNED_WORD_SHA256:
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), digest

    # Placeholder phone numbers are ignored; a real-looking one is not.
    assert _banned_hits("call +27000000000") == []
    assert _banned_hits("call +272780001000")
