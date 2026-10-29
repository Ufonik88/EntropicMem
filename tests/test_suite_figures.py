"""The figures-of-record guard: a chunk's test counts are measured once, not typed.

Why this exists: a chunk's figures were hand-typed into five places — the BASELINE
table, the CHANGELOG entry, the MASTER_TODO ledger row, plan §11's rows and the
NEXT_CHUNK pass — and one pass wrote them all one low, because it measured the
tree before the last test existed. CI's own read exposed the discrepancy. Fixing
the numbers would have fixed nothing; this makes the numbers checkable.

`docs/plan/suite_figures.json` is the record, written only by
`scripts/record_suite_figures.py` from pytest summary lines. This guard fails when:

* BASELINE's five table rows do not equal the record;
* BASELINE's ladder does not reproduce the record arithmetically;
* `Read as at <sha>` or the cited CI run id disagrees with the record;
* the newest commit touching the suite surface is not an ancestor of the
  recorded sha (the docs and the record can agree while the tree has moved);
* the ordering rule or the `failed is always 0` rule has gone from the legend;
* **any of the five documents states a triple that is neither current nor
  historical** — the shape the incident took.

The historical set is the allowlist of superseded figures: a triple lands there
only by having been a figure of record, so a typo cannot qualify.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import doc_figures  # noqa: E402

BASELINE = REPO / "docs" / "plan" / "BASELINE.md"

#: BASELINE's table row whose label contains each key (checked in this order).
ROW_KEYS = (
    ("ci", "CI, `test` job"),
    ("bare", "bare (`.venv311`"),
    ("digest", "digest list"),
    ("ci_equiv", "CI-equivalent"),
    ("python310", "Python 3.10"),
)

_TABLE_TRIPLE = doc_figures.TRIPLE_RE
_LADDER_LINE = re.compile(r"^(bare|= CI-equiv|= CI)\s+(\d+) /\s*(\d+) /\s*(\d+)", re.MULTILINE)
_LADDER_DELTA = re.compile(
    r"^[+\u2212-]\s*(extras|digest list|host pins)\s+([\u2212+-]?\d+) passed,\s+([\u2212+-]?\d+) skipped",
    re.MULTILINE,
)
_READ_AS_AT = re.compile(r"Read as at `([0-9a-f]{7,40})`")


def _baseline_rows() -> dict:
    """{key: (passed, skipped, xfailed)} from BASELINE's table."""
    rows = {}
    text = BASELINE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 3:
            continue
        label = cells[1]  # the row's first cell only: the prose cell can name
                          # another row's environment ("this box's CI-equivalent")
        for key, needle in ROW_KEYS:
            if needle in label and key not in rows:
                m = _TABLE_TRIPLE.search(line)
                assert m, f"BASELINE row for {key} states no triple: {line[:120]}"
                rows[key] = tuple(int(g) for g in m.groups())
    return rows


def _baseline_ladder() -> tuple:
    """The `bare` ... `= CI` code block as (bare, ci_equiv, ci, extras_delta, digest_delta)."""
    text = BASELINE.read_text(encoding="utf-8")
    lines = dict((m.group(1), tuple(int(g) for g in m.groups()[1:])) for m in _LADDER_LINE.finditer(text))
    assert set(lines) == {"bare", "= CI-equiv", "= CI"}, f"ladder lines not found: {sorted(lines)}"
    deltas = {
        m.group(1): (
            int(m.group(2).replace("\u2212", "-")),
            int(m.group(3).replace("\u2212", "-")),
        )
        for m in _LADDER_DELTA.finditer(text)
    }
    assert set(deltas) >= {"extras", "digest list", "host pins"}, f"ladder deltas not found: {sorted(deltas)}"
    return lines["bare"], lines["= CI-equiv"], lines["= CI"], deltas


def _record():
    rec = doc_figures.load_record()
    assert set(rec["current"]) == {
        "bare",
        "digest",
        "ci_equiv",
        "ci",
        "python310",
    }, rec["current"].keys()
    for key, triple in rec["current"].items():
        assert len(triple) == 3 and all(isinstance(n, int) for n in triple), (key, triple)
    return rec


# ── the parser that writes the record ──────────────────────────────────────

def test_the_parser_reads_a_canonical_green_summary():
    assert doc_figures.parse_summary(
        "2862 passed, 16 skipped, 2 xfailed, 2 warnings in 210.97s (0:03:30)"
    ) == (2862, 16, 2)


