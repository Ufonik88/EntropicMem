"""The CI identity guard, and the one named exception it carries.

`scripts/check_commit_identity.sh` fails a push when any reachable commit is
authored or committed by a non-noreply address, because a personal email in
published history cannot be repaired without rewriting that history.

One commit already on `main` predates the guard reaching it: `14925b3`, a
worktree merge made by the kanban tooling under `kanban-kat@localhost`. It is
published, so it is **named** by full SHA rather than hidden by a pattern. These
tests keep that honest:

* the exception is by SHA only — a new commit with the same address still fails;
* the entry is still needed — if the commit disappears or its identity becomes
  acceptable, the test fails and the entry must be removed;
* the guard is green on this repository's history.

Fixtures use throwaway repositories with a scrubbed git environment, so the
developer's own config can never decide the result.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_commit_identity.sh"

#: The published commit the guard names. Keep in step with ALLOWED_SHAS.
EXEMPT_SHA = "14925b301995ee2640b4c61ec7c284582da54888"

#: The same rule the script applies (keep the two in step; a change to one that
#: the other does not see is the drift this pair exists to catch).
ALLOWED_RE = re.compile(
    r"(@users\.noreply\.github\.com$|^noreply@github\.com$|^noreply@anthropic\.com$)"
)

NOREPLY = "242751133+Ufonik88@users.noreply.github.com"
LOCAL_BOT = "kanban-kat@localhost"


def _env(email: str) -> dict:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test Author",
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": "Test Committer",
            "GIT_COMMITTER_EMAIL": email,
            # A hostile/real global config must not reach the fixture.
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return env


def _run(cwd, *args, email=NOREPLY, check=True):
    return subprocess.run(
        list(args),
        cwd=cwd,
        env=_env(email),
        capture_output=True,
        text=True,
        check=check,
    )


def _commit(repo: Path, name: str, email: str) -> str:
    (repo / f"{name}.txt").write_text(name, encoding="utf-8")
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-q", "-m", f"commit {name}", email=email)
    return _run(repo, "git", "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    _run(path, "git", "init", "-q", "-b", "main")
    _commit(path, "first", NOREPLY)
    return path


def _guard(cwd, rev_range: str):
    return subprocess.run(
        ["bash", str(SCRIPT), rev_range],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


# ── the rule ────────────────────────────────────────────────────────────────

def test_the_guard_passes_a_noreply_history(repo):
    result = _guard(repo, "HEAD")
    assert result.returncode == 0, result.stderr
    assert "identity-guard: OK" in result.stdout


def test_the_guard_fails_a_local_identity_and_names_it(repo):
    _commit(repo, "second", LOCAL_BOT)
    result = _guard(repo, "HEAD")
    assert result.returncode == 1
    assert "FAILED" in result.stderr
    assert LOCAL_BOT in result.stderr
    assert "author:" in result.stderr


def test_an_unresolvable_range_is_an_error_not_a_pass(repo):
    result = _guard(repo, "no-such-ref")
    assert result.returncode == 2
    assert "ERROR" in result.stderr


# ── the named exception ─────────────────────────────────────────────────────

def test_the_exception_is_by_sha_not_by_address(repo):
    """The allowlist names a commit; the same address still fails elsewhere."""
    _commit(repo, "second", LOCAL_BOT)
    assert _guard(repo, "HEAD").returncode == 1, (
        "a local-bot commit must fail: the exception is the SHA, not the address"
    )


def test_the_exception_is_still_needed():
    """If this fails, delete EXEMPT_SHA from ALLOWED_SHAS — and this test."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ae%n%ce", EXEMPT_SHA],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"allowlisted commit {EXEMPT_SHA} is no longer reachable: remove it from "
        "ALLOWED_SHAS in scripts/check_commit_identity.sh and from this test"
    )
    author, committer = result.stdout.strip().splitlines()
    for address in (author, committer):
        assert not ALLOWED_RE.search(address), (
            f"{address!r} is now an acceptable identity, so the exception is "
            "dead weight: remove it from ALLOWED_SHAS"
        )


def test_the_guard_source_still_carries_the_exception():
    """A silent removal would put main back in the red without a trace."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert EXEMPT_SHA in source
    assert "ALLOWED_SHAS" in source


def test_the_guard_is_green_on_this_repository():
    """End to end: the branch's own history passes the guard as CI runs it."""
    result = _guard(REPO, "HEAD")
    assert result.returncode == 0, result.stderr
