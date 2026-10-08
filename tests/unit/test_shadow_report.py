"""P0c — reading the shadow log against the **pre-declared** promotion observable.

The observable in ``_shadow.PROMOTION`` was frozen before any data was collected, and on
**2026-10-08 the owner ruled its shape changed** — before a single real turn was read,
which is the only circumstance in which changing it is not fitting it to the sample:

* **fabrication stays a hard ceiling** (``max_v3_only == 0``): v3 inventing a memory v2
  did not have is a correctness/safety property, not a tuning knob;
* **the miss side is split out** (``max_v2_miss_rate``) because the old symmetric
  ``max_divergence_rate`` counted "v3 dropped a hit v2 had" exactly like "v3 invented
  one", and a measured sample was 150 misses with **0** additions — a gate that fails on
  a non-safety metric blocks a better engine;
* **the miss ceiling is NOT ARMED yet** (``None``) and its arming rule is pre-registered
  in ``_shadow.MISS_CEILING_RULE``: v2's own miss rate against a held-out reference. An
  un-armed ceiling reports ``not armed`` and the sample reads ``cannot conclude`` — never
  ``met`` — so the ungated dimension is loud rather than accidental.

What these tests pin, beyond that ruling:

* thresholds come from ``PROMOTION`` at report time — change the dict, the verdict moves;
* an under-filled, no-signal or unreadable sample is never ``met``;
* a violation outranks a short sample;
* fabrication and misses are **separable**: each can fail alone, and neither excuses the
  other;
* the retired symmetric rate is still *reported*, so the earlier 37.5% finding stays
  comparable;
* the writer's own fields are cross-checked, not trusted;
* p95 is nearest-rank with p50/max beside it, margins are shown (rates in points), and
  findings carry ids and line numbers — never question text, in the render *or* `--json`;
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

#: The frozen turn floor, so a test that wants "everything else clean" need not repeat it.
N = _shadow.PROMOTION["min_turns"]

SECRET_QUERY = "does the owner's private note about Dr. Alice Example leak"

CONDITIONS = {
    "min_turns", "copy_within_bound", "v3_only_never", "v2_miss_rate", "p95_within_budget",
}


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


def miss_lines(turns: int = N, *, missing: int = 0) -> List[Dict[str, Any]]:
    """A sample with an exact, hand-computable miss rate.

    Every turn injects one id; the first ``missing`` of them are dropped by v3. So
    ``v2_miss_rate == missing / turns`` exactly, ``v3_only`` is zero everywhere, and the
    symmetric rate equals the same fraction — which is what makes the boundary tests
    arithmetic rather than guesswork.
    """
    return [
        line(index, v2=[f"a{index:04d}"], v3=[] if index < missing else [f"a{index:04d}"])
        for index in range(turns)
    ]


@pytest.fixture()
def armed(monkeypatch):
    """Arm the miss ceiling, because the default is deliberately un-armed.

    Arming is an act with a pre-registered rule; a test that wants a `met` verdict has to
    perform it explicitly rather than inherit it.
    """
    monkeypatch.setitem(_shadow.PROMOTION, "max_v2_miss_rate", 0.10)


@pytest.fixture(autouse=True)
def _thresholds_restored():
    """Belt to `armed`'s braces: the frozen dict must not survive a test."""
    before = dict(_shadow.PROMOTION)
    yield
    assert _shadow.PROMOTION == before, "a test left PROMOTION modified"


# --- the observable is the ruled one, and the reader cannot drift from it ----


def test_the_observable_is_the_split_one_the_owner_ruled():
    assert set(_shadow.PROMOTION) == {
        "min_turns", "max_copy_age_s", "max_v3_only", "max_v2_miss_rate", "max_p95_shadow_ms",
    }
    assert _shadow.PROMOTION["max_v3_only"] == 0, "fabrication stays a hard ceiling"
    assert _shadow.PROMOTION["max_copy_age_s"] == _shadow.MAX_COPY_AGE_S
    assert _shadow.PROMOTION["max_v2_miss_rate"] is None, "un-armed until v2's holdout rate exists"
    assert "max_divergence_rate" not in _shadow.PROMOTION, "the symmetric ceiling is retired"


