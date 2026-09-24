"""Metric math for the eval framework (stdlib only).

All functions are pure and operate on abstract ids (scenario memory refs like
"$0", or real entropic ids resolved by the adapter). Ranking conventions:
position 1 = top hit.
"""
from math import log2
from typing import Optional, Sequence, Set


def recall_at_k(expected: Sequence[str], ranked_ids: Sequence[str], k: int = 5) -> float:
    """Share of ``expected`` ids present in the top ``k`` of ``ranked_ids``.

    Empty ``expected`` → 1.0 (vacuously true; abstain scenarios are scored by
    ``abstain_correct`` instead).
    """
    if not expected:
        return 1.0
    topk = set(ranked_ids[:k])
    hits = sum(1 for e in expected if e in topk)
    return hits / len(expected)


def mrr(expected: Sequence[str], ranked_ids: Sequence[str]) -> float:
    """Reciprocal rank of the first expected id found (0.0 when absent).

    Empty ``expected`` → 0.0 by convention: abstain queries are not scored by
    MRR; the runner excludes them from the MRR mean.
    """
    if not expected:
        return 0.0
    want = set(expected)
    for idx, rid in enumerate(ranked_ids, start=1):
        if rid in want:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(expected: Sequence[str], ranked_ids: Sequence[str], k: int = 5) -> float:
    """Binary-relevance NDCG@k (log2 discount, ideal = all expected at top).

    Empty ``expected`` → 1.0, matching ``recall_at_k``'s vacuous convention.
    """
    if not expected:
        return 1.0
    want = set(expected)
    dcg = 0.0
    for idx, rid in enumerate(ranked_ids[:k], start=1):
        if rid in want:
            dcg += 1.0 / log2(idx + 1)
    ideal_n = min(len(want), k)
    idcg = sum(1.0 / log2(i + 1) for i in range(1, ideal_n + 1))
    return dcg / idcg if idcg > 0 else 0.0


def abstain_correct(injected_ids: Sequence[str], expect_ids: Sequence[str]) -> Optional[float]:
    """1.0 if an abstain query (``expect_ids`` empty) injected nothing, else 0.0.

    Returns None when the query is not an abstain query (runner excludes it
    from the abstain mean). §6.2: abstain is about non-pinned injection; with
    no pinned tier in v2, zero injection is the contract.
    """
    if expect_ids:
        return None
    return 1.0 if not injected_ids else 0.0


def noise_rate(injected_ids: Sequence[str], acceptable_ids: Set[str]) -> float:
    """Fraction of injected bullets that are neither expected nor pinned (§6.2).

    Empty injection → 0.0 (abstention is not noise).
    """
    if not injected_ids:
        return 0.0
    noise = sum(1 for i in injected_ids if i not in acceptable_ids)
    return noise / len(injected_ids)


_BULLET_PREFIX = "- ["
_TOKENS_PER_CHAR = 0.25
_BULLET_MARKUP_TOKENS = 3.0


def estimate_tokens(block: str) -> float:
    """Estimate tokens of a rendered prefetch block (stdlib, deterministic).

    Matches the provider's ``- [id] content`` bullet rendering: per bullet,
    ``len(content) / 4`` (ceil) plus 3 tokens of markup; any other line counts
    its characters at the same 4-chars-per-token rate. The debug ``[score:…]``
    suffix is counted as content — it is part of what reaches the model.
    """
    total = 0.0
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith(_BULLET_PREFIX):
            close = stripped.find("] ", len(_BULLET_PREFIX))
            content = stripped[close + 2:] if close != -1 else stripped
            total += -(-len(content) // 4) + _BULLET_MARKUP_TOKENS
        else:
            total += len(stripped) * _TOKENS_PER_CHAR
    return total
