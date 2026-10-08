"""P0c — reading the shadow log against the **pre-declared** promotion observable.

The observable in ``_shadow.PROMOTION`` was frozen before any data was collected, so
the whole point of the readout is that it cannot be fitted to the sample. What these
tests pin is the set of properties that make a green light mean something:

* every threshold comes from ``PROMOTION`` at report time — change the dict and the
  verdict follows, so nothing is copied into the reader;
* an under-filled sample, a sample with no injections, and a sample with unreadable
  lines are all ``cannot conclude`` — never ``met``. An empty live store would
  otherwise read as 0% divergence and hand the owner a fake pass;
* a violation is a violation: ``not met`` outranks ``cannot conclude``;
* the divergence rate is measured over the denominator the frozen comment names
  ("turns with injection"), the alternates are shown as context only, and the
  staleness bound travels next to the number;
* ``v3_only`` cites its lines and never prints the query text;
* the reader cross-checks the writer's own fields (``stale``, ``divergence``) against
  the frozen bound and the recorded ids, and a disagreement is not trusted;
* p95 is nearest-rank and prints p50/max beside it — the perf-smoke lesson: a low p50
  with a huge max is one noisy sample, and the report must let a reader see that;
* the report reads only, and the runner's exit code carries the verdict.

Invented data only (rule 4). Nothing here opens the live store.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from plugins.entropicmem import _shadow  # noqa: E402

#: Long enough to satisfy the frozen floor, so a test that wants "everything else
#: clean" does not have to repeat 200 in ten places.
N = _shadow.PROMOTION["min_turns"]

SECRET_QUERY = "does the owner's private note about Dr. Alice Example leak"


def line(
    index: int = 0,
    *,
    v2: List[str] = (),
    v3: List[str] = (),
    divergence: List[str] | None = None,
    v3_only: List[str] | None = None,
    age: float = 0.0,
    stale: bool = False,
    ms: float = 40.0,
    query: str = "an invented question about the staging server",
) -> Dict[str, Any]:
    """One divergence line in the shape ``_shadow.run`` writes."""
    return {
        "ts": f"2026-10-08T09:{index // 60:02d}:{index % 60:02d}.000Z",
        "query": query,
        "v2_ids": list(v2),
        "v3_ids": list(v3),
        "divergence": list(divergence) if divergence is not None else sorted(set(v2) ^ set(v3)),
        "v3_only": list(v3_only) if v3_only is not None else sorted(set(v3) - set(v2)),
        "copy_age_s": age,
        "copy_refreshed": age == 0.0,
        "stale": stale,
        "shadow_ms": ms,
        "caveat": _shadow.CAVEAT,
    }


def sample(count: int = N, **kwargs) -> List[Dict[str, Any]]:
    return [line(index, **kwargs) for index in range(count)]


def clean(count: int = N, *, injections: int = 100, diverging: int = 5) -> List[Dict[str, Any]]:
    """A sample that satisfies every condition: enough turns, fresh copy, divergence
    at or under the ceiling, no v3-only line, off-turn cost well inside the budget.

    Note what "diverging" means here: v3 **missed** an id v2 injected. Divergence where
    v3 adds an id instead is a v3-only line, which `v3_only_never` forbids outright — so
    building the diverging case the lazy way would quietly test a different rule.
    """
    lines: List[Dict[str, Any]] = []
    for index in range(count):
        if index < injections:
            if index < diverging:
                lines.append(line(index, v2=["a%016x" % index, "missed%016x" % index],
                                  v3=["a%016x" % index]))
            else:
                lines.append(line(index, v2=["a%016x" % index], v3=["a%016x" % index]))
        else:
            lines.append(line(index))
    return lines


# --- the thresholds are the frozen ones, read at report time ---------------


def test_the_report_echoes_the_frozen_observable():
    report = _shadow.evaluate(clean())
    assert report["thresholds"] == dict(_shadow.PROMOTION)


def test_the_verdict_uses_the_frozen_values_rather_than_a_copy_of_them(monkeypatch):
    """If the reader carried its own literals, tightening the observable would not
    change what it says — which is exactly the drift that makes a reading fake."""
    data = clean()
    assert _shadow.evaluate(data)["verdict"] == "met"
    monkeypatch.setitem(_shadow.PROMOTION, "max_divergence_rate", 0.01)
    assert _shadow.evaluate(data)["verdict"] == "not met"
    monkeypatch.setitem(_shadow.PROMOTION, "max_p95_shadow_ms", 10.0)
    report = _shadow.evaluate(data)
    assert report["conditions"]["p95_within_budget"]["verdict"] == "not met"


# --- a green light must mean something -------------------------------------


def test_a_full_clean_sample_is_met():
    report = _shadow.evaluate(clean())
    assert report["verdict"] == "met"
    assert all(c["verdict"] == "met" for c in report["conditions"].values())


def test_one_turn_short_is_cannot_conclude_never_a_pass():
    """The floor is part of the observable, so a 199-turn sample cannot report `met`
    even when everything in it is clean."""
    short = _shadow.evaluate(clean(N - 1))
    assert short["verdict"] == "cannot conclude"
    assert short["conditions"]["min_turns"]["verdict"] == "not met"
    assert _shadow.evaluate(clean(N))["verdict"] == "met"


def test_an_empty_store_reads_as_no_signal_not_as_zero_divergence():
    """The trap P0c would otherwise walk into: the live store holds zero facts, so
    v2 injects nothing and v3 injects nothing, and a naive rate is 0/0 -> 0% -> met.
    The denominator is turns with injection, so this sample has no signal at all."""
    report = _shadow.evaluate(sample(N))
    assert report["conditions"]["divergence_rate"]["verdict"] == "no signal"
    assert report["verdict"] == "cannot conclude"
    assert "no signal" in " ".join(report["reasons"]).lower()


def test_a_violation_outranks_an_underfilled_sample():
    """`cannot conclude` must not hide a real failure: 3 turns with a fabricated hit
    is `not met`, so the reader cannot drift into 'we just need more data'."""
    data = sample(3, v3=["mem_fabricated"])
    report = _shadow.evaluate(data)
    assert report["conditions"]["v3_only_never"]["verdict"] == "not met"
    assert report["verdict"] == "not met"


# --- the frozen definition, with its margin visible ------------------------


def test_divergence_is_measured_over_turns_with_injection():
    report = _shadow.evaluate(clean(N, injections=100, diverging=10))
    condition = report["conditions"]["divergence_rate"]
    assert condition["injections"] == 100
    assert condition["diverged"] == 10
    assert condition["value"] == pytest.approx(0.10)
    assert condition["verdict"] == "met", "the ceiling is inclusive"


def test_one_more_diverging_turn_than_the_ceiling_allows_is_not_met():
    report = _shadow.evaluate(clean(N, injections=100, diverging=11))
    condition = report["conditions"]["divergence_rate"]
    assert condition["value"] == pytest.approx(0.11)
    assert condition["verdict"] == "not met"
    assert report["verdict"] == "not met"


def test_the_alternate_denominators_are_context_and_not_the_verdict():
    """A reader must see what the choice costs without the choice being re-derived:
    the same 10 diverging turns are 5% over all lines and 10% over injected ones."""
    report = _shadow.evaluate(clean(N, injections=100, diverging=10))
    assert report["context"]["divergence_over_all_lines"] == pytest.approx(0.05)
    assert report["conditions"]["divergence_rate"]["value"] == pytest.approx(0.10)


# --- the biases travel with the numbers ------------------------------------


def test_a_rate_margin_is_printed_in_points_not_a_bare_fraction():
    """`margin: -0.28` beside a percentage is a readability bug in the one tool whose
    job is readability. The seeded 240-turn run is what showed it."""
    report = _shadow.evaluate(clean(N, injections=200, diverging=75))  # 37.5%
    rendered = _shadow.render(report)
    assert "-27.50 pts" in rendered
    assert "margin: -0.28" not in rendered


def test_the_divergence_is_decomposed_into_misses_and_additions():
    """The ceiling deliberately counts a miss and an addition alike; a reader must not
    have to, because the two mean opposite things about v3."""
    data = [
        line(0, v2=["keep", "miss1", "miss2"], v3=["keep"]),
        line(1, v2=["x"], v3=["x", "extra"]),
    ]
    report = _shadow.evaluate(data)
    assert report["context"]["divergence_shape"] == {"v3_missed": 2, "v3_added": 1}
    rendered = _shadow.render(report)
    assert "v3 missed 2" in rendered and "added 1" in rendered


def test_every_number_shows_its_margin():
    """A pass/fail alone hides how close the run was: the owner asked for margin."""
    report = _shadow.evaluate(clean())
    for name, condition in report["conditions"].items():
        assert "margin" in condition, name
    assert report["conditions"]["divergence_rate"]["margin"] == pytest.approx(0.05)
    assert report["conditions"]["min_turns"]["margin"] == 0

    broken = clean()
    broken[1] = line(1, v2=["x"], v3=["y", "z"])
    assert _shadow.evaluate(broken)["conditions"]["v3_only_never"]["margin"] < 0


def test_findings_cite_ids_and_lines_and_never_the_question():
    data = clean(diverging=1)
    data[7] = line(7, v2=["kept", "missed"], v3=["kept"], query=SECRET_QUERY)
    report = _shadow.evaluate(data)

    assert {"line": 8, "v2_ids": ["kept", "missed"], "v3_ids": ["kept"]} in (
        report["findings"]["divergence"]
    )
    rendered = _shadow.render(report)
    assert "line 8" in rendered and "missed" in rendered
    # The leak surface is the whole report, not the human view alone: `--json` prints
    # these findings, so conversation text must be absent from the data too.
    assert SECRET_QUERY not in rendered
    assert SECRET_QUERY not in json.dumps(report)
    assert "Alice Example" not in json.dumps(report)


def test_a_stale_copy_blocks_an_otherwise_clean_reading():
    data = clean()
    data[7] = line(7, v2=["a7"], age=1200.0, stale=True)
    report = _shadow.evaluate(data)
    assert report["conditions"]["copy_within_bound"]["verdict"] == "not met"
    assert report["verdict"] == "not met"


def test_a_stale_flag_that_disagrees_with_the_bound_is_not_trusted():
    """The writer marks staleness from the same constant; if the two ever diverge,
    the sample cannot be read as fresh. Both directions are checked, because a test
    that only covers the age side passes with the cross-check deleted."""
    late_but_unflagged = clean()
    late_but_unflagged[9] = line(9, v2=["a9"], age=1200.0, stale=False)
    report = _shadow.evaluate(late_but_unflagged)
    assert report["conditions"]["copy_within_bound"]["verdict"] == "not met"
    assert "stale flag" in " ".join(report["reasons"]).lower()

    flagged_but_fresh = clean()
    flagged_but_fresh[11] = line(11, v2=["a11"], age=10.0, stale=True)
    second = _shadow.evaluate(flagged_but_fresh)
    assert second["conditions"]["copy_within_bound"]["verdict"] == "not met", (
        "a line that claims to be stale cannot be read as fresh"
    )
    assert "stale flag" in " ".join(second["reasons"]).lower()


def test_the_caveat_is_printed_next_to_the_divergence_number():
    rendered = _shadow.render(_shadow.evaluate(clean()))
    assert _shadow.CAVEAT in rendered
    divergence_line = [ln for ln in rendered.splitlines() if "divergence" in ln]
    assert divergence_line, "the render must show the divergence condition"


# --- fabrication and line citations ---------------------------------------


def test_v3_only_is_never_a_pass_and_cites_its_line_without_the_query_text():
    data = clean()
    data[42] = line(42, v2=[], v3=["mem_fabricated"], query=SECRET_QUERY)
    report = _shadow.evaluate(data)
    assert report["conditions"]["v3_only_never"]["verdict"] == "not met"
    assert report["conditions"]["v3_only_never"]["lines"] == [43]  # 1-based file order

    rendered = _shadow.render(report)
    assert "line 43" in rendered
    assert "mem_fabricated" in rendered
    # The leak surface is the whole report, not just the human view: `--json` prints
    # these findings, so question text must be absent from the data as well.
    assert SECRET_QUERY not in rendered
    assert SECRET_QUERY not in json.dumps(report)
    assert "Alice Example" not in json.dumps(report)


def test_a_recorded_divergence_that_disagrees_with_the_ids_is_not_trusted():
    data = clean()
    data[3] = line(3, v2=["same"], v3=["same"], divergence=["same"])
    report = _shadow.evaluate(data)
    assert report["conditions"]["divergence_rate"]["verdict"] == "not met"
    assert "inconsistent" in " ".join(report["reasons"]).lower()


# --- the off-turn cost -----------------------------------------------------


def test_p95_is_nearest_rank_and_prints_p50_and_max():
    """One stray slow sample with a low p50 must read as noise, not as a failure —
    the tell `perf-smoke` learned the hard way."""
    data = clean()
    data[0] = line(0, v2=["a0"], ms=900.0)
    report = _shadow.evaluate(data)
    budget = report["conditions"]["p95_within_budget"]
    assert budget["max"] == pytest.approx(900.0)
    assert budget["value"] == pytest.approx(40.0)
    assert budget["verdict"] == "met"
    assert budget["p50"] <= budget["value"] <= budget["max"]


def test_p95_above_the_ceiling_is_not_met():
    data = clean()
    for index in range(12):  # > 5% of the sample, so nearest-rank p95 is inside them
        data[index] = line(index, v2=["a%d" % index], ms=400.0)
    report = _shadow.evaluate(data)
    assert report["conditions"]["p95_within_budget"]["verdict"] == "not met"
    assert report["verdict"] == "not met"


# --- unreadable lines are counted, not dropped ----------------------------


def test_malformed_lines_are_counted_and_block_a_pass():
    data = clean()
    del data[5]["shadow_ms"]           # a truncated write
    data.append("not an object")        # a half line
    report = _shadow.evaluate(data)
    assert report["sample"]["malformed"] == 2
    assert report["sample"]["usable"] == N - 1
    assert report["verdict"] == "cannot conclude"


# --- the reader and the writer agree, on real lines -----------------------


def test_the_reader_understands_the_lines_the_writer_writes(tmp_path, monkeypatch, live_db):
    """Schema coupling, pinned end to end: these lines come from `_shadow.run`, not
    from this file's own idea of the shape, so a writer change that the reader did not
    follow makes every line unreadable here instead of reporting zero turns."""
    copy = tmp_path / "shadow" / "memory.db"
    monkeypatch.setenv(_shadow.SHADOW_ENV, str(copy))
    lines_path = tmp_path / "divergence.jsonl"

    for index in range(3):
        written = _shadow.run(
            # An empty copy, which is what the real store is today: the turn injected
            # nothing, so ``v2_ids`` is empty too.
            live_db,
            profile="eval",
            query="what does the staging server run",
            v2_ids=[],
            destination=lines_path,
        )
        assert written is not None

    report = _shadow.report(lines_path)
    assert report["sample"]["usable"] == 3, "every written line must be readable"
    assert report["sample"]["malformed"] == 0
    assert set(report["conditions"]) == {
        "min_turns", "copy_within_bound", "divergence_rate", "v3_only_never", "p95_within_budget",
    }
    assert report["verdict"] == "cannot conclude", "three turns cannot conclude anything"


@pytest.fixture()
def live_db(tmp_path):
    """An empty real sqlite file: the shadow copies it and migrates the copy."""
    import sqlite3

    path = tmp_path / "live" / "memory.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(str(path)).close()
    return path


# --- reading is read-only, and the runner is honest -----------------------


def test_the_report_writes_nothing(tmp_path):
    log = tmp_path / "divergence.jsonl"
    log.write_text("".join(json.dumps(item) + "\n" for item in clean()), encoding="utf-8")
    before = (log.read_bytes(), log.stat().st_mtime_ns)

    _shadow.report(log)

    assert (log.read_bytes(), log.stat().st_mtime_ns) == before


def test_a_missing_log_names_the_path_and_how_to_enable_collection(tmp_path, capsys):
    missing = tmp_path / "nowhere" / "divergence.jsonl"
    code = _shadow.main(["report", "--log", str(missing)])
    assert code == 2
    printed = capsys.readouterr().out
    assert str(missing) in printed
    assert _shadow.SHADOW_ENV in printed, "the reader must say how collection is turned on"


def test_the_exit_code_carries_the_verdict(tmp_path, capsys):
    def run_and_code(lines_data: List[Dict[str, Any]]) -> int:
        log = tmp_path / f"div{len(lines_data)}{lines_data[0]['shadow_ms']}.jsonl"
        log.write_text("".join(json.dumps(i) + "\n" for i in lines_data), encoding="utf-8")
        return _shadow.main(["report", "--log", str(log)])

    assert run_and_code(clean()) == 0
    broken = clean()
    broken[1] = line(1, v2=["x"], v3=["y", "z"])  # a v3_only line
    assert run_and_code(broken) == 1
    assert run_and_code(sample(10)) == 2


def test_json_output_is_the_report_verbatim(tmp_path, capsys):
    log = tmp_path / "divergence.jsonl"
    log.write_text("".join(json.dumps(i) + "\n" for i in clean()), encoding="utf-8")

    assert _shadow.main(["report", "--log", str(log), "--json"]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed) == _shadow.report(log)
