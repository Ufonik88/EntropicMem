# EntropicMem — Manual Backfill Procedure

**Status:** current as of `v2.5.0`  
**Locked decision:** default profile's existing facts publish via opt-in manual backfill only. Nothing auto-publishes.  
*(Spec ref: `docs/MULTI_PROFILE_PROVENANCE_SPEC.md` §7, LOCKED 2026-08-18)*

---

## What backfill does

`entropicmem publish --backfill` emits the default profile's non-`secret` facts from the canonical store into the shared log (`shared_facts` / `sync_events`). After backfill, the transactional outbox drains future writes automatically when `entropicmem publish` runs.

## Current state (v2.5.0)

- Canonical store: **1,040 facts**
- `sync_outbox`: **904 pending events** (captured by P2's transactional outbox)
- `shared_facts` / `sync_events` / `sync_offsets`: **0** — backfill has never been run
- Per-profile subscriber stores: **empty** — expected until backfill + pull

The empty shared state is **not a bug**. It is the expected pre-backfill condition per the locked decision.

## How to run backfill

```bash
cd /path/to/EntropicMem
entropicmem publish --backfill
```

Expected result:
- `shared_facts` count matches canonical store facts
- `sync_events` contains the emitted backfill batch
- `sync_outbox` retains future writes until `entropicmem publish` drains them

Idempotency: re-running `publish --backfill` emits nothing new and is safe.

## Ongoing sync

After backfill:
- Run `entropicmem publish` to drain new outbox rows
- Subscribers run `entropicmem pull` to receive shared facts
- A 60s cron tick (`entropicmem_cron_publish.py`) is specified in the P2 contract but **not yet wired** — manual `publish` is the current operational path

## Do not

- Do not run backfill with secrets you do not want in the shared log. `secret` facts are excluded automatically, but review before publishing cross-profile.
- Do not assume empty subscriber stores indicate a sync failure before backfill has run.