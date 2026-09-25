"""
Tests for the hard scenario dataset (EM-002).

Validates that the dataset files are well-formed and meet the EM-002
acceptance criteria:
- ≥60 scenarios
- ≥150 queries across ≥12 categories
- all JSON valid, all scenario IDs unique
- the committed JSONL is exactly what gen_hard_scenarios.py generates
- contact data is obviously synthetic (privacy guard)
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HARD_DIR = ROOT / "evals" / "datasets_hard"
GENERATOR = ROOT / "gen_hard_scenarios.py"

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
        with open(fpath, encoding="utf-8") as f:
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
            with open(fpath, encoding="utf-8") as f:
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
                    m = re.fullmatch(r"\$(\d+)", eid)
                    assert m, f"Invalid expect_id '{eid}' in '{s['id']}'"
                    idx = int(m.group(1))
                    assert 0 <= idx < n_memories, (
                        f"expect_id '{eid}' in '{s['id']}' references memory {idx}, "
                        f"only {n_memories} memories exist"
                    )


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_hard_scenarios", GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestHardDatasetGenerator:
    """gen_hard_scenarios.py is the source of truth for datasets_hard/."""

    def test_import_has_no_side_effects(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        before = {p.name: p.stat().st_mtime_ns for p in HARD_DIR.glob("*.jsonl")}
        _load_generator()
        after = {p.name: p.stat().st_mtime_ns for p in HARD_DIR.glob("*.jsonl")}
        assert before == after, "importing the generator rewrote datasets_hard/"
        assert not any(tmp_path.iterdir()), "importing the generator wrote into cwd"

    def test_generator_covers_every_committed_category(self):
        gen = _load_generator()
        committed = {p.stem for p in HARD_DIR.glob("*.jsonl")}
        assert set(gen.datasets) == committed == REQUIRED_CATEGORIES
        assert sum(len(v) for v in gen.datasets.values()) == 60

    def test_regenerate_matches_committed(self, tmp_path):
        gen = _load_generator()
        gen.write(tmp_path)
        for committed in sorted(HARD_DIR.glob("*.jsonl")):
            fresh = tmp_path / committed.name
            assert fresh.exists(), f"generator did not produce {committed.name}"
            assert fresh.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8"), (
                f"{committed.name} drifted from gen_hard_scenarios.py; "
                "run `python3 gen_hard_scenarios.py` and commit the result"
            )

    def test_ageing_previous_fact_is_older_than_current(self):
        """An ageing fixture's superseded fact must predate the current one."""
        gen = _load_generator()
        for s in gen.ageing:
            current, previous = s["memories"][0], s["memories"][1]
            assert "previous" in previous["content"], s["id"]
            assert previous["age_days"] > current["age_days"], (
                f"{s['id']}: previous fact ({previous['age_days']}d) is newer than "
                f"the current one ({current['age_days']}d)"
            )


# Anything shaped like an international phone number, and any email address.
_PHONE_RE = re.compile(r"\+\d[\d\s().-]{5,}\d")
# NANP reserves 555-0100..555-0199 for fiction.
_FICTIONAL_PHONE_RE = re.compile(r"\+1[\s-]?555[\s-]?01\d\d")
_EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
# RFC 2606 reserved domains.
_RESERVED_EMAIL_DOMAIN_RE = re.compile(r"(?:[\w-]+\.)*example\.(?:com|org|net)")


def _privacy_sources():
    return [*sorted(HARD_DIR.glob("*.jsonl")), GENERATOR]


@pytest.mark.parametrize("path", _privacy_sources(), ids=lambda p: p.name)
def test_contact_data_is_obviously_synthetic(path):
    text = path.read_text(encoding="utf-8")
    bad_phones = [m.group() for m in _PHONE_RE.finditer(text)
                  if not _FICTIONAL_PHONE_RE.fullmatch(m.group())]
    bad_emails = [m.group() for m in _EMAIL_RE.finditer(text)
                  if not _RESERVED_EMAIL_DOMAIN_RE.fullmatch(m.group(1))]
    assert not bad_phones, f"{path.name}: use +1 555 01xx for phone numbers: {bad_phones}"
    assert not bad_emails, f"{path.name}: use example.com/.org/.net for emails: {bad_emails}"


def test_privacy_guard_is_not_vacuous():
    """The guard patterns really do catch real-looking contact data."""
    assert _PHONE_RE.search("call +27 82 000 0000 now")
    assert not _FICTIONAL_PHONE_RE.fullmatch("+27 82 000 0000")
    assert _FICTIONAL_PHONE_RE.fullmatch("+1 555 0142")
    assert not _RESERVED_EMAIL_DOMAIN_RE.fullmatch("company.com")
    assert _RESERVED_EMAIL_DOMAIN_RE.fullmatch("example.org")
    total = sum(len(_PHONE_RE.findall(p.read_text(encoding="utf-8"))) for p in _privacy_sources())
    assert total > 0, "no phone numbers scanned; the guard would pass vacuously"
