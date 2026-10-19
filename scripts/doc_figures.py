"""Parsing shared by the figures-of-record script and its guard.

`docs/plan/suite_figures.json` is the machine record; `scripts/record_suite_figures.py`
writes it from pytest summary lines; `tests/test_suite_figures.py` fails when the
prose in the five documents below states a triple that is neither current nor
historical. Both sides parse the docs the same way, so a change to the format can
only break in one place.

Stdlib only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RECORD_PATH = REPO / "docs" / "plan" / "suite_figures.json"

#: The five places a chunk's figures get written, and the reason this guard
#: exists: one pass wrote all of them one low.
DOCS = (
    "CHANGELOG.md",
    "MASTER_TODO.md",
    "docs/plan/BASELINE.md",
    "docs/plan/REMAINING_PLAN.md",
    "docs/plan/NEXT_CHUNK.md",
)

#: `2853 passed, 15 skipped, 2 xfailed` — the canonical long form, in the ONE
#: order the repo uses. A reordered triple is a drift this must catch too.
TRIPLE_RE = re.compile(r"(\d+)\s+passed,\s+(\d+)\s+skipped,\s+(\d+)\s+xfailed")

#: `**2860 / 16 / 2**` — the plan pages' shorthand. The 3-5 digit first group is
#: what keeps this off prose like "2 / 3 / 4"; the counts never drop below 100.
SHORTHAND_RE = re.compile(r"\b(\d{3,5}) / (\d{1,3}) / (\d{1,2})\b")

#: pytest prints its counters as `<n> <word>` pairs, in a fixed order. Scanning
#: them in order is what lets the parser refuse a reordered or red summary line
#: rather than quietly reading whichever pair it finds first.
_COUNTER = re.compile(
    r"(\d+) (failed|passed|skipped|xfailed|xpassed|deselected|error|errors|warning|warnings)\b"
)

#: pytest's canonical counter order. Note `xfailed` is its own word: a bare
#: `failed` scan would misread `2 xfailed` as a red run.
COUNTER_ORDER = (
    "failed",
    "error",
    "errors",
    "passed",
    "skipped",
    "xfailed",
    "xpassed",
    "deselected",
    "warning",
    "warnings",
)


def parse_summary(text: str) -> tuple:
    """The (passed, skipped, xfailed) of the last pytest summary line in `text`.

    Refuses, rather than guessing:

    * a line with no counters at all (nothing was run);
    * a line reporting any failure or error — **failed is always 0 on a green
      run**, so a figure carrying one is not a figure of record;
    * a line whose counters are out of pytest's canonical order (a hand-written
      or mangled summary), so the ordering rule is enforced on the way in.
    """
    lines = [ln for ln in text.splitlines() if _COUNTER.search(ln)]
    if not lines:
        raise SystemExit("no pytest summary line found (expected 'N passed, ...')")
    line = lines[-1].strip()

    counters = [(m.group(2), int(m.group(1))) for m in _COUNTER.finditer(line)]
    positions = [COUNTER_ORDER.index(word) for word, _ in counters]
    if positions != sorted(positions):
        raise SystemExit(
            f"refusing a summary with out-of-order counters: {line!r} "
            f"(expected pytest's order {COUNTER_ORDER})"
        )

    values = dict(counters)
    for bad in ("failed", "error", "errors"):
        if values.get(bad):
            raise SystemExit(
                f"refusing to record a red run: {values[bad]} {bad} ({line!r}) — "
                "failed must be 0 on a green run"
            )
    if "passed" not in values:
        raise SystemExit(f"summary line reports no passes: {line!r}")

    return (values["passed"], values.get("skipped", 0), values.get("xfailed", 0))



def load_record() -> dict:
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


def current(record: dict) -> set:
    """The four triples of record, as tuples."""
    return {tuple(v) for v in record["current"].values()}


def historical(record: dict) -> set:
    """Triples that were once figures of record, plus any bootstrapped example."""
    return {tuple(t) for t in record.get("historical", [])}


def all_triples(text: str) -> set:
    """Every test-count triple in `text`, in either form."""
    found = {tuple(int(g) for g in m.groups()) for m in TRIPLE_RE.finditer(text)}
    found |= {tuple(int(g) for g in m.groups()) for m in SHORTHAND_RE.finditer(text)}
    return found


def read_docs() -> dict:
    """{relative path: text} for the five documents, in DOCS order."""
    return {name: (REPO / name).read_text(encoding="utf-8") for name in DOCS}


def harvest() -> set:
    """Every triple currently stated anywhere in the five documents."""
    found = set()
    for text in read_docs().values():
        found |= all_triples(text)
    return found
