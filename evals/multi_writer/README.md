# Two writers, one store

A reproducible measurement of what happens when more than one agent writes about
the same fact and one of them is behind. It exists because the retrieval suites
in this repo are single-writer, and so is the benchmark the public comparison
leans on: LongMemEval's histories are one user's chat history, so its
knowledge-update lane changes a value over time and asks for the newest one. A
*second* writer changing the answer is not what either measures.

```bash
python -m evals.multi_writer                 # markdown table
python -m evals.multi_writer --keys 12 --seed 60828 --json /tmp/mw.json
```

Exit status is 0 whatever the numbers say. This is a measurement of a write
protocol, not a gate; `python -m evals run --suite ci` remains the gate.

## What is measured

Every number comes from the shipped path — `MemoryStore.add`,
`MemoryStore.supersede`, and `em.retrieval.pipeline.retrieve` (the same sequence
`entropicmem_search` runs) — against a temporary v3 store. Nothing is
re-implemented, no LLM judges anything, and the corpus is generated from the seed
so a run reproduces exactly.

Values are synthetic codenames (`alpha-aurora-01`), so "the current value was
served" is a substring test, and a value can never match by coincidence.

## The three protocols

The variable is the **write protocol**. The database, the retrieval weights and
the corpus are identical between runs.

| protocol | what the writers do |
|---|---|
| `append` | every write is a plain `remember`. Nothing is superseded, so every historical value stays `active` and ranking decides. This is the "shared store, newest wins" baseline. |
| `supersede` | a correcting writer supersedes the row it is correcting — what `entropicmem_update` does by default (`mode=supersede`). A writer that re-asserts a dead value is *not* cooperating and is written the way an agent would write it: plain `remember`. |
| `supersede_guard` | `supersede` plus a caller-side check: before a plain write, look for the value in history and skip the write when it is already superseded. Uses only the shipped read surface (`entropicmem_search` with `include_history`); it is a policy an agent can adopt today, not a store feature. |

## The four shapes, and why each exists

| shape | timeline | what it isolates |
|---|---|---|
| `succession` | v1 → v2 → v3, one writer, same phrasing | the control. Plain recency *should* be enough here; if it is not, the corpus is telling you something about the ranking. |
| `pinned_stale` | v1 written as a pinned, high-importance constraint, then corrected | a superseded row is not a candidate at all, so a `pinned=1` old value cannot outvote its own correction. |
| `rogue_echo` | a correction, then a second writer re-asserts the dead value inside new prose that repeats the key | the residual. No store can tell a dead re-assertion from a legitimate one; only a caller-side history check can. |
| `concurrent_conflict` | two writers claim different values half a day apart, nobody corrects | no ground truth exists to score against, so these keys are reported separately: the question is how many values stay live and which one the ranking picks. |

The echo deliberately repeats the key phrase more often than the terse
correction, so it is the better lexical match. That is the failure mode an
evidence-picking step hits — the wrong quote wins on relevance — and a benchmark
that made the stale value obviously worse would be measuring length
normalisation instead.

## The numbers

`seed 60828`, 12 keys (3 per shape), queries asked 30 days after the last
write. Ratios, not percentages. `active stale (n)` is the mean number of dead
values still `active` per scored key.

| protocol | current@1 | current@5 | stale leak@5 | stale > current | served: current | served: stale | active stale (n) | history kept |
|---|---|---|---|---|---|---|---|---|
| `append` | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.89 | 1.33 | 1.00 |
| `supersede` | 0.67 | 1.00 | 0.33 | 0.33 | 0.67 | 0.33 | 0.33 | 1.00 |
| `supersede_guard` | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 1.00 |

Per shape, `current@1`:

| shape | `append` | `supersede` | `supersede_guard` |
|---|---|---|---|
| `succession` | 0.00 | 1.00 | 1.00 |
| `pinned_stale` | 0.00 | 1.00 | 1.00 |
| `rogue_echo` | 0.00 | 0.00 | 1.00 |
| `concurrent_conflict` | — | — | — |

The same ordering holds on seeds 1, 2, 3 and 42: `append` 0.00, `supersede` 0.67,
`supersede_guard` 1.00. The fractions are corpus-specific; the ordering is
not a seed artefact.

## What the numbers say

1. **Without supersede, the ranking serves the stale value first on every scored
   key — including plain succession.** Currency is one 0.10 feature term
   (recency) against a 0.60 RRF term, so when a key's values are lexically
   identical they tie in the generator and the ordering is insertion order. The
   store has no currency signal strong enough to outvote that.
2. **An explicit supersede fixes the two classes it can see.** A superseded row
   is filtered out of every candidate generator (`status='active'`), so neither
   recency, importance nor a pinned flag can resurrect it: 6 of 9 become correct.
3. **The residual is exactly the rogue echo.** A second writer re-asserting a
   dead value in new prose cannot be distinguished from a legitimate update by
   the store, because the text differs and only the value is old. `supersede`
   alone leaves 3 of 9 wrong; the caller-side history check takes it to 0.
4. **Concurrent conflicts stay visible, not resolved.** Two writers making
   different claims half a day apart leave two live values; the ranking serves
   the later write in 12 of 12 here, which is recency deciding an answer, not
   truth. That is the honest boundary: the store's guarantee is that the conflict
   is visible, actor-stamped and auditable, not that it picks the right one.
5. **No protocol loses data.** `history kept` is 1.00 everywhere: superseded
   rows keep their content, `valid_to`, `superseded_by` and version snapshots.

## What this does not test

- **Concurrency.** Writes are serial in one process; this measures contradiction
  and staleness, not SQLite write races or interleaving. A multi-process writer
  harness is a different benchmark.
- **Semantic contradiction.** Two differently-worded facts that mean the same
  thing are not detected; the corpus keeps the key phrase constant so the only
  variable is the value and its age.
- **Embeddings.** Lexical only, to keep the run stdlib-fast and deterministic.
  A vector lane would change the tie behaviour and is not measured here.
- **Abstention.** The gate returned a result on every query in these runs;
  `abstained` is 0.00 and is reported only so a future corpus cannot hide it.
- **Scale.** 12 keys, one SQLite file, one box. It is a mechanism test with
  receipts, not a leaderboard score.