def test_the_parser_refuses_a_red_run():
    """`failed` is printed FIRST, before `passed` — a scan that only looks after
    the pass count would read a red run as green and record its figures."""
    with pytest.raises(SystemExit, match="red run"):
        doc_figures.parse_summary("1 failed, 2935 passed, 4 skipped, 2 xfailed, 4 warnings in 311s")


def test_the_parser_refuses_out_of_order_counters():
    """The ordering rule, enforced on the way in as well as in the prose."""
    with pytest.raises(SystemExit, match="out-of-order"):
        doc_figures.parse_summary("4 skipped, 2935 passed, 2 xfailed in 1s")
    with pytest.raises(SystemExit, match="out-of-order"):
        doc_figures.parse_summary("2935 passed, 2 xfailed, 4 skipped in 1s")


def test_the_parser_refuses_a_summary_with_no_counters():
    with pytest.raises(SystemExit, match="no pytest summary line"):
        doc_figures.parse_summary("no tests ran in 0.01s")


def test_the_parser_does_not_mistake_xfailed_for_failed():
    assert doc_figures.parse_summary("10 passed, 2 xfailed in 1s") == (10, 0, 2)


# ── the rules themselves ────────────────────────────────────────────────────

def test_the_legend_states_the_ordering_and_the_failed_rule():
    """The triple is `passed / skipped / xfailed`, in that order; failed is 0."""
    text = BASELINE.read_text(encoding="utf-8")
    assert "`passed / skipped / xfailed`" in text, "the ordering rule is gone from the legend"
    assert "always 0 on a green run" in text, "the 'failed is always 0' rule is gone"
    assert "failed` is a fourth number" in text or "Failed is a fourth number" in text


def test_the_record_is_shaped_like_a_green_run():
    rec = _record()
    for key, triple in rec["current"].items():
        assert triple[0] > 0, f"{key}: no passes recorded"
        assert triple[2] >= 0, f"{key}: negative xfailed"
    # the host pins are the only skip CI has over the CI-equivalent box, and the
    # digest list converts exactly one skip of a bare box.
    assert rec["current"]["ci"][1] > rec["current"]["ci_equiv"][1], "CI must skip more than the CI-equivalent box"
    assert rec["current"]["digest"][1] == rec["current"]["bare"][1] - 1, "the digest list converts exactly one skip"


# ── BASELINE against the record ─────────────────────────────────────────────

def test_baselines_table_equals_the_record():
    rec = _record()
    rows = _baseline_rows()
    assert set(rows) == set(rec["current"]), f"BASELINE rows {sorted(rows)} != record {sorted(rec['current'])}"
    for key, triple in rec["current"].items():
        assert rows[key] == tuple(triple), (
            f"BASELINE's {key} row reads {rows[key]} but the record has {tuple(triple)} — "
            "re-measure with scripts/record_suite_figures.py --measure"
        )


def test_baselines_ladder_reproduces_the_record():
    bare, ci_equiv, ci, deltas = _baseline_ladder()
    rec = _record()["current"]
    assert bare == tuple(rec["bare"]), f"ladder bare {bare} != record {tuple(rec['bare'])}"
    assert ci_equiv == tuple(rec["ci_equiv"]), f"ladder CI-equiv {ci_equiv} != record"
    assert ci == tuple(rec["ci"]), f"ladder CI {ci} != record"

    extras_p, extras_s = deltas["extras"]
    digest_p, digest_s = deltas["digest list"]
    pins_p, pins_s = deltas["host pins"]
    assert (
        bare[0] + extras_p + digest_p,
        bare[1] + extras_s + digest_s,
        bare[2],
    ) == ci_equiv, "the ladder's bare -> CI-equiv arithmetic does not add up"
    assert (ci_equiv[0] + pins_p, ci_equiv[1] + pins_s, ci_equiv[2]) == ci, (
        "the ladder's CI-equiv -> CI arithmetic does not add up"
    )


