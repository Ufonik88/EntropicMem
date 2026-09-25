# EntropicMem eval framework

Scenario-driven measurement of the retrieval pipeline (`memory_engine` + the
Hermes provider prefetch path). Built in EM-001 as the S0 "measure before
touching" gate: the v2 defects must show up in the numbers.

## Quick start

```bash
python -m evals run --suite ci --adapter v2
python -m evals run --suite ci --adapter v2 --compare evals/baselines/v2.8.0-ci.json
```

`run` scores every scenario in the suite, writes
`evals/results/<suite>-<git-sha>.json` (generated, gitignored) and prints a
Markdown metrics table. With `--compare <baseline.json>` it also prints
per-metric deltas and exits **1** if any gated metric regressed by more than
0.02 (§6.3 — the hard CI gate). Gated: `recall@5`, `ndcg@5`,
`abstain_correct`, `noise_rate`, `must_not_ok` (`evals.runner.GATED_METRICS`);
the other metrics are shown, marked `info` when they worsen (`prefetch_tokens`
belongs to the token/perf budgets and `latency_ms` is runner noise). Absolute §6.3 thresholds
(`recall@5 >= 0.75`, `noise_rate <= 0.25`, `abstain_correct >= 0.90`) are
printed as warnings pre-2.8.0: S0's job is measuring the known-broken v2
baseline, and those numbers are S1+ fix targets.

## Suites

| suite  | dataset                    | contract |
|--------|----------------------------|----------|
| `ci`   | `datasets/ci.jsonl`        | fast (≤ 60 s wall), deterministic, **no ML/network deps** — the v2 adapter forces `sentence_transformers`/`torch` off for the whole process (`evals/adapters/engine_v2.force_no_embeddings`), so it is stdlib-fast even on interpreters that have the ML stack installed. |
| `full` | `datasets/ci.jsonl` + `datasets/full.jsonl` | adds the vector backend when installed (embeddings allowed; run in the `vectors` CI job, plan line 1269). |
| `external` | (reserved)             | EM-006 (LiveMem etc.). |

## Dataset format (JSONL, one scenario per line)

```json
{"id":"temporal_aged_identity_01","category":"ageing",
 "memories":[{"content":"...","kind":"profile","age_days":120,"importance":0.9,"domain":"People","scope_user":""}],
 "noise":{"generator":"filler","count":300,"seed":7},
 "turns":[{"query":"where does the user live?","expect_ids":["$0"],
           "expect_substrings":["Riverton"],"must_not":["$noise"]}]}
```

`$N` references the N-th scenario memory; `$noise` means any noise memory.
`age_days` is applied by backdating `created_at/updated_at/last_accessed`
(v2 adapter). Personas, places and content are synthetic (public-repo rule).

## Metrics (per query, averaged per category and overall)

`recall@5`, `mrr`, `ndcg@5`, `abstain_correct` (empty `expect_ids`: 1 iff no
memories injected), `noise_rate@prefetch` (fraction of injected bullets that
are noise), `substring_hit`, `must_not_ok`, `prefetch_tokens` (estimated),
`latency_ms`.

## Adapters

`AdapterBase`: `load(scenario) -> EvalHandle`, `search(handle, query, k)`,
`prefetch(handle, query) -> str`. `engine_v2` drives the real
`MemoryEngine` + provider against a temp `HERMES_HOME`, one scenario per
fresh DB. `engine_v3` arrives with S2.

## Tests

`tests/evals/` — metric math on hand-computed examples (`test_metrics.py`),
dataset resolution, runner scoring, the v2 adapter, the CLI, and the suite
budget guards (`test_ci_budget.py`: ci wall clock ≤ 60 s and the ML stack
never imported; `test_ci_lockdown.py`: the embedding lockdown mechanism).

## Baselines

`evals/baselines/*.json` are committed (tracked via `!.gitignore` negation);
`evals/results/` stays generated and ignored. Each release commits
`v<version>-ci.json` (the `evals-ci` gate) and `v<version>.json` (hard suite),
generated at the release commit; older baselines stay for comparison
(`v2.7.0*` = pre-S1).
