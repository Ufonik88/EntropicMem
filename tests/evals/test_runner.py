"""Runner scoring/aggregation/compare — exercised through a FakeAdapter."""
import json

from evals import runner
from evals.adapters.base import EvalHandle, Hit
from evals.dataset import Memory, NoiseSpec, Scenario, Turn


def _scenario():
    return Scenario(
        scenario_id="s1",
        category="ageing",
        memories=[
            Memory(content="The user lives in Riverton", age_days=0, importance=0.9),
            Memory(content="The user likes tea", age_days=0, importance=0.5),
        ],
        noise=NoiseSpec(count=3),
        turns=[
            Turn(query="where does the user live?", expect_ids=["$0"],
                 expect_substrings=["Riverton"], must_not=["$noise"]),
            Turn(query="what is the capital of Zululand?", expect_ids=[],
                 must_not=["$noise"]),
        ],
    )


class FakeAdapter:
    """Deterministic adapter: fixed rankings per query."""

    name = "fake"

    def __init__(self, search_ranking, injected_ids, block=""):
        self._ranking = search_ranking
        self._injected = injected_ids
        self._block = block

    def load(self, scenario):
        ref_ids = {f"${i}": f"real{i}" for i in range(len(scenario.memories))}
        noise_ids = {f"noise{i}" for i in range(scenario.noise.count)}
        contents = {f"real{i}": m.content for i, m in enumerate(scenario.memories)}
        contents.update({nid: f"filler noise {n}" for n, nid in enumerate(sorted(noise_ids))})
        return EvalHandle(scenario=scenario, ref_ids=ref_ids, noise_ids=noise_ids,
                          extra={"contents": contents})

    def search(self, handle, query, k=5):
        contents = handle.extra["contents"]
        ids = self._ranking.get(query, [])[:k]
        return [Hit(id=i, content=contents.get(i, f"content-{i}"), score=1.0 - 0.1 * n)
                for n, i in enumerate(ids)]

    def prefetch(self, handle, query):
        contents = handle.extra["contents"]
        ids = self._injected.get(query, [])
        lines = ["## EntropicMem recall"] + [f"- [{i}] {contents.get(i, f'content-{i}')}" for i in ids]
        return "\n".join(lines) if ids else ""


def _score_all(adapter):
    sc = _scenario()
    handle = adapter.load(sc)
    return [runner.score_turn(sc, t, adapter, handle, k=5) for t in sc.turns]


def test_score_turn_hit_query_metrics():
    adapter = FakeAdapter(
        search_ranking={"where does the user live?": ["real1", "real0", "noise0"]},
        injected_ids={"where does the user live?": ["real0"]},
    )
    r = _score_all(adapter)[0]
    # expected = [$0] → real0, found at rank 2 → recall@5 = 1.0, mrr = 0.5
    assert r["recall@5"] == 1.0
    assert r["mrr"] == 0.5
    assert r["abstain_correct"] is None  # not an abstain query
    assert r["noise_rate"] == 0.0        # injected only the expected id
    assert r["substring_hit"] == 1.0
    assert r["must_not_ok"] == 1.0       # no noise bullets injected
    assert r["prefetch_tokens"] > 0
    assert r["latency_ms"] >= 0


def test_score_turn_must_not_violation_flagged():
    adapter = FakeAdapter(
        search_ranking={"where does the user live?": ["real0"]},
        injected_ids={"where does the user live?": ["noise0", "real0"]},
    )
    r = _score_all(adapter)[0]
    assert r["must_not_ok"] == 0.0
    assert r["noise_rate"] == 0.5


def test_score_turn_abstain_query_with_injection_is_wrong():
    adapter = FakeAdapter(
        search_ranking={},
        injected_ids={"what is the capital of Zululand?": ["noise1"]},
    )
    r = _score_all(adapter)[1]
    assert r["abstain_correct"] == 0.0
    assert r["noise_rate"] == 1.0


def test_score_turn_abstain_query_clean_block():
    adapter = FakeAdapter(search_ranking={}, injected_ids={})
    r = _score_all(adapter)[1]
    assert r["abstain_correct"] == 1.0
    assert r["noise_rate"] == 0.0
    assert r["prefetch_tokens"] == 0


def test_score_turn_abstain_query_excludes_ranking_metrics():
    # Empty expect_ids: recall/mrr/ndcg are not defined (None), so abstain
    # turns cannot silently inflate the recall means.
    adapter = FakeAdapter(search_ranking={}, injected_ids={})
    r = _score_all(adapter)[1]
    assert r["recall@5"] is None
    assert r["mrr"] is None
    assert r["ndcg@5"] is None


def test_aggregate_means_and_skips_none():
    rows = [
        {"recall@5": 1.0, "mrr": 0.5, "abstain_correct": None, "noise_rate": 0.0,
         "prefetch_tokens": 10.0, "latency_ms": 1.0, "substring_hit": 1.0, "must_not_ok": 1.0,
         "ndcg@5": 0.63},
        {"recall@5": 0.0, "mrr": 0.0, "abstain_correct": 0.0, "noise_rate": 1.0,
         "prefetch_tokens": 0.0, "latency_ms": 3.0, "substring_hit": 0.0, "must_not_ok": 0.0,
         "ndcg@5": 0.0},
    ]
    agg = runner.aggregate(rows)
    assert agg["recall@5"] == 0.5
    assert agg["abstain_correct"] == 0.0   # only the one non-None row counts
    assert agg["noise_rate"] == 0.5
    assert agg["latency_ms"] == 2.0
    assert agg["n_turns"] == 2


def test_compare_flags_drops_over_threshold():
    base = {"recall@5": 0.80, "noise_rate": 0.10, "mrr": 0.50}
    cur = {"recall@5": 0.75, "noise_rate": 0.14, "mrr": 0.50}
    rows = runner.compare_deltas(base, cur, threshold=0.02)
    flags = {r["metric"]: r for r in rows}
    assert flags["recall@5"]["regressed"] is True    # -0.05 drop
    assert flags["noise_rate"]["regressed"] is True  # +0.04 rise on a lower-is-better metric
    assert flags["mrr"]["regressed"] is False


def test_compare_direction_aware_higher_is_better_defaults():
    assert runner.LOWER_IS_BETTER == {"noise_rate", "prefetch_tokens", "latency_ms"}


def test_render_markdown_table_shape():
    metrics = {"recall@5": 0.75, "mrr": 0.6}
    md = runner.render_markdown("ci", "v2", metrics)
    assert "| metric | value |" in md
    assert "| recall@5 | 0.750 |" in md


def test_run_suite_end_to_end_with_factory(tmp_path):
    adapter = FakeAdapter(
        search_ranking={"where does the user live?": ["real0", "real1"]},
        injected_ids={"where does the user live?": ["real0"]},
    )
    sc = _scenario()
    result = runner.run_suite(
        scenarios=[sc], adapter=adapter, suite="ci", git_sha="deadbeef",
    )
    assert result["suite"] == "ci"
    assert result["adapter"] == "fake"
    assert result["git_sha"] == "deadbeef"
    assert result["by_category"]["ageing"]["n_turns"] == 2
    assert 0.0 <= result["metrics"]["recall@5"] <= 1.0
    out = tmp_path / "ci-deadbeef.json"
    out.write_text(json.dumps(result), encoding="utf-8")
    assert json.loads(out.read_text())["metrics"]["mrr"] >= 0.0
