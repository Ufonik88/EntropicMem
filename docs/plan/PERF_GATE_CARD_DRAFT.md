# EM-608 — the 50k warm-p95 gate's measurement, drafted

**Status: LANDED 2026-10-18 as `3b71cf0` (chunk 37).** Opened 2026-10-18 as a *tracked
defect item*, not a product card: the gate's **measurement** is the defect, not
its budget. The owner slotted it the same day and it was built, landed and merged the
same day — both warm-p95 ACs now read the best of five 20-probe windows via the shared
`tests/harness/perf_stats.py`, and **the 150 ms budget was not touched.** The record:
`CHANGELOG.md` `[Unreleased]`/Fixed, `MASTER_TODO.md`'s chunk-37 row,
`NEXT_CHUNK.md` Part A. The text below is the original draft, kept as the record.

## The defect

`tests/harness/test_prefetch_service_ac.py::test_warm_p95_at_50k_is_under_150ms`
reports a single p95 over 25 probes and fails on it. On a shared runner that
number moves with the host, not with the code. It has now flapped on **unchanged
behaviour** twice in two days, both times on a `main`-push run, both times with
the same SHA green on its branch and green on the rerun.

**Re-running a red `main` job until it goes green is not a fix.** The current
practice is honest but it is still a workaround: the gate's verdict depends on
which runner it lands on, so it does not actually gate.

## The recorded failures

Two instances are verifiable from evidence read at the time. **The owner recalled
three; the third is not retrievable**, and the reason is itself worth recording:
re-running a failed job **overwrites that job's log**, so a failure that was
re-run to green leaves no artifact. A 2026-09-20 → 2026-10-19 sweep of every
failed CI job's log on `main` and its branches returns **zero** warm-p95 hits for
exactly that reason. A flake record must be written down when it happens; GitHub
will not keep it.

| # | When (UTC) | SHA | Leg | p95 | Samples | Runner tell |
|---|---|---|---|---|---|---|
| 1 | 2026-10-16, run `38861052493` | `6e86c98` (EM-406 main push) | `test (3.10)` | **153.35 ms** | all 25 at 117–158 ms | **uniformly inflated** — no slow tail; a contended host |
| 2 | 2026-10-18 ~08:45:56Z, run `39112375641`, job `117631038052` | `bdc1e20` (EM-601 slice 1 main push, re-run) | `test (3.13)` | **151.09 ms** | 24 of 25 under; 135–159 ms, p50 144 | same, 0.7 % over budget |

Both are the **opposite tell** from a real regression: a stall tail would show a
low p50 with one huge max. Here the whole distribution shifts up together. Same
SHA green on branch, green on rerun, and nothing on the prefetch path changed.

Separately, the 2026-10-15 `test (3.13)` numpy-guard flap was a **different
test** (`test_50k_vectors_search_p95_under_25ms_with_numpy`) and was **fixed by
statistic, not re-run** — EM-407's best-of-five 20-probe windows. That fix is the
precedent this card generalises.

## What to build

Reuse the shape that already worked: **a statistic, not a rerun.**

1. **Median over repeated windows, best-of-N** — the exact fix EM-407 applied to
   the numpy guard: run 20 probes × 5 windows, take the **best window's p95**,
   gate on that. Proven on this repo, one test over, and it changes no budget.
2. **A dedicated non-blocking job** is the fallback if (1) is not enough: report
   the number on every run, fail only on a sustained breach (N consecutive runs
   over budget), so one contended host cannot redden a `main` push.
3. **A CI-scaled budget** (budget × runner load, or a relative gate against a
   committed per-runner baseline) is deliberately **not** first choice: it needs a
   calibration story this repo does not have, and a budget that moves is a budget
   nobody trusts.

## Constraints

- **Do not widen 150 ms without the owner.** The number is the AC; the *statistic*
  is what is wrong. If the fix needs a wider budget to pass, that is a finding,
  not a tuning knob — stop and report it.
- Never skip, xfail or delete the test to get green.
- Whatever replaces it must still fail a genuine regression: a best-of-N window
  statistic must be shown (by mutation) to go red when the code actually gets
  slower, not just when the runner is busy.

## Owner ask

**One word: slot EM-608 (or don't).** Until then the current practice stands —
rerun the failed job, never widen the budget — and every instance is recorded in
`MASTER_TODO.md`'s flake list as it happens.