def test_the_arming_rule_is_pre_registered_and_says_it_is_not_gated():
    rule = _shadow.MISS_CEILING_RULE
    assert "holdout" in rule, "the rule must name the held-out reference"
    assert "NOT GATED" in rule, "an un-armed ceiling must announce itself"
    assert "recall@5" in rule, "the rule must say how the number is computed"


def test_the_report_echoes_the_frozen_observable():
    report = _shadow.evaluate(sample(3))
    assert report["thresholds"] == dict(_shadow.PROMOTION)
    assert report["arming_rule"] == _shadow.MISS_CEILING_RULE


def test_the_verdict_uses_the_frozen_values_rather_than_a_copy_of_them(monkeypatch):
    """If the reader carried its own literals, tightening the observable would not
    change what it says — which is exactly the drift that makes a reading fake."""
    data = miss_lines(N, missing=20)  # 10% misses
    monkeypatch.setitem(_shadow.PROMOTION, "max_v2_miss_rate", 0.10)
    assert _shadow.evaluate(data)["verdict"] == "met"
    monkeypatch.setitem(_shadow.PROMOTION, "max_v2_miss_rate", 0.05)
    assert _shadow.evaluate(data)["verdict"] == "not met"
    monkeypatch.setitem(_shadow.PROMOTION, "max_p95_shadow_ms", 1.0)
    assert _shadow.evaluate(data)["conditions"]["p95_within_budget"]["verdict"] == "not met"


# --- an un-armed ceiling is loud, never a pass ------------------------------


def test_an_unarmed_miss_ceiling_never_reads_as_a_pass():
    """The ruling's explicit half: report the miss rate, but never let an ungated
    dimension turn into a green light by omission."""
    report = _shadow.evaluate(miss_lines(N, missing=0))
    assert report["conditions"]["v2_miss_rate"]["verdict"] == "not armed"
    assert report["conditions"]["v3_only_never"]["verdict"] == "met"
    assert report["verdict"] == "cannot conclude"
    assert "not gated" in " ".join(report["reasons"]).lower()


def test_arming_the_ceiling_is_what_makes_a_clean_sample_met(armed):
    report = _shadow.evaluate(miss_lines(N, missing=0))
    assert report["conditions"]["v2_miss_rate"]["verdict"] == "met"
    assert report["verdict"] == "met"


def test_the_arming_rule_travels_with_every_reading():
    rendered = _shadow.render(_shadow.evaluate(miss_lines(N, missing=0)))
    assert "not armed" in rendered
    assert "NOT GATED" in rendered
    assert "holdout" in rendered


# --- fabrication and misses are separable ----------------------------------


def test_the_miss_ceiling_is_inclusive_and_one_miss_past_it_fails(armed):
    at = _shadow.evaluate(miss_lines(N, missing=20))  # 20/200 = 0.10
    assert at["conditions"]["v2_miss_rate"]["value"] == pytest.approx(0.10)
    assert at["conditions"]["v2_miss_rate"]["verdict"] == "met"

    over = _shadow.evaluate(miss_lines(N, missing=21))  # 0.105
    assert over["conditions"]["v2_miss_rate"]["value"] == pytest.approx(0.105)
    assert over["conditions"]["v2_miss_rate"]["verdict"] == "not met"
    assert over["verdict"] == "not met"


def test_a_recall_regression_is_not_a_fabrication(armed):
    """The whole point of the split: missing everything v2 had is a recall failure, and
    it must not read as the safety failure the observable treats as decisive."""
    report = _shadow.evaluate(miss_lines(N, missing=N))
    assert report["conditions"]["v2_miss_rate"]["verdict"] == "not met"
    assert report["conditions"]["v3_only_never"]["verdict"] == "met"
    assert report["verdict"] == "not met"


