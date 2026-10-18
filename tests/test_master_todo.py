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

import pytest

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

#: The canonical source of the expected suite size. **One file, one number.**
#: The three plan pages used to each hand-copy the triple, and three hand-copied
#: numbers mean three edits per chunk and a silent one-page drift whenever one is
#: missed — which is exactly what happened, repeatedly (chunk 18's pre-flight said
#: 1995 while the other two pages and the actual run said 1998; and on 2026-10-17
#: `cb88d47` went red on all four legs because `MASTER_TODO.md` said 2755/4/3 while
#: the other two said 2756/4/3 — a doc-only failure that cost a full re-run). So the
#: pages now *reference* the source and state no figure of their own, and this guard
#: checks the reference rather than the arithmetic.
_BASELINE_PAGE = REPO / "docs" / "plan" / "BASELINE.md"

#: The three pages that must point at it, each by an anchor unique to it.
_BASELINE_REFS = (
    (REPO / "MASTER_TODO.md", "| Tests |"),
    (REPO / "docs" / "plan" / "NEXT_CHUNK.md", "**Baseline:**"),
    (REPO / "docs" / "plan" / "REMAINING_PLAN.md", "pre-flight. Expect"),
)

#: The source's figure-of-record row — CI's 3.12 leg, the one a pre-flight is
#: checked against. The marker is what makes the triple findable in a page that
#: also quotes the three *local* readings a few rows below.
_FIGURE_OF_RECORD = "figure of record"

#: Both separators appear in the wild: `2061 passed / 3 skipped / 3 xfailed` in the
#: gates table, `2061 passed, 3 skipped, 3 xfailed` in the pre-flight blocks.
_COUNT_RE = re.compile(r"(\d+)\s+passed\s*[/,]\s*(\d+)\s+skipped\s*[/,]\s*(\d+)\s+xfailed")

#: Below this the number was mis-typed, not mis-synced — same idea as the CLI drift
#: guard's `_SANITY_FLOOR`.
_COUNT_FLOOR = 1000


def _canonical_baseline(text: str) -> tuple:
    """The `(passed, skipped, xfailed)` triple the source states, or a loud failure.

    Keys on the figure-of-record row, not on any triple in the file: the page also
    carries the bare, digest and CI-equivalent readings, and picking up one of those
    instead would compare CI's figure against a local one and call it drift.
    """
    lines = [ln for ln in text.splitlines() if _FIGURE_OF_RECORD in ln]
    assert len(lines) == 1, (
        f"{_BASELINE_PAGE.name}: the marker {_FIGURE_OF_RECORD!r} matched {len(lines)} lines, "
        "expected exactly one. If the wording moved, move `_FIGURE_OF_RECORD` — do not drop "
        "the check, that is how the drift this guard exists for returns."
    )
    match = _COUNT_RE.search(lines[0])
    assert match, f"{_BASELINE_PAGE.name}: the figure-of-record row states no passed/skipped/xfail triple"
    return tuple(int(group) for group in match.groups())


def _reference_is_intact(line: str) -> Optional[str]:
    """``None`` when a plan page's anchor line points at the source and states no
    figure, else a message saying which half is wrong.

    A pure function on purpose. The pages are correct today, so a test that only reads
    them never sees a violating input — and an assertion whose strength no input tests
    cannot be mutation-proven (deleting the "states no figure" half would slip through
    with the tree green). Separating the check lets the tests below feed it a violation
    directly, which is what gives the doc-level check its teeth.
    """
    if _BASELINE_PAGE.name not in line:
        return f"does not reference {_BASELINE_PAGE.name}"
    if _COUNT_RE.search(line):
        return (
            f"restates a passed/skipped/xfail triple instead of referencing {_BASELINE_PAGE.name}; "
            "move the figure to the source"
        )
    return None


