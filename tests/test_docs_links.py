"""Every relative link in the repo's Markdown resolves to a committed file.

Docs are the map of this repo; a link to a file that was renamed, removed or
never committed is invisible until someone clicks it. CI checks out tracked
files only, so a link to a local-only file breaks there and not on the author's
disk — the same trap as an untracked fixture. `docs/BACKFILL_PROCEDURE.md`
pointed at an internal design doc that is deliberately not in this repo; that is
now prose, and this test keeps the next one from landing.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

ROOT_DOCS = ("README.md", "CONTRIBUTING.md", "AGENTS.md", "SETUP.md")
DOCS = (
    sorted(REPO.glob("docs/**/*.md"))
    + sorted(REPO.glob("skills/**/*.md"))
    + [REPO / name for name in ROOT_DOCS]
)

_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_OFFSITE = ("http://", "https://", "mailto:", "#")


def _relative_targets(text: str) -> list[str]:
    targets = []
    for match in _LINK.finditer(text):
        target = match.group(1)
        if target.startswith(_OFFSITE):
            continue
        targets.append(target.split("#", 1)[0] or target)
    return targets


def _is_tracked(path: Path) -> bool:
    """True when git knows the file, i.e. when CI will have it."""
    try:
        relative = path.relative_to(REPO)
    except ValueError:  # a link pointing outside the repo: existence is enough
        return True
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(relative)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


@pytest.mark.parametrize("doc", DOCS, ids=lambda path: str(path.relative_to(REPO)))
def test_relative_links_resolve_to_committed_files(doc: Path) -> None:
    assert doc.is_file(), f"{doc} vanished; update this test's file list"
    broken = []
    for target in _relative_targets(doc.read_text(encoding="utf-8")):
        resolved = (doc.parent / target).resolve()
        if not resolved.exists():
            broken.append(f"{target} (no such file)")
        elif resolved.is_file() and not _is_tracked(resolved):
            broken.append(f"{target} (exists on disk but is not committed)")
    assert not broken, f"{doc.relative_to(REPO)}: broken link(s): {broken}"