def test_fabrication_fails_even_when_the_miss_rate_is_perfect(armed):
    data = miss_lines(N, missing=0)
    data[5] = line(5, v2=["a0005"], v3=["a0005", "mem_fabricated"])
    report = _shadow.evaluate(data)
    assert report["conditions"]["v2_miss_rate"]["verdict"] == "met"
    assert report["conditions"]["v3_only_never"]["verdict"] == "not met"
    assert report["verdict"] == "not met"


def test_a_violation_outranks_an_underfilled_sample():
    """`cannot conclude` must not hide a real failure: 3 turns with a fabricated hit is
    `not met`, so the reading cannot drift into "we just need more data"."""
    report = _shadow.evaluate(sample(3, v3=["mem_fabricated"]))
    assert report["conditions"]["v3_only_never"]["verdict"] == "not met"
    assert report["conditions"]["min_turns"]["verdict"] == "not met"
    assert report["verdict"] == "not met"


def test_one_turn_short_is_cannot_conclude_never_a_pass(armed):
    short = _shadow.evaluate(miss_lines(N - 1, missing=0))
    assert short["verdict"] == "cannot conclude"
    assert short["conditions"]["min_turns"]["verdict"] == "not met"
    assert _shadow.evaluate(miss_lines(N, missing=0))["verdict"] == "met"


# --- the denominator, and no fake zero -------------------------------------


def test_an_empty_store_reads_as_no_signal_not_as_a_zero_miss_rate():
    """The trap P0c would otherwise walk into: the live store holds zero facts, so v2
    injects nothing, and a naive rate is 0/0 -> 0% -> met."""
    report = _shadow.evaluate(sample(N))
    assert report["conditions"]["v2_miss_rate"]["verdict"] == "no signal"
    assert report["conditions"]["v2_miss_rate"]["value"] is None
    assert report["verdict"] == "cannot conclude"
    assert "no signal" in " ".join(report["reasons"]).lower()


def test_the_miss_rate_is_id_level_over_the_ids_v2_injected():
    """Declared, not inferred: ids v3 dropped / ids v2 injected.

    The numbers are chosen so the three candidate definitions **disagree** — id-level
    4/7, turn-level 2/3, symmetric 2/3. A fixture with one id per turn makes all three
    equal, and then this test passes with the definition silently swapped: that is exactly
    how the first version of it let two mutations through.
    """
    data = [
        line(0, v2=["a", "b", "c", "d"], v3=["a"]),   # 4 injected, 3 missed
        line(1, v2=["x", "y"], v3=["x"]),             # 2 injected, 1 missed
        line(2, v2=["z"], v3=["z"]),                  # 1 injected, 0 missed
        line(3),                                      # no injection at all
    ]
    condition = _shadow.evaluate(data)["conditions"]["v2_miss_rate"]
    assert condition["missed_ids"] == 4
    assert condition["injected_ids"] == 7
    assert condition["value"] == pytest.approx(4 / 7)
    assert condition["value"] != pytest.approx(2 / 3), (
        "id-level and turn-level must be distinguishable in this fixture"
    )
    # The turn-level fraction is reported beside it, not used for the verdict.
    assert condition["turns_with_injection"] == 3
    assert condition["turns_with_a_miss"] == 2


def test_the_retired_symmetric_rate_is_still_reported_for_comparability():
    """The 37.5% finding was measured with the symmetric definition; a reader must be
    able to line the two up instead of trusting a restatement."""
    report = _shadow.evaluate(miss_lines(N, missing=20))
    assert report["context"]["divergence_rate_symmetric"] == pytest.approx(0.10)
    assert report["context"]["divergence_shape"] == {"v3_missed": 20, "v3_added": 0}
    assert "max_divergence_rate" not in report["thresholds"]


# --- the biases travel with the numbers ------------------------------------


def test_a_stale_copy_blocks_an_otherwise_clean_reading(armed):
    data = miss_lines(N, missing=0)
    data[7] = line(7, v2=["a0007"], v3=["a0007"], age=1200.0, stale=True)
    report = _shadow.evaluate(data)
    assert report["conditions"]["copy_within_bound"]["verdict"] == "not met"
    assert report["verdict"] == "not met"


