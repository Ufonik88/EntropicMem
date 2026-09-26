"""Privacy guard: no real personal data anywhere in the tracked repo (N-1).

The repo is PUBLIC, so this must hold for **every** tracked file, including
binary fixture databases. The file list comes from ``git ls-files``; it once was
a hand-picked glob list, which let an employer name reach ``tests/unit/`` and
``tests/fixtures/`` unnoticed.

The identifiers to ban are PRIVATE and are never stored in this repository,
**not even hashed**: an unsalted hash of a short word (a name, a company, a
bank) is reversed in seconds with a word list, so a public hash list republishes
exactly what it is meant to protect. The list lives outside the repo, as
SHA-256 digests of the lowercased tokens (one per line or comma separated):

* CI: the ``ENTROPICMEM_PRIVACY_DIGESTS`` Actions secret;
* locally: the same environment variable, a file named by
  ``ENTROPICMEM_PRIVACY_DIGESTS_FILE``, or ``~/.config/entropicmem/privacy-digests.txt``.

Without a list the identifier scan SKIPS, unless
``ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1``. CI sets that wherever secrets exist
(pushes and same-repo pull requests), and then a missing list FAILS, so the
guard cannot pass vacuously where it matters.

Failure messages give the file, the line and the entry's position in the
private list, never the matched word: CI logs of a public repo are public.

Placeholder identities stay legal and are what tests must use: Acme / Globex /
Initech, Alice / Bob, example.com, +1 555 01xx.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SELF = Path(__file__).resolve()

ENV_DIGESTS = "ENTROPICMEM_PRIVACY_DIGESTS"
ENV_DIGESTS_FILE = "ENTROPICMEM_PRIVACY_DIGESTS_FILE"
ENV_REQUIRE = "ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS"
DEFAULT_DIGESTS_FILE = Path("~/.config/entropicmem/privacy-digests.txt")

#: Scanned as raw bytes: SQLite pages hold row text verbatim.
_DB_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})

#: Never read (binary or compiled content that cannot hold fixture text).
_SKIP_SUFFIXES = frozenset({
    ".7z", ".bin", ".bmp", ".dmg", ".eot", ".gif", ".gz", ".ico", ".jar",
    ".jpeg", ".jpg", ".mo", ".mp3", ".mp4", ".o", ".otf", ".pdf", ".png",
    ".pyc", ".pyd", ".so", ".svgz", ".tar", ".tgz", ".ttf", ".wasm", ".webp",
    ".whl", ".woff", ".woff2", ".xz", ".zip", ".zst",
})

_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_WORD_RE = re.compile(r"[a-z0-9]+")

# A +27 phone number is real-looking unless its digits are a clear placeholder.
_FAKE_RUNS = ("0000", "1234", "9876", "5432")
_PHONE_RE = re.compile(r"\+27(?:[\s-]?\d){9,12}")


def _sha(token: str) -> str:
    return hashlib.sha256(token.strip().lower().encode()).hexdigest()


# ── private digest list ─────────────────────────────────────────────────────

def parse_digests(text: str) -> tuple[str, ...]:
    """Digests from ``text`` (whitespace/comma separated), in order.

    Any entry that is not a 64-char hex SHA-256 raises ValueError: a mistyped
    secret must fail loudly, never silently shrink the ban list.
    """
    entries = [e for e in re.split(r"[\s,]+", text.strip().lower()) if e]
    bad = [i + 1 for i, e in enumerate(entries) if not _DIGEST_RE.fullmatch(e)]
    if bad:
        raise ValueError(f"privacy digest list: entries {bad} are not SHA-256 hex digests")
    return tuple(dict.fromkeys(entries))


def load_digests(env: Optional[dict] = None) -> Optional[tuple[str, ...]]:
    """The private digest list, or None if none is configured anywhere."""
    env = os.environ if env is None else env
    if env.get(ENV_DIGESTS, "").strip():
        return parse_digests(env[ENV_DIGESTS])
    path = Path(env.get(ENV_DIGESTS_FILE) or DEFAULT_DIGESTS_FILE).expanduser()
    if path.is_file():
        digests = parse_digests(path.read_text(encoding="utf-8"))
        return digests or None
    return None


# ── scanning ────────────────────────────────────────────────────────────────

def _tracked_files() -> list[Path]:
    """Every tracked file worth reading (text and DB fixtures), excluding this guard."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            capture_output=True, text=True, check=True, timeout=60,
        ).stdout
        names = [n for n in out.split("\0") if n]
    except (OSError, subprocess.SubprocessError):
        names = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                 if p.is_file() and ".git" not in p.parts]
    files = []
    for name in names:
        p = (ROOT / name).resolve()
        if p == _SELF or not p.is_file() or p.suffix.lower() in _SKIP_SUFFIXES:
            continue
        files.append(p)
    return sorted(files)


def _file_lines(path: Path) -> Optional[list[str]]:
    """Lines of a text file, or the whole byte content (latin-1) of a DB file."""
    if path.suffix.lower() in _DB_SUFFIXES:
        return [path.read_bytes().decode("latin-1")]
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return None