def test_the_source_states_one_canonical_triple() -> None:
    """The single source exists, parses, and is plausible.

    This replaces the old three-way agreement check: the pages no longer state a
    number, so there is nothing to cross-compare — the number has exactly one home,
    and this is the assertion that keeps it honest. The floor is the same one the old
    comparison carried, moved here: a mis-typed 206 is a mis-type, and nothing else in
    the file would catch it.
    """
    assert _BASELINE_PAGE.is_file(), (
        f"{_BASELINE_PAGE.name} is missing; it is the single source of the expected suite size"
    )
    passed, skipped, xfailed = _canonical_baseline(_BASELINE_PAGE.read_text(encoding="utf-8"))
    assert passed >= _COUNT_FLOOR, f"implausible suite size (below {_COUNT_FLOOR}): {passed}"
    assert 0 <= skipped < 100, f"implausible skip count: {skipped}"
    assert 0 <= xfailed < 100, f"implausible xfail count: {xfailed}"


def test_every_page_that_used_to_state_the_baseline_now_references_it() -> None:
    """Each of the three pages points at the source and states no figure of its own."""
    for path, anchor in _BASELINE_REFS:
        assert path.is_file(), f"{path.name} vanished; it must reference the pre-flight baseline"
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if anchor in ln]
        assert len(lines) == 1, (
            f"{path.name}: the anchor {anchor!r} matched {len(lines)} lines, expected exactly "
            "one. If the wording moved, move the anchor in `_BASELINE_REFS` — do not drop "
            "the page from the check, that is how the drift this guard exists for returns."
        )
        problem = _reference_is_intact(lines[0])
        assert problem is None, f"{path.name}: the line anchored by {anchor!r} {problem}"


def test_the_page_set_is_pinned_by_name() -> None:
    """Pinned by name, because dropping a page from `_BASELINE_REFS` narrows the
    guard silently — the loop above is happy with two pages either way."""
    assert {path.name for path, _ in _BASELINE_REFS} == {
        "MASTER_TODO.md", "NEXT_CHUNK.md", "REMAINING_PLAN.md",
    }
    assert len(_BASELINE_REFS) == 3
    # And each anchor must be specific to its own page: an anchor that matches in two
    # files is an anchor that will match the wrong line when one of them is reworded.
    for path, anchor in _BASELINE_REFS:
        hits = [ln for ln in path.read_text(encoding="utf-8").splitlines() if anchor in ln]
        assert len(hits) == 1, f"{path.name}: anchor {anchor!r} matched {len(hits)} lines"


def test_the_source_is_not_one_of_the_pages_it_owns() -> None:
    """The source and the pages that reference it must be different files, or the
    reference is a tautology and the single source is not single."""
    assert _BASELINE_PAGE.name == "BASELINE.md"
    assert _BASELINE_PAGE not in {path for path, _ in _BASELINE_REFS}
    assert _BASELINE_PAGE.parent == REPO / "docs" / "plan"


def test_the_reference_check_rejects_a_page_that_restates_the_figure() -> None:
    """The teeth, fed the violating line the repo cannot supply while it is consistent.

    The first form is the shape this repo actually drifted on: a page that keeps its
    reference *and* re-adds a number beside it, which is how a second home for the
    figure gets started.
    """
    assert _reference_is_intact("| Tests | `pytest -q` | see `BASELINE.md` |") is None

    restate = "| Tests | `pytest -q` | 2755 passed / 4 skipped / 3 xfailed (see BASELINE.md) |"
    assert "restate" in (_reference_is_intact(restate) or "")

    # And the other half: pointing somewhere else entirely is not a reference either.
    assert "does not reference" in (
        _reference_is_intact("| Tests | `pytest -q` | 2755 passed / 4 skipped / 3 xfailed |") or ""
    )


def test_the_source_parser_keys_on_the_figure_of_record_row() -> None:
    """The parser must not grab any triple in the file — only that row's.

    The source also quotes the bare, digest and CI-equivalent readings; a parser that
    matched the first triple it saw would compare CI's figure against a local one and
    report drift on a perfectly consistent repo.
    """
    row = "| CI, 3.12 (the figure of record) | `pytest -q` | **2813 passed, 4 skipped, 2 xfailed** |"
    assert _canonical_baseline(f"intro\n{row}\n| bare | x | 2737 passed, 16 skipped, 2 xfailed |\n") == (
        2813, 4, 2,
    )

    # A triple elsewhere in the file is not the figure of record: no marker, no answer.
    with pytest.raises(AssertionError):
        _canonical_baseline("| bare | x | 2737 passed, 16 skipped, 2 xfailed |\n")

    # Two marker rows is as ambiguous as none, and fails for the same reason.
    with pytest.raises(AssertionError):
        _canonical_baseline(f"{row}\n{row}\n")


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


