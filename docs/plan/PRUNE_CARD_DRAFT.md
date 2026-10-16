# DRAFT — the embedding-maintenance prune card (EM-303's orphaned promise)

**Status:** draft for the owner's slotting decision — fold into the cutover card
or its own slot. Promised in EM-303's model-switch hygiene notes
(`CHANGELOG.md` `[Unreleased]` EM-303 entry; `docs/plan/NEXT_CHUNK.md` Part A;
`docs/plan/REMAINING_PLAN.md` §5 EM-303 row; `MASTER_TODO.md` row 28 and the
prune notes): "prune non-current-model vector rows after a completed backfill
for the current model plus a 7-day grace, keeping the current and previous
models, executed by EM-410's maintenance pass." EM-410's card carries no
prune (`REMAINING_PLAN.md` §5 EM-410 row: "Recorded as still owed … did not
ride this card"), and EM-412's does not either — the promise is orphaned. The
plan's EM-209 card already lists `prune` among the job types registered in
S3/S5 (`REMAINING_PLAN.md` §6.2); `KNOWN_JOB_TYPES` does not carry it yet.

## Recommendation — its own card, not folded into the cutover (agent; owner decides)

Fold-in is tempting (both touch the store), but three facts argue for a **separate, destructive card**:

1. **It depends on state the cutover does not create.** The spec's transition record — `meta.embedding_model_previous` and `meta.embedding_model_switched_at`, written by `embed_backfill` on completion — **does not exist yet** (EM-303 wrote only `meta.embedding_model`). Without it the handler must refuse, so a prune folded into a store migration would be a no-op at best; building the record is its own small piece of work.
2. **It is destructive and worker-only.** Its guard tests are the merge gate; folding deletion into the migration card mixes two irreversible acts and gives each no separate green-CI checkpoint.
3. **The size figure is a measurement, not a bound.** ≈2.1 KB/row is from the EM-303 observability pass; re-derive it on a real 10k store before sizing (recipe below) — capacity planning must not treat it as a bound.

**Suggested slot:** its own card, after EM-502/EM-503 (which produce the model switches the prune acts on) and before the cutover's storage sizing; gated on the owner's explicit sign-off, because it deletes.

## Spec

A `prune` job handler — worker thread only, under the EM-209 contract (outside
the write transaction, short transactions through `ctx.store`, idempotent,
heartbeating; no prefetch/agent path imports it) — that deletes `embeddings`
rows for models that are neither the current nor the immediately previous one,
and only once the current model's backfill completed more than
`prune.grace_days` (default 7) ago.

* **Current model** = `meta.embedding_model` (written by `embed_backfill` on
  completion). Its rows are never deleted.
* **Previous model** = the model `meta.embedding_model` named before the last
  completed backfill. Its rows are the rollback set: a bad model switch is
  undone by flipping `meta.embedding_model` back while they still exist.
* **Transition record:** on completion the backfill handler also writes
  `meta.embedding_model_previous` and `meta.embedding_model_switched_at`.
  Without these there is no previous-model identity and no grace clock — the
  prune refuses (no-op, logged) rather than guesses.
* **Grace gates the whole prune.** Deletion runs only when the current model
  is recorded, the transition record exists, and
  `now − switched_at > prune.grace_days`. A partial backfill never authorizes
  deletion. After the grace, one run deletes every row whose model is neither
  current nor previous.
* **Dry run:** payload `{"dry_run": true}` reports the per-model row counts it
  would delete and deletes nothing.
* **Vacuum:** after a real prune's deletes commit, the handler runs `VACUUM`
  on a dedicated autocommit connection (SQLite forbids it inside a
  transaction) to return the pages. Vacuum runs in the worker, never on a
  request path, bounded by the cron budget; a set too large for one budget is
  finished by the next run (the handler is idempotent).
* **Registration:** add `"prune"` to `KNOWN_JOB_TYPES` and a
  `make_prune_handler()` factory (new `em/embeddings/prune.py`) in the shared
  `em/jobs/registry.py` builder, so the CLI worker and the in-process worker
  cannot drift. The backfill handler enqueues one `prune` job on completion
  (dedupe-keyed); `entropicmem worker run --types prune` runs it on demand.

## Acceptance criteria

1. **Current model's rows are never deleted** — any state, dry-run or real.
2. **Previous model's rows are never deleted inside the grace window**; after
   it, they are.
3. **No deletion without a completed backfill** — empty `meta.embedding_model`
   or a missing transition record is a no-op (logged).
4. **Dry-run reports per-model counts and deletes nothing.**
5. **Vacuum runs outside the request path** (worker thread only) and after the
   delete transaction commits.
6. **Idempotent** — a second run deletes nothing more — and follows the EM-209
   contract (heartbeats; permanent vs transient errors; a backend-less or
   read-only box is a clean no-op, never a dead job).

## Test plan — guard tests gate the merge (this is a destructive path)

* Models A (old), B (previous), C (current) seeded; C's backfill completed
  8 days ago → a real prune deletes A's rows only; B and C survive.
* Same seed, backfill completed 3 days ago (inside grace) → nothing is deleted.
* `meta.embedding_model` empty, or no transition record → no deletion, logged.
* Dry-run: counts reported for A (and B after the grace), zero rows deleted.
* Vacuum: asserted to run on the worker thread (spy/thread name), after the
  delete transaction commits.
* Idempotence: a second prune run is a no-op.
* The five owner-required cases above each get their own test.

## The ≈2.1 KB/row figure and how to re-measure it

**≈2.1 KB/row all-in (1.5 KB blob): ≈21 MB per 10k memories per model set
(50k → 106 MB per stale set).** Measured during the EM-303 observability pass
(`514a6a5`, recorded in `60f0d67`); the pass's exact harness was not recorded,
so treat the figure as a **measurement, not a bound**, and re-derive it before
sizing the cutover:

* The blob is a 384-d float32 vector: 384 × 4 = 1,536 B = 1.5 KB (the
  `pack_vector` payload).
* All-in adds the row (`owner_type`/`owner_id`/`model`/`dim`/`content_hash`/
  `created_at`) and the `ix_embeddings_owner_model` index entry: ≈0.6 KB →
  ≈2.1 KB/row.
* Recipe: `SELECT model, COUNT(*) FROM embeddings GROUP BY model`, then page
  accounting (`dbstat` where available, else `page_count × page_size` deltas)
  for the table and its index; divide the old-model set's pages by its row
  count.
* Re-check on a real 10k-memory set before sizing the cutover (standing
  instruction).

## Risks

* **Destructive.** The guard tests above gate the merge; the handler must be
  impossible to run on a request path.
* **The figure is a measurement, not a bound** — re-measure on a real 10k set
  before sizing.
* **Rollback depends on the transition record.** If
  `meta.embedding_model_previous` is missing, the previous model's rows become
  prunable immediately — the handler must refuse rather than delete.
* **Vacuum locks the database.** Worker-only and budget-bounded; a huge stale
  set may need multiple runs (idempotent by construction).
