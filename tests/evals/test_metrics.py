"""Metric math on hand-computed examples (EM-001 spec: tests/evals/test_metrics.py)."""
import math

from evals import metrics


def test_recall_at_k_counts_expected_in_top_k_only():
    # two expected ids; "$0" inside the top 5, "$1" only at rank 6 → 1/2
    hits = ["$0", "n1", "n2", "n3", "n4", "$1"]
    assert metrics.recall_at_k(["$0", "$1"], hits, k=5) == 0.5


def test_recall_at_k_all_present_is_one():
    assert metrics.recall_at_k(["a", "b"], ["b", "x", "a"], k=5) == 1.0


def test_recall_at_k_none_present_is_zero():
    assert metrics.recall_at_k(["a"], ["x", "y", "z"], k=5) == 0.0


def test_recall_at_k_empty_expected_is_vacuous_one():
    # Abstain queries are scored via abstain_correct, not recall; the
    # convention here keeps suite aggregation from dividing by zero.
    assert metrics.recall_at_k([], ["x"], k=5) == 1.0


def test_mrr_first_hit_at_rank_3():
    # expected "b" at rank 3 → 1/3
    assert math.isclose(metrics.mrr(["b"], ["x", "y", "b", "z"]), 1 / 3)


def test_mrr_takes_best_rank_over_multiple_expected():
    # "a" rank 2, "b" rank 1 → 1/1 (first expected found wins)
    assert metrics.mrr(["a", "b"], ["b", "a"]) == 1.0


def test_mrr_no_hit_is_zero():
    assert metrics.mrr(["a"], ["x", "y"]) == 0.0


def test_ndcg_at_k_single_relevant_at_rank_2():
    # DCG = 1/log2(3), IDCG = 1/log2(2) → 0.6309...
    expected = 1 / math.log2(3)  # discount at rank 2
    ideal = 1.0  # discount at rank 1
    assert math.isclose(metrics.ndcg_at_k(["a"], ["x", "a", "y"], k=5), expected / ideal)


def test_ndcg_perfect_ranking_is_one():
    assert metrics.ndcg_at_k(["a", "b"], ["a", "b", "c"], k=5) == 1.0


def test_ndcg_no_relevant_in_window_is_zero():
    assert metrics.ndcg_at_k(["a"], ["x", "y", "z", "w", "v", "a"], k=5) == 0.0


def test_ndcg_empty_expected_is_one():
    assert metrics.ndcg_at_k([], ["x"], k=5) == 1.0


# ── prefetch-side metrics ────────────────────────────────────────────────


def test_abstain_correct_true_block_is_one():
    assert metrics.abstain_correct(injected_ids=[], expect_ids=[]) == 1.0


def test_abstain_correct_any_injection_is_zero():
    assert metrics.abstain_correct(injected_ids=["x"], expect_ids=[]) == 0.0


def test_abstain_correct_none_when_not_an_abstain_query():
    assert metrics.abstain_correct(injected_ids=["x"], expect_ids=["$0"]) is None


def test_noise_rate_all_noise():
    assert metrics.noise_rate(injected_ids=["n1", "n2"], acceptable_ids={"$0"}) == 1.0


def test_noise_rate_mixed():
    # 3 bullets, one expected → 2/3 noise
    assert math.isclose(
        metrics.noise_rate(injected_ids=["$0", "n1", "n2"], acceptable_ids={"$0"}),
        2 / 3,
    )


def test_noise_rate_empty_injection_is_zero():
    # Abstained: no bullets → no noise.
    assert metrics.noise_rate(injected_ids=[], acceptable_ids=set()) == 0.0


def test_estimate_tokens_rough_quarter_of_chars_plus_markup():
    block = "- [abc123def456] the quick brown fox jumps over the lazy dog\n"
    # content = "the quick brown fox jumps over the lazy dog" (43 chars)
    # 43/4 = 10.75 → 11 ceil, +3 markup per bullet
    assert metrics.estimate_tokens(block) == 14


def test_estimate_tokens_empty_block_is_zero():
    assert metrics.estimate_tokens("") == 0


def test_estimate_tokens_counts_all_bullets():
    line = "- [id1234567890] " + "x" * 40 + "\n"
    # 40/4 = 10 + 3 = 13 per bullet
    assert metrics.estimate_tokens(line + line) == 26