#: `REMAINING_PLAN.md` §11's "State as of" rows that name commits this branch
#: has. The **Released version** row is deliberately excluded: it names the
#: `v2.8.1` tag `7e02412`, which lives on `release/2.8.x` and is *not* an
#: ancestor of `main` — checking it here would fail on a correct tree.
_S11_MAIN_ROWS = (
    "Development line",
    "Last landed chunk",
    "In flight",
    "Next piece of development",
    "Stage",
)

#: A backticked lowercase-hex token of commit length.
_SHA_TOKEN = re.compile(r"`([0-9a-f]{7,40})`")


def _remaining_plan_section_11() -> str:
    text = (REPO / "docs" / "plan" / "REMAINING_PLAN.md").read_text(encoding="utf-8")
    assert "## 11. Picking this up" in text, (
        "REMAINING_PLAN.md lost its §11 cold-start page; the state SHAs live there"
    )
    return text.split("## 11. Picking this up", 1)[1].split("\n## ", 1)[0]


def _section_11_row(section: str, name: str) -> str:
    hits = [ln for ln in section.splitlines() if ln.startswith(f"| **{name}**")]
    assert len(hits) == 1, (
        f"REMAINING_PLAN.md §11: row {name!r} matched {len(hits)} lines, expected exactly "
        "one. If the wording moved, move the row name — do not drop the check."
    )
    return hits[0]


def _is_ancestor(sha: str, ref: str = "HEAD") -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, ref],
        cwd=REPO,
        capture_output=True,
    ).returncode == 0


def test_every_remaining_plan_state_sha_is_a_real_ancestor_of_head() -> None:
    """The `MASTER_TODO` reconciled SHA was guarded; §11's other cells were not.

    Every commit ``main``'s state rows name must exist and be an ancestor of this
    branch. A row that names a commit from another line, or a token that was
    mistyped, makes the cold-start page describe a state this branch never had.
    """
    section = _remaining_plan_section_11()
    checked = 0
    for name in _S11_MAIN_ROWS:
        for sha in _SHA_TOKEN.findall(_section_11_row(section, name)):
            exists = subprocess.run(
                ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                cwd=REPO,
                capture_output=True,
            ).returncode == 0
            assert exists, f"§11 row {name!r} cites {sha}, which is not a commit"
            assert _is_ancestor(sha), (
                f"§11 row {name!r} cites {sha}, which is not an ancestor of HEAD; a "
                "state row may only name commits this branch has"
            )
            checked += 1
    assert checked >= 10, f"§11 SHA scan found only {checked} tokens; the row anchors drifted"


def test_the_development_line_does_not_lag_a_landing_the_page_records() -> None:
    """The exact gap the 2026-10-16 audit found and nothing compared.

    §11's **Development line** row still said `874b3d4` (EM-410) after EM-412
    landed as `637a269`. Every SHA in that stale row is still a real ancestor, so
    the existence/ancestry check above passes it too — what slipped was the
    *relationship*. Pin it: the line must be at least as new as every landing the
    same page records in its **Last landed chunk** row.
    """
    section = _remaining_plan_section_11()
    dev_row = _section_11_row(section, "Development line")
    match = re.search(r"`main` at `([0-9a-f]{7,40})`", dev_row)
    assert match, "§11's Development line must read: `main` at `<sha>`"
    dev = match.group(1)
    assert _is_ancestor(dev), f"§11's Development line names {dev}, not an ancestor of HEAD"

    landings = list(
        dict.fromkeys(_SHA_TOKEN.findall(_section_11_row(section, "Last landed chunk")))
    )
    assert len(landings) >= 5, f"§11's landing row cites only {len(landings)} commits"
    lagging = [sha for sha in landings if not _is_ancestor(sha, dev)]
    assert not lagging, (
        f"§11's Development line ({dev}) lags landings the same page records: {lagging}. "
        "Move the line to the newest landing shown there."
    )
