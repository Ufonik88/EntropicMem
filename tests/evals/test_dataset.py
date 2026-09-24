"""Scenario dataset loading and $-reference resolution."""
import pytest
from evals import dataset


def _write(tmp_path, lines):
    p = tmp_path / "scen.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


GOOD = (
    '{"id":"s1","category":"ageing",'
    '"memories":[{"content":"The user lives in Riverton","kind":"profile",'
    '"age_days":120,"importance":0.9,"domain":"People","scope_user":""}],'
    '"noise":{"generator":"filler","count":5,"seed":7},'
    '"turns":[{"query":"where does the user live?","expect_ids":["$0"],'
    '"expect_substrings":["Riverton"],"must_not":["$noise"]}]}'
)


def test_load_parses_scenario(tmp_path):
    s = dataset.load_scenarios(_write(tmp_path, [GOOD]))
    assert len(s) == 1
    sc = s[0]
    assert sc.scenario_id == "s1"
    assert sc.category == "ageing"
    assert sc.memories[0].age_days == 120
    assert sc.noise.count == 5 and sc.noise.seed == 7
    assert sc.turns[0].expect_ids == ["$0"]
    assert sc.turns[0].must_not == ["$noise"]


def test_load_skips_blank_lines_and_comments(tmp_path):
    p = _write(tmp_path, ["# comment line", "", GOOD, ""])
    s = dataset.load_scenarios(p)
    assert len(s) == 1


def test_reference_resolution_memory_ref(tmp_path):
    sc = dataset.load_scenarios(_write(tmp_path, [GOOD]))[0]
    t = sc.turns[0]
    real_ids = {"$0": "abc123"}
    noise_ids = {"n1", "n2"}
    resolved = dataset.resolve_refs(t.expect_ids, real_ids, noise_ids)
    assert resolved == ["abc123"]


def test_reference_resolution_noise_expands_to_all(tmp_path):
    real_ids = {"$0": "abc123"}
    noise_ids = {"n1", "n2"}
    out = dataset.resolve_refs(["$noise"], real_ids, noise_ids)
    assert set(out) == {"n1", "n2"}


def test_reference_resolution_unknown_ref_raises(tmp_path):
    with pytest.raises(dataset.ScenarioError):
        dataset.resolve_refs(["$9"], {"$0": "x"}, set())


def test_load_rejects_duplicate_ids(tmp_path):
    p = _write(tmp_path, [GOOD, GOOD])
    with pytest.raises(dataset.ScenarioError):
        dataset.load_scenarios(p)


def test_load_rejects_bad_ref_format(tmp_path):
    p = _write(tmp_path, ["$0"])
    with pytest.raises(dataset.ScenarioError):
        dataset.load_scenarios(p)


def test_ci_suite_dataset_files_exist_and_load():
    from evals.datasets import ci_suite_path

    scen = dataset.load_scenarios(ci_suite_path())
    assert len(scen) >= 3
    ids = {s.scenario_id for s in scen}
    assert len(ids) == len(scen)
    # every category referenced by the CI gates is represented
    cats = {s.category for s in scen}
    assert {"ageing", "abstention", "noise", "update"} <= cats