def identifier_hits(lines: Iterable[str], digests: Sequence[str]) -> list[str]:
    """``line N: private denylist entry #K`` per banned token. Never the token itself."""
    index = {d: i + 1 for i, d in enumerate(digests)}
    hits = []
    for lineno, line in enumerate(lines, 1):
        for word in set(_WORD_RE.findall(line.lower())):
            k = index.get(_sha(word))
            if k:
                hits.append(f"line {lineno}: private denylist entry #{k}")
    return hits


def phone_hits(lines: Iterable[str]) -> list[str]:
    return [
        f"line {lineno}: real-looking phone number"
        for lineno, line in enumerate(lines, 1)
        for m in _PHONE_RE.finditer(line)
        if all(run not in re.sub(r"\D", "", m.group()) for run in _FAKE_RUNS)
    ]


def _scan(check) -> tuple[int, list[str]]:
    offenders, scanned = [], 0
    for path in _tracked_files():
        lines = _file_lines(path)
        if lines is None:
            continue
        scanned += 1
        rel = path.relative_to(ROOT).as_posix()
        offenders += [f"{rel}: {hit}" for hit in check(lines)]
    return scanned, offenders


# ── tests ───────────────────────────────────────────────────────────────────

def test_no_private_identifiers_in_tracked_files() -> None:
    digests = load_digests()
    if not digests:
        if os.environ.get(ENV_REQUIRE) == "1":
            pytest.fail(f"{ENV_REQUIRE}=1 but no private digest list is configured "
                        f"({ENV_DIGESTS} secret / {ENV_DIGESTS_FILE} / {DEFAULT_DIGESTS_FILE})")
        pytest.skip("private digest list not configured on this machine")
    scanned, offenders = _scan(lambda lines: identifier_hits(lines, digests))
    assert not offenders, (
        f"private identifiers in tracked files ({scanned} scanned):\n" + "\n".join(offenders))


def test_no_real_looking_phone_numbers_in_tracked_files() -> None:
    scanned, offenders = _scan(phone_hits)
    assert scanned > 100
    assert not offenders, "real-looking phone numbers:\n" + "\n".join(offenders)


def test_the_guard_scans_the_whole_repo_including_fixture_dbs() -> None:
    """The scan must not silently shrink to a subset again."""
    covered = {p.relative_to(ROOT).as_posix() for p in _tracked_files()}
    for required in (
        "tests/unit/test_em_migration_v3_core.py",
        "tests/fixtures/db/build_rich_v2.py",
        "tests/fixtures/db/v2_7_0.db",
        "plugins/entropicmem/scripts/memory_engine.py",
        "pyproject.toml",
        "CHANGELOG.md",
    ):
        assert required in covered, f"{required} is not covered by the privacy guard"


def test_no_digest_lists_are_committed() -> None:
    """Never publish identifiers, not even hashed (hashes of short words are reversible)."""
    for rel in ("tests/evals/test_no_personal_data.py", "tests/test_extraction_hygiene.py"):
        assert not _DIGEST_RE.search((ROOT / rel).read_text(encoding="utf-8")), rel
    digests = load_digests()
    if digests:
        _, leaked = _scan(lambda lines: [
            f"line {n}: private digest #{k} committed verbatim"
            for n, line in enumerate(lines, 1)
            for k, d in enumerate(digests, 1) if d in line.lower()])
        assert not leaked, "\n".join(leaked)


def test_detection_is_token_based_and_never_prints_the_word(tmp_path) -> None:
    probe = "zqprobe"
    digests = (_sha("unrelated"), _sha(probe))

    hits = identifier_hits([f"works at {probe.upper()} Ltd"], digests)
    assert hits == ["line 1: private denylist entry #2"]
    assert probe not in " ".join(hits).lower()
    assert identifier_hits([f"{probe}zzz zzz{probe}"], digests) == []
    for text in ("Alice works at Globex", "Bob at Initech", "user@example.com"):
        assert identifier_hits([text], digests) == []

    # Text stored inside an SQLite fixture is found through the byte scan.
    db = tmp_path / "fixture.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE facts (content TEXT)")
    conn.execute("INSERT INTO facts VALUES (?)", (f"Alice works at {probe}",))
    conn.commit()
    conn.close()
    assert identifier_hits(_file_lines(db), digests) == ["line 1: private denylist entry #2"]


def test_digest_list_loading(tmp_path) -> None:
    d1, d2 = _sha("one"), _sha("two")
    assert load_digests({ENV_DIGESTS: f"{d1},\n {d2.upper()}\n{d1}"}) == (d1, d2)
    with pytest.raises(ValueError):
        load_digests({ENV_DIGESTS: f"{d1} not-a-digest"})
    f = tmp_path / "digests.txt"
    f.write_text(f"{d2}\n", encoding="utf-8")
    assert load_digests({ENV_DIGESTS_FILE: str(f)}) == (d2,)
    assert load_digests({ENV_DIGESTS_FILE: str(tmp_path / "missing.txt")}) is None


def test_phone_rule() -> None:
    assert phone_hits(["call +27000000000"]) == []
    assert phone_hits(["call +272780001000"]) == ["line 1: real-looking phone number"]
