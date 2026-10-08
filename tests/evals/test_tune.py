"""EM-306 — the calibration harness's fixed pieces, and the committed calibration.

The tuning itself runs offline; what CI checks is that the *rules* cannot drift: the
split is by id hash and order-independent, the objective is the card's formula, the grid
is pre-declared and contains the spec candidate, and the committed result file still
describes the current suite, derives its arming number from v2's holdout recall, and
matches ``em/config.py`` (which links it back).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from evals import dataset as dataset_mod  # noqa: E402
from evals import datasets, tune  # noqa: E402


def _hard_scenarios():
    return [
        scenario
        for path in datasets.suite_paths("hard")
        for scenario in dataset_mod.load_scenarios(path)
    ]


@pytest.fixture(scope="module")
def committed():
    from em import config

    path = REPO / config.RESULT_FILE
    assert path.is_file(), f"em/config.py links {config.RESULT_FILE}, which does not exist"
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_split_is_by_id_hash_not_by_order():
    scenarios = [SimpleNamespace(scenario_id=f"s{index}") for index in range(50)]
    dev_a, holdout_a = tune.split_by_id_hash(scenarios)
    dev_b, holdout_b = tune.split_by_id_hash(list(reversed(scenarios)))
    assert {s.scenario_id for s in dev_a} == {s.scenario_id for s in dev_b}
    assert {s.scenario_id for s in holdout_a} == {s.scenario_id for s in holdout_b}


def test_the_split_partitions_the_hard_suite():
    scenarios = _hard_scenarios()
    dev, holdout = tune.split_by_id_hash(scenarios)
    assert len(scenarios) == 60
    assert len(dev) + len(holdout) == 60
    assert not ({s.scenario_id for s in dev} & {s.scenario_id for s in holdout})
    assert dev and holdout, "both sides must be non-empty or the split is useless"


def test_the_committed_result_records_the_same_split(committed):
    dev, holdout = tune.split_by_id_hash(_hard_scenarios())
    assert committed["split"]["dev_ids"] == [s.scenario_id for s in dev]
    assert committed["split"]["holdout_ids"] == [s.scenario_id for s in holdout]


def test_the_objective_is_the_card_formula():
    metrics = {"recall@5": 1.0, "mrr": 0.5, "abstain_correct": 1.0, "noise_rate": 0.25}
    assert tune.objective(metrics) == pytest.approx(0.4 + 0.15 + 0.3 - 0.05)
    with pytest.raises(ValueError):
        tune.objective({"recall@5": None, "mrr": 0.5, "abstain_correct": 1.0, "noise_rate": 0.0})


def test_the_grid_is_pre_declared_and_contains_the_spec_candidate():
    assert set(tune.DEFAULT_GRID) == {"gate.min_score", "gate.min_coverage", "ranking.weights"}
    candidates = tune.expand_grid(tune.DEFAULT_GRID)
    assert len(candidates) == 27
    assert tune.spec_params() in candidates, "the baseline must be one of the candidates"


def test_the_weight_presets_sum_to_one_and_spec_matches_the_dataclass():
    from em.retrieval import fusion

    defaults = fusion.RankWeights()
    spec = tune.RANK_WEIGHT_PRESETS["spec"]
    assert spec == {field: getattr(defaults, field) for field in spec}
    for name, weights in tune.RANK_WEIGHT_PRESETS.items():
        assert sum(weights.values()) == pytest.approx(1.0), name


def test_the_committed_result_derives_the_arming_number_from_v2_holdout(committed):
    v2_recall = committed["holdout"]["v2"]["metrics"]["recall@5"]
    assert committed["v2_miss_rate"] == round(1.0 - v2_recall, 6)
    assert 0.0 <= committed["v2_miss_rate"] < 1.0
    assert committed["split"]["holdout_ids"], "the arming number needs a holdout"


def test_the_chosen_candidate_is_the_dev_best(committed):
    best = max(row["objective"] for row in committed["dev"])
    assert committed["chosen"]["objective"] == pytest.approx(best)
    assert committed["chosen"]["params"] in [row["params"] for row in committed["dev"]]


def test_a_flat_objective_prefers_the_candidate_closer_to_the_spec():
    """The first pass over the grid found a flat tie in the min_score band; the rule
    that keeps a threshold from moving on no evidence is pinned here."""
    spec = {"gate.min_score": 0.30, "gate.min_coverage": 0.34, "ranking.weights": "spec"}
    far = {
        "params": {"gate.min_score": 0.25, "gate.min_coverage": 0.34, "ranking.weights": "importance_heavy"},
        "objective": 0.5,
    }
    near = {
        "params": {"gate.min_score": 0.30, "gate.min_coverage": 0.34, "ranking.weights": "importance_heavy"},
        "objective": 0.5,
    }
    assert min([far, near], key=lambda row: tune._selection_key(row, spec)) is near


def test_the_committed_result_names_a_real_commit(committed):
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{committed['git_sha']}^{{commit}}"],
        cwd=REPO,
        capture_output=True,
    )
    assert probe.returncode == 0, f"the result names {committed['git_sha']}, not a commit"


def test_the_committed_result_names_what_is_deferred(committed):
    assert "EM-303" in committed["deferred"]["per_model_cosine"]
    assert "GENERATOR_WEIGHTS" in committed["deferred"]["generator_weights"]


def test_em_config_matches_the_committed_calibration(committed):
    from em import config

    chosen = committed["chosen"]["params"]
    assert config.GATE_MIN_SCORE == chosen["gate.min_score"]
    assert config.GATE_MIN_COVERAGE == chosen["gate.min_coverage"]
    weights = tune.RANK_WEIGHT_PRESETS[chosen["ranking.weights"]]
    assert config.RANKING_RRF == weights["rrf"]
    assert config.RANKING_IMPORTANCE == weights["importance"]
    assert config.RANKING_RECENCY == weights["recency"]
    assert config.RANKING_CONFIDENCE == weights["confidence"]
    assert config.RANKING_FEEDBACK == weights["feedback"]


def test_the_armed_ceiling_is_the_calibrated_v2_miss_rate(committed):
    """The chain the arming rule names: holdout v2 recall -> this result file ->
    ``_shadow.PROMOTION``. If any link drifts, the armed number is no longer the
    pre-registered one and the test says so."""
    from plugins.entropicmem import _shadow

    assert _shadow.PROMOTION["max_v2_miss_rate"] == pytest.approx(committed["v2_miss_rate"])
    assert str(committed["v2_miss_rate"]) in _shadow.MISS_CEILING_RULE


def test_tune_refuses_a_suite_it_cannot_split():
    args = SimpleNamespace(suite="external", grid=None, k=5, results_dir=None, out=None)
    assert tune.cmd_tune(args) == 2