def test_a_stale_flag_that_disagrees_with_the_bound_is_not_trusted(armed):
    """The writer marks staleness from the same constant; if the two diverge the sample
    cannot be read as fresh. Both directions, because a test covering only the age side
    passes with the cross-check deleted."""
    late_but_unflagged = miss_lines(N, missing=0)
    late_but_unflagged[9] = line(9, v2=["a0009"], v3=["a0009"], age=1200.0, stale=False)
    report = _shadow.evaluate(late_but_unflagged)
    assert report["conditions"]["copy_within_bound"]["verdict"] == "not met"
    assert "stale flag" in " ".join(report["reasons"]).lower()

    flagged_but_fresh = miss_lines(N, missing=0)
    flagged_but_fresh[11] = line(11, v2=["a0011"], v3=["a0011"], age=10.0, stale=True)
    second = _shadow.evaluate(flagged_but_fresh)
    assert second["conditions"]["copy_within_bound"]["verdict"] == "not met"
    assert "stale flag" in " ".join(second["reasons"]).lower()


def test_the_caveat_is_printed_next_to_the_miss_number(armed):
    rendered = _shadow.render(_shadow.evaluate(miss_lines(N, missing=20)))
    assert _shadow.CAVEAT in rendered
    assert [ln for ln in rendered.splitlines() if "miss rate" in ln], (
        "the render must show the miss condition"
    )


# --- fabrication citations, without the conversation ----------------------


def test_v3_only_is_never_a_pass_and_cites_its_line_without_the_query_text():
    data = miss_lines(N, missing=0)
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


def test_a_recorded_divergence_that_disagrees_with_the_ids_is_not_trusted(armed):
    data = miss_lines(N, missing=0)
    data[3] = line(3, v2=["same"], v3=["same"], divergence=["same"])
    report = _shadow.evaluate(data)
    assert report["conditions"]["v2_miss_rate"]["verdict"] == "not met"
    assert "inconsistent" in " ".join(report["reasons"]).lower()


# --- the off-turn cost -----------------------------------------------------


def test_p95_is_nearest_rank_and_prints_p50_and_max(armed):
    """One stray slow sample with a low p50 must read as noise, not as a failure —
    the tell `perf-smoke` learned the hard way."""
    data = miss_lines(N, missing=0)
    data[0] = line(0, v2=["a0000"], v3=["a0000"], ms=900.0)
    budget = _shadow.evaluate(data)["conditions"]["p95_within_budget"]
    assert budget["max"] == pytest.approx(900.0)
    assert budget["value"] == pytest.approx(40.0)
    assert budget["verdict"] == "met"
    assert budget["p50"] <= budget["value"] <= budget["max"]


def test_p95_above_the_ceiling_is_not_met(armed):
    data = miss_lines(N, missing=0)
    for index in range(12):  # > 5% of the sample, so nearest-rank p95 lands inside them
        data[index] = line(index, v2=[f"a{index:04d}"], v3=[f"a{index:04d}"], ms=400.0)
    report = _shadow.evaluate(data)
    assert report["conditions"]["p95_within_budget"]["verdict"] == "not met"
    assert report["verdict"] == "not met"


# --- unreadable lines are counted, not dropped ----------------------------


def test_malformed_lines_are_counted_and_block_a_pass(armed):
    data = miss_lines(N, missing=0)
    del data[5]["shadow_ms"]      # a truncated write
    data.append("not an object")  # a half line
    report = _shadow.evaluate(data)
    assert report["sample"]["malformed"] == 2
    assert report["sample"]["usable"] == N - 1
    assert report["verdict"] == "cannot conclude"


# --- margin and findings --------------------------------------------------


def test_every_gated_number_shows_its_margin(armed):
    """A pass/fail alone hides how close the run was: the owner asked for margin."""
    report = _shadow.evaluate(miss_lines(N, missing=20))
    for name in ("min_turns", "copy_within_bound", "v2_miss_rate", "p95_within_budget"):
        assert "margin" in report["conditions"][name], name
    assert report["conditions"]["v2_miss_rate"]["margin"] == pytest.approx(0.0)

    over = _shadow.evaluate(miss_lines(N, missing=40))
    assert over["conditions"]["v2_miss_rate"]["margin"] < 0


