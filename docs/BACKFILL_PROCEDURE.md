# EntropicMem: Manual Backfill Procedure

**Locked decision:** existing facts in any profile's canonical store publish via opt-in manual backfill only. Nothing auto-publishes. (Spec: [MULTI_PROFILE_PROVENANCE_SPEC.md](MULTI_PROFILE_PROVENANCE_SPEC.md), backfill section.)

---

## What backfill does

`publish --backfill` emits the profile's non-`secret` facts from the canonical store into the shared log (`shared_facts` / `sync_events`). After backfill, the transactional outbox drains future writes automatically whenever `publish` runs.

An empty shared state before backfill is not a bug. It is the expected pre-backfill condition per the locked decision.

## How to run backfill

```bash
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py publish --backfill
```

Expected result:

- `shared_facts` count matches the canonical store's publishable facts
- `sync_events` contains the emitted backfill batch
- `sync_outbox` retains future writes until `publish` drains them

Idempotency: re-running `publish --backfill` emits nothing new and is safe.

## Ongoing sync

After backfill:

- Run `publish` to drain new outbox rows
- Subscribers run `pull` to receive shared facts into their local `shared_facts` projection
- `recall --scope own|shared|all` selects which projection to search

```bash
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py publish
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py pull
```

## Do not

- Do not run backfill with secrets you do not want in the shared log. `secret` facts are excluded automatically, but review before publishing cross-profile.
- Do not assume empty subscriber stores indicate a sync failure before backfill has run.
- Do not expect deletions to vanish silently: they propagate as tombstones with a new version slot and stay hidden from recall.