def test_the_read_as_at_sha_and_the_ci_run_agree_with_the_record():
    rec = _record()
    text = BASELINE.read_text(encoding="utf-8")
    m = _READ_AS_AT.search(text)
    assert m, "BASELINE has no `Read as at <sha>` line"
    sha = m.group(1)
    assert sha == rec["sha"], f"BASELINE reads as at {sha} but the record was measured at {rec['sha']}"
    ok = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=REPO, capture_output=True
    )
    assert ok.returncode == 0, f"the recorded sha {sha} is not a commit in this repository"
    if rec.get("ci_run"):
        assert rec["ci_run"] in text, f"the CI run id {rec['ci_run']} is not cited in BASELINE"
    else:
        assert "projected" in text, (
            "the record carries a projected CI figure but BASELINE does not mark it projected"
        )

    # The record can go stale in the other direction: docs and record agree with
    # each other while the *tree* has moved past the measurement. The
    # security-hardening commits added 17 tests after 5258b46 and every guard
    # stayed green, because nothing compared the record to the tree. Rule: the
    # newest commit touching the suite surface must be an ancestor of the
    # recorded sha. tests/test_suite_figures.py is excluded because it is the
    # checker itself — its edits add no tests to the count, so they must not
    # invalidate the measurement they check.
    newest = subprocess.run(
        [
            "git", "log", "-1", "--format=%H", "--",
            "tests", ":(exclude)tests/test_suite_figures.py",
            "conftest.py", "pyproject.toml",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert newest.returncode == 0, newest.stderr
    newest_sha = newest.stdout.strip()
    assert newest_sha, "git found no commit touching tests/, conftest.py or pyproject.toml"
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", newest_sha, sha],
        cwd=REPO,
        capture_output=True,
    )
    assert ancestor.returncode == 0, (
        f"the newest commit touching the suite surface ({newest_sha[:7]}) is not an "
        f"ancestor of the recorded sha ({sha}); the figures describe an older tree — "
        "re-measure with scripts/record_suite_figures.py --measure"
    )


def test_a_projected_ci_figure_is_marked_projected_in_baseline():
    """The record and the prose must agree about whether CI's figure was read."""
    rec = _record()
    text = BASELINE.read_text(encoding="utf-8")
    row = [ln for ln in text.splitlines() if ln.startswith("|") and "CI, `test` job" in ln][0]
    if rec.get("ci_projected"):
        assert "projected" in row, "a projected CI figure is stated as if read"
        assert not re.search(r"read at `[0-9a-f]{7,40}`", row), (
            "a projected CI figure claims to be read at a SHA"
        )
    else:
        assert "projected" not in row, "a read CI figure is still marked projected"


# ── the five documents against the record ───────────────────────────────────

def test_no_document_states_a_triple_that_is_neither_current_nor_historical():
    """The incident's shape: one place saying 2859 while the measurement said 2860.

    A triple qualifies as historical only by having been a figure of record, so a
    typo cannot be silenced by adding it here — it has to be re-measured.
    """
    rec = _record()
    allowed = doc_figures.current(rec) | doc_figures.historical(rec)
    offenders = []
    for name, text in doc_figures.read_docs().items():
        for triple in sorted(doc_figures.all_triples(text)):
            if triple not in allowed:
                offenders.append(f"{name}: {' / '.join(str(n) for n in triple)}")
    assert not offenders, (
        "these triples are neither the current figures of record nor any historical one; "
        "re-measure (scripts/record_suite_figures.py --measure) or fix the typo:\n  "
        + "\n  ".join(offenders)
    )


def test_the_changelog_states_the_current_ci_figure():
    """The CHANGELOG is the one place that must restate the figures as evidence.

    The current CI figure lives in the **newest section with content**: the
    `[Unreleased]` section while work is in flight, and — once a release
    converts it (chunk 55) — the release section the figures shipped in. An
    empty `[Unreleased]` above a release section is the released state, not a
    drift.
    """
    rec = _record()
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    after_head = text.split("## [Unreleased]", 1)[1]
    unreleased = after_head.split("\n## [", 1)[0]
    # A section carrying only the standing blockquote note is the released
    # state: the newest section (the release the figures shipped in) is what
    # must state the current figure.
    prose = [ln for ln in unreleased.splitlines() if ln.strip() and not ln.strip().startswith(">")]
    if not prose:
        newest = after_head.split("## [", 1)[1]
        unreleased = newest.split("\n## [", 1)[0]
    ci = rec["current"]["ci"]
    long_form = f"{ci[0]} / {ci[1]} / {ci[2]}"
    assert long_form in unreleased or "projected" in unreleased, (
        f"the CHANGELOG's newest section does not state the current CI figure "
        f"({long_form}) or mark it projected"
    )
