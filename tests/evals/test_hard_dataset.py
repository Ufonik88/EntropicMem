"""
Tests for the hard scenario dataset (EM-002).

Validates that the dataset files are well-formed and meet the EM-002
acceptance criteria:
- ≥60 scenarios
- ≥150 queries across ≥12 categories
- all JSON valid, all scenario IDs unique
"""
import json
from pathlib import Path

HARD_DIR = Path(__file__).resolve().parent.parent.parent / "evals" / "datasets_hard"

REQUIRED_CATEGORIES = {
    "paraphrase", "ageing", "update", "contradiction", "abstention",
    "temporal", "multi_user", "multimodal", "procedural", "entity",
    "long_content", "scale",
}

EXPECTED_SCENARIOS_PER_CATEGORY = 5
QUERY_COUNT_PER_SCENARIO = 3


def _load_all():
    """Load all scenarios and files from the hard dataset.

    Returns (scenarios, files).
    """
    scenarios = []
    files = sorted(f for f in HARD_DIR.glob("*.jsonl") if not f.name.startswith("placeholder"))
    for fpath in files:
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    scenarios.append(json.loads(line))
    return scenarios, files


class TestHardDatasetCompleteness:
    """EM-002 acceptance criteria: dataset size and coverage."""

    def test_total_scenarios_gte_60(self):
        scenarios, _ = _load_all()
        assert len(scenarios) >= 60, f"Expected >=60 scenarios, got {len(scenarios)}"

    def test_total_queries_gte_150(self):
        scenarios, _ = _load_all()
        total_queries = sum(len(s["turns"]) for s in scenarios)
        assert total_queries >= 150, f"Expected >=150 queries, got {total_queries}"

    def test_all_12_categories_present(self):
        _, files = _load_all()
        found_categories = {f.name.replace(".jsonl", "") for f in files}
        missing = REQUIRED_CATEGORIES - found_categories
        assert not missing, f"Missing categories: {missing}"

    def test_at_least_5_scenarios_per_category(self):
        _, files = _load_all()
        for fpath in files:
            if fpath.name.startswith("placeholder"):
                continue
            cat = fpath.name.replace(".jsonl", "")
            with open(fpath) as f:
                scenarios = [json.loads(line) for line in f if line.strip() and not line.startswith("#")]
            assert len(scenarios) >= EXPECTED_SCENARIOS_PER_CATEGORY, (
                f"Category '{cat}' has {len(scenarios)} scenarios, expected >= {EXPECTED_SCENARIOS_PER_CATEGORY}"
            )


class TestHardDatasetWellFormed:
    """Validate JSON structure and field correctness."""

    def test_all_scenarios_parse_as_json(self):
        scenarios, _ = _load_all()
        # If we got here, all parsed successfully
        assert len(scenarios) > 0

    def test_all_scenario_ids_unique(self):
        scenarios, _ = _load_all()
        ids = [s["id"] for s in scenarios]
        duplicates = set([i for i in ids if ids.count(i) > 1])
        assert not duplicates, f"Duplicate scenario IDs: {duplicates}"

    def test_all_scenarios_have_required_fields(self):
        scenarios, _ = _load_all()
        required_fields = {"id", "category", "memories", "noise", "turns"}
        for s in scenarios:
            missing = required_fields - set(s.keys())
            assert not missing, f"Scenario '{s.get('id', '?')}' missing fields: {missing}"

    def test_all_turns_have_required_fields(self):
        scenarios, _ = _load_all()
        for s in scenarios:
            for t in s["turns"]:
                assert "query" in t, f"Turn in '{s['id']}' missing 'query'"
                assert "expect_ids" in t, f"Turn in '{s['id']}' missing 'expect_ids'"
                assert "expect_substrings" in t, f"Turn in '{s['id']}' missing 'expect_substrings'"
                assert "must_not" in t, f"Turn in '{s['id']}' missing 'must_not'"

    def test_all_memories_have_required_fields(self):
        scenarios, _ = _load_all()
        for s in scenarios:
            for m in s["memories"]:
                assert "content" in m, f"Memory in '{s['id']}' missing 'content'"
                assert "kind" in m, f"Memory in '{s['id']}' missing 'kind'"
                assert "age_days" in m, f"Memory in '{s['id']}' missing 'age_days'"
                assert "importance" in m, f"Memory in '{s['id']}' missing 'importance'"

    def test_queries_per_scenario_is_3(self):
        scenarios, _ = _load_all()
        for s in scenarios:
            assert len(s["turns"]) == QUERY_COUNT_PER_SCENARIO, (
                f"Scenario '{s['id']}' has {len(s['turns'])} turns, expected {QUERY_COUNT_PER_SCENARIO}"
            )

    def test_expect_ids_reference_valid_indices(self):
        scenarios, _ = _load_all()
        for s in scenarios:
            n_memories = len(s["memories"])
            for t in s["turns"]:
                for eid in t["expect_ids"]:
                    assert eid.startswith("$"), f"Invalid expect_id '{eid}' in '{s['id']}'"
                    idx = int(eid[1:])
                    assert idx < n_memories, (
                        f"expect_id '{eid}' in '{s['id']}' references memory {idx}, "
                        f"only {n_memories} memories exist"
                    )
