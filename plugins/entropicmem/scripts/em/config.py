"""EM-306's calibration output: the tuned scalars for the v3 retrieval pipeline.

Calibrated 2026-10-08 on the **hard** suite's dev split (70% of the 60 scenarios, by id
hash) against the card's objective. ``RESULT_FILE`` holds the grid, the split ids, the
dev table and the never-optimised holdout numbers; the selected candidate was the
dev-best, and ties prefer the spec — a flat objective never moves a threshold.

**Nothing reads this module yet, and that is deliberate.** ``gate.*`` and ``ranking.*``
reach the pipeline through the provider cards (EM-401–403), and the shadow's miss
ceiling is armed separately from the same result file. Keep this file to scalars: a
loader, precedence rules or a schema is EM-407's, not this module's.
"""

from __future__ import annotations

#: The calibration record this file is derived from — grid, split ids, holdout numbers.
RESULT_FILE = "evals/results/tune-hard-4eb8097.json"

#: `gate.min_score` / `gate.min_coverage` — unchanged from §3.6's defaults. The dev
#: objective was flat across the grid's band, so the spec values stand rather than
#: moving a threshold on no evidence.
GATE_MIN_SCORE = 0.30
GATE_MIN_COVERAGE = 0.34

#: `ranking.*` — the rerank weights. Chosen by the dev objective and confirmed on the
#: holdout: mrr 0.881 against the spec's 0.865, with the same recall and noise.
RANKING_RRF = 0.50
RANKING_IMPORTANCE = 0.25
RANKING_RECENCY = 0.10
RANKING_CONFIDENCE = 0.10
RANKING_FEEDBACK = 0.05
