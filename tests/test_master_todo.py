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
from typing import Optional

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
#: Decimal ids are allowed because sub-chunks exist (7.1, 7.2).
_CHUNK_ROWS = ("4", "5", "6", "7", "7.1", "7.2")

_CHUNK_ID = r"\d+(?:\.\d+)?"

#: The three pages that state the expected suite size, each by an anchor unique to it.
#: **Cross-file agreement only** — comparing against a live collection run would need a
#: nested pytest, which trades a silent drift for a flaky gate (and `--collect-only`
#: cannot see collection-time skips anyway, so the number would not match regardless).
_BASELINE_ANCHORS = (
    (REPO / "MASTER_TODO.md", "| Tests |"),
    (REPO / "docs" / "plan" / "NEXT_CHUNK.md", "**Baseline:**"),
    (REPO / "docs" / "plan" / "REMAINING_PLAN.md", "pre-flight. Expect"),
)

#: Both separators appear in the wild: `2061 passed / 3 skipped / 3 xfailed` in the
#: gates table, `2061 passed, 3 skipped, 3 xfailed` in the two pre-flight blocks.
_COUNT_RE = re.compile(r"(\d+)\s+passed\s*[/,]\s*(\d+)\s+skipped\s*[/,]\s*(\d+)\s+xfailed")

#: Below this the number was mis-typed, not mis-synced — same idea as the CLI drift
#: guard's `_SANITY_FLOOR`.
_COUNT_FLOOR = 1000


def _stated_baseline(path: Path, anchor: str) -> tuple:
    """The `(passed, skipped, xfailed)` triple one page states, or a loud failure."""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if anchor in ln]
    assert len(lines) == 1, (
        f"{path.name}: the anchor {anchor!r} matched {len(lines)} lines, expected exactly "
        "one. If the wording moved, move the anchor in `_BASELINE_ANCHORS` — do not drop "
        "the page from the check, that is how the drift this guard exists for returns."
    )
    match = _COUNT_RE.search(lines[0])
    assert match, f"{path.name}: the line anchored by {anchor!r} states no passed/skipped/xfailed triple"
    return tuple(int(group) for group in match.groups())


def _baseline_disagreement(stated: dict) -> Optional[str]:
    """``None`` when every page states the same triple, else a message naming them.

    A pure function on purpose. The docs agree today, so a test that only reads them
    never sees a violating input — and an assertion whose strength no input tests cannot
    be mutation-proven (weakening ``== 1`` to ``>= 1`` would slip through with the tree
    green). Separating the comparison lets the tests below feed it disagreement directly,
    which is what gives the doc-level check its teeth. Same lesson EM-304's tie-break test
    taught: a test that does not exercise the case proves nothing about it.
    """
    passed = {triple[0] for triple in stated.values()}
    if len(passed) > 1:
        return f"the docs disagree about the expected suite size: {stated}"
    if min(passed) < _COUNT_FLOOR:
        return f"implausible suite size (below {_COUNT_FLOOR}): {stated}"
    skipped = {triple[1] for triple in stated.values()}
    xfailed = {triple[2] for triple in stated.values()}
    if len(skipped) > 1 or len(xfailed) > 1:
        return (
            "the docs disagree about the skip/xfail pair, which is read as a pair with the "
            f"passed count (3 skips without the private digest list, 2 with it): {stated}"
        )
    return None


def test_the_stated_pre_flight_baseline_agrees_across_the_docs() -> None:
    """One number, three pages.

    Chunk 18's pre-flight said **1995** while `MASTER_TODO` and the actual run said
    **1998**: a stale number that reads exactly like a real mismatch, and the rule on
    mismatch is "stop and report", so a wrong page costs a full re-measure and invites
    the wrong conclusion ("assume the older number is right"). Nothing compared the
    pages, because the number is written by hand in all three.

    This asserts the three statements agree **with each other**. It deliberately does
    not compare them against a live collection: the suite's own pre-flight run is what
    checks them against reality, and this guard's job is to make sure that when the run
    disagrees, the pages cannot also disagree among themselves.
    """
    stated = {path.name: _stated_baseline(path, anchor) for path, anchor in _BASELINE_ANCHORS}
    assert _baseline_disagreement(stated) is None, _baseline_disagreement(stated)

    # Belt and braces, and knowingly redundant with the three synthetic tests below: a
    # guard that returned None for everything would pass the assertion above too, so the
    # real triples are fed a deliberate drift as well. Dropping *this* line does not
    # weaken the guard — the synthetic tests carry it, and a mutation of the comparison
    # itself is caught there — which is why it reads as a survived mutation rather than a
    # coverage hole.
    drifted = dict(stated)
    page = sorted(drifted)[0]
    drifted[page] = (drifted[page][0] - 1, *drifted[page][1:])
    assert _baseline_disagreement(drifted) is not None


def test_every_page_that_states_the_baseline_is_in_the_comparison() -> None:
    """Pinned by name, because dropping a page from `_BASELINE_ANCHORS` narrows the
    guard silently — `len(stated) == len(_BASELINE_ANCHORS)` is true either way."""
    assert {path.name for path, _ in _BASELINE_ANCHORS} == {
        "MASTER_TODO.md", "NEXT_CHUNK.md", "REMAINING_PLAN.md",
    }
    assert len(_BASELINE_ANCHORS) == 3
    # And each anchor must be specific to its own page: an anchor that matches in two
    # files is an anchor that will match the wrong line when one of them is reworded.
    for path, anchor in _BASELINE_ANCHORS:
        assert path.is_file(), f"{path.name} vanished; it states the pre-flight baseline"
        hits = [ln for ln in path.read_text(encoding="utf-8").splitlines() if anchor in ln]
        assert len(hits) == 1, f"{path.name}: anchor {anchor!r} matched {len(hits)} lines"


def test_the_comparison_rejects_a_drifted_passed_count() -> None:
    """The teeth, fed a violating input the repo cannot supply while it is consistent."""
    agreed = {"MASTER_TODO.md": (2061, 3, 3), "NEXT_CHUNK.md": (2061, 3, 3), "REMAINING_PLAN.md": (2061, 3, 3)}
    assert _baseline_disagreement(agreed) is None

    drifted = dict(agreed, **{"NEXT_CHUNK.md": (1995, 3, 3)})
    assert "disagree" in (_baseline_disagreement(drifted) or "")


def test_the_comparison_rejects_a_drifted_skip_or_xfail_pair() -> None:
    """The skip count is read as a *pair* with the passed count (3 without the private
    digest list, 2 with it), so a one-sided drift is a disagreement, not a variant."""
    assert "skip/xfail pair" in (_baseline_disagreement(
        {"a": (2061, 3, 3), "b": (2061, 2, 3)}) or "")
    assert "skip/xfail pair" in (_baseline_disagreement(
        {"a": (2061, 3, 3), "b": (2061, 3, 4)}) or "")


def test_the_comparison_rejects_an_implausible_size() -> None:
    """A mis-typed 206 in all three pages agrees with itself; the floor catches it."""
    assert "implausible" in (_baseline_disagreement({"a": (206, 3, 3), "b": (206, 3, 3)}) or "")


def _table_rows(text: str) -> dict[str, str]:
    """Map ``| 5 | ... |`` rows to their full text, keyed by the row number."""
    rows: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(rf"^\|\s*({_CHUNK_ID})\s*\|", line)
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

    # Which chunk numbers does In flight admit are unmerged? Decimal ids count,
    # because sub-chunks are real (7.1 landed, 7.2 did not).
    pending = set(re.findall(rf"[Cc]hunk\s*({_CHUNK_ID})", inflight))
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
