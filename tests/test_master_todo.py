"""`MASTER_TODO.md` exists, is linked, and can be trusted.

The document-control rule in `AGENTS.md` is only as good as the file it keeps
honest. An agent that starts a session at a stale `MASTER_TODO.md` cannot know
what is in flight, and an agent that finishes without updating it leaves the next
one to reconstruct history. That is exactly the failure this repo already hit
between chunks, when the plan referenced a `MASTER_TODO` that existed only in one
agent's memory and could not be read by the next.

So the rule is pinned here rather than left to good intentions:

* the file exists, is substantial, and carries its required sections;
* `AGENTS.md` and `README.md` both link it, so it is reachable from the two
  places an agent is guaranteed to read;
* the SHA it records as reconciled against is a **real ancestor** of this branch,
  which is what stops it claiming a state that never existed.

This is a documentation guard, in the same family as `tests/test_docs_links.py`
and `tests/test_cli_reference_drift.py`. It asserts nothing about product
behaviour.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MASTER = REPO / "MASTER_TODO.md"

#: Sections that must survive edits. Each one is a question the next agent asks.
REQUIRED_SECTIONS = (
    "The document-control rule",
    "Where we are",
    "What is done",
    "What is next",
    "Gates that must be green",
    "Open blockers",
)

#: The two files every agent reads, plus the README a human reads.
MUST_LINK = ("AGENTS.md", "README.md")

#: "Last reconciled: <date>, against branch `<branch>` at `<sha>`."
_RECONCILED = re.compile(
    r"Last reconciled:\*\*\s*(?P<when>[^*]+?),\s*against branch\s*`(?P<branch>[^`]+)`\s*at\s*\s*`(?P<sha>[0-9a-f]{7,40})`"
)


def test_master_todo_exists_and_is_not_a_stub() -> None:
    assert MASTER.is_file(), (
        f"{MASTER.name} is missing. It is the canonical status page: where the "
        "project is, what is in flight, what is next, and the gates. Without it "
        "the next agent starts by guessing."
    )
    assert len(MASTER.read_text(encoding="utf-8").splitlines()) > 60, (
        f"{MASTER.name} is too short to carry real state. It is a summary that "
        "links to the detail, not a stub."
    )


def test_master_todo_carries_every_required_section() -> None:
    text = MASTER.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    assert not missing, f"{MASTER.name} is missing required sections: {missing}"


def test_master_todo_is_linked_from_the_docs_every_agent_reads() -> None:
    """A bare filename is not a link; a reader needs somewhere to click.

    `AGENTS.md` is the file every agent is instructed to read first, so a plain
    mention there would leave a reader with nothing to open. Both entry points
    must carry a real relative Markdown link.
    """
    wanted = "(MASTER_TODO.md)"
    for name in MUST_LINK:
        source = REPO / name
        assert source.is_file(), f"{name} vanished; it is one of the two entry points"
        assert wanted in source.read_text(encoding="utf-8"), (
            f"{name} does not link to MASTER_TODO.md. An agent reading only "
            f"{name} would never find the status page."
        )


def test_master_todo_records_a_sha_that_is_a_real_ancestor() -> None:
    """The recorded SHA must exist, or the file describes a state that never was."""
    text = MASTER.read_text(encoding="utf-8")
    match = _RECONCILED.search(text)
    assert match, (
        f"{MASTER.name} must say when it was last reconciled and against which "
        "commit, in the form: '**Last reconciled:** <date>, against branch "
        "`<branch>` at `<sha>`.'"
    )
    sha = match.group("sha")

    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=REPO,
        capture_output=True,
    )
    assert probe.returncode == 0, (
        f"{MASTER.name} records {sha} as the commit it was reconciled against, "
        "but that commit is not in this repository. A SHA that does not exist "
        "makes the whole file unfalsifiable."
    )

    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
        cwd=REPO,
        capture_output=True,
    )
    assert ancestor.returncode == 0, (
        f"{MASTER.name} records {sha}, which exists but is not an ancestor of "
        "HEAD. The status page must describe history this branch actually has."
    )


#: Chunk numbers whose table row is checked for the merged/unmerged claim.
_CHUNK_ROWS = ("4", "5", "6", "7")


def _table_rows(text: str) -> dict[str, str]:
    """Map ``| 5 | ... |`` rows to their full text, keyed by the row number."""
    rows: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\|\s*(\d+)\s*\|", line)
        if match:
            rows.setdefault(match.group(1), line)
    return rows


def test_master_todo_does_not_overstate_a_commit_as_merged() -> None:
    """Guard the honesty rule AGENTS.md states: committed is not merged.

    The status page carries a per-chunk table saying what is done, and a
    separate In flight section. If a chunk is admitted unmerged in one place and
    reported as plain "Done" in the other, the next agent reads the table, sees
    Done, and skips a merge that never happened. The table row must repeat the
    caveat.

    Stays quiet in the normal state: the check only runs when the In flight
    section actually admits unmerged work.
    """
    text = MASTER.read_text(encoding="utf-8")
    if "### In flight" not in text:
        return
    inflight = text.split("### In flight", 1)[1].split("\n## ", 1)[0]
    if not re.search(r"not merged|unpushed|no CI has run", inflight, re.IGNORECASE):
        return

    # Which chunk numbers does In flight admit are unmerged?
    pending = set(re.findall(r"Chunk\s*(\d+)", inflight))
    assert pending, (
        "the In flight section says work is unmerged but names no chunk number, "
        "so the chunk table cannot be checked against it"
    )

    rows = _table_rows(text)
    for number in sorted(pending):
        row = rows.get(number)
        assert row is not None, (
            f"chunk {number} is in flight but has no row in the status table"
        )
        if re.search(r"\*\*Done\*\*", row):
            assert re.search(r"not merged|committed,|unmerged", row, re.IGNORECASE), (
                f"the chunk {number} row claims Done while In flight says it is "
                "unmerged. Write 'Done (committed, not merged)'."
            )