def test_an_unarmed_condition_shows_no_margin_because_it_gates_nothing():
    condition = _shadow.evaluate(miss_lines(N, missing=20))["conditions"]["v2_miss_rate"]
    assert condition["verdict"] == "not armed"
    assert "margin" not in condition
    assert condition["value"] == pytest.approx(0.10), "reported, whether or not it gates"


def test_a_rate_margin_is_printed_in_points_not_a_bare_fraction(armed):
    """`margin: -0.28` beside a percentage is a readability bug in the one tool whose
    job is readability. The 240-turn run is what showed it."""
    assert _shadow.PROMOTION["max_v2_miss_rate"] == pytest.approx(0.10)  # the `armed` fixture
    rendered = _shadow.render(_shadow.evaluate(miss_lines(N, missing=75)))  # 37.5% vs 10%
    assert "-27.50 pts" in rendered
    assert "margin: -0.28" not in rendered


def test_findings_cite_ids_and_lines_and_never_the_question(armed):
    data = miss_lines(N, missing=1)
    data[7] = line(7, v2=["kept", "missed"], v3=["kept"], query=SECRET_QUERY)
    report = _shadow.evaluate(data)

    assert {"line": 8, "v2_ids": ["kept", "missed"], "v3_ids": ["kept"]} in (
        report["findings"]["misses"]
    )
    rendered = _shadow.render(report)
    assert "line 8" in rendered and "missed" in rendered
    assert SECRET_QUERY not in rendered
    assert SECRET_QUERY not in json.dumps(report)


# --- the reader and the writer agree, on real lines -----------------------


def test_the_reader_understands_the_lines_the_writer_writes(tmp_path, monkeypatch, live_db):
    """Schema coupling, pinned end to end: these lines come from `_shadow.run`, not from
    this file's idea of the shape, so a writer change the reader did not follow makes
    every line unreadable here instead of reporting zero turns."""
    copy = tmp_path / "shadow" / "memory.db"
    monkeypatch.setenv(_shadow.SHADOW_ENV, str(copy))
    lines_path = tmp_path / "divergence.jsonl"

    for _ in range(3):
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
    assert set(report["conditions"]) == CONDITIONS
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


def test_the_report_writes_nothing(tmp_path, armed):
    log = tmp_path / "divergence.jsonl"
    log.write_text("".join(json.dumps(i) + "\n" for i in miss_lines()), encoding="utf-8")
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


def test_the_exit_code_carries_the_verdict(tmp_path, capsys, monkeypatch):
    def run_and_code(lines_data: List[Dict[str, Any]], tag: str) -> int:
        log = tmp_path / f"div-{tag}.jsonl"
        log.write_text("".join(json.dumps(i) + "\n" for i in lines_data), encoding="utf-8")
        return _shadow.main(["report", "--log", str(log)])

    monkeypatch.setitem(_shadow.PROMOTION, "max_v2_miss_rate", 0.10)
    assert run_and_code(miss_lines(N, missing=0), "met") == 0
    assert run_and_code(miss_lines(N, missing=N), "misses") == 1

    broken = miss_lines(N, missing=0)
    broken[1] = line(1, v2=["x"], v3=["y", "z"])  # a fabricated hit
    assert run_and_code(broken, "fabrication") == 1

    monkeypatch.setitem(_shadow.PROMOTION, "max_v2_miss_rate", None)
    assert run_and_code(miss_lines(N, missing=0), "unarmed") == 2
    assert run_and_code(sample(10), "short") == 2


def test_json_output_is_the_report_verbatim(tmp_path, capsys, armed):
    log = tmp_path / "divergence.jsonl"
    log.write_text("".join(json.dumps(i) + "\n" for i in miss_lines()), encoding="utf-8")

    assert _shadow.main(["report", "--log", str(log), "--json"]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed) == _shadow.report(log)
