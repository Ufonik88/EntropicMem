# The re-armed P0c — declared before any new data (2026-11-18)

The standing rule: **a re-armed P0c must be pre-declared before any new
collection**, exactly as the first one was. This page is that pre-declaration.
It is written on the owner's standing delegation of 2026-11-18 ("use your own
logic and do whatever makes the most safe sense") while **no post-3.0.1
collection turn exists**. The previous verdict — the 3.0.1 tree's NOT MET,
with its attribution — stands as recorded in
[`P0C_READOUT.md`](P0C_READOUT.md) and is not re-read under these rules.

Every threshold below is **frozen as of this page**. Nothing here moves after
data exists; an amendment after a window opens is recorded as an amendment and
restarts the window.

## Why a re-arm is declared at all

The 3.0.1 collection's two failing conditions attributed to:

1. **The miss rate (1.0)** — the shadow's v3 side served exactly what the
   cutover would have: lexical-only, because no embedding backend existed on
   the host. A re-arm that measures the same configuration would measure the
   same verdict. This declaration therefore declares the **target
   configuration** (below) — the store the owner would actually cut over to —
   so the shadow's v3 side serves with embeddings.
2. **The p95 (quiet-turn 453 ms against a 150 ms absolute)** — the budget was
   a dev-box figure, and the machine context had to travel with the verdict as
   a caveat. This declaration re-derives the budget in **machine-independent
   form** (below), from the original budget's intent and the 3.0.1 collection's
   *prior* shapes only.

Both changes are made **now, before data**, which is the only circumstance in
which changing an observable is not fitting it to a sample.

## Preconditions — verified before the window opens, not after

| # | Precondition | How verified |
|---|---|---|
| P1 | An embeddings backend is available on the serving host, and the flag is on | `entropicmem doctor` reads `[PASS] embeddings: enabled, backend '…' available` (the readiness section landed with this declaration) |
| P2 | **The owner's explicit word on the flag flip** — a specific word, not the general delegation | The flip is a live-serving change: it turns on semantic recall for the **live v2 engine** using the store's existing ~2,900 `all-MiniLM-L6-v2` rows, and on a v3 store `initialize` queues the model-switch backfill (EM-412). It is reversible (flag off). Recorded here with its consequences so the word is informed |
| P3 | The gateway has been restarted onto the current tree | The writer stamps the current version and the `source` field; the same-minor carve-out tolerates patch-stamp drift, not a stale process |
| P4 | The window | Opens at the flag flip; **72-hour cap**; sufficiency below must be met inside it |

## The target configuration — what the shadow's v3 side serves

- The shadow's v3 copy, with `embeddings.enabled` on, a **local
  `sentence_transformers` backend, model `all-MiniLM-L6-v2`** — the model the
  store's existing rows are stamped with, so they serve with **no fresh
  backfill**. A different model choice is allowed only after the model-switch
  backfill (EM-303's machinery) completes first; the doctor's model-mismatch
  advisory names the requirement.
- An `openai_compat` endpoint is a valid alternative **only** with the owner's
  explicit choice of it (memory text leaves the host) — the local backend is
  the declared default because no data leaves the machine.

## The frozen observable

| Condition | Declared value |
|---|---|
| Sufficiency | ≥ **200** usable real turns inside the window (cron-preamble lines tagged, not scored, `source_split` reported) |
| Copy age | p95 ≤ **900 s** |
| Fabrication | **0** refined lines (hard ceiling; the refined read, `extras_resolved`) |
| Miss rate | ≤ **0.107143** — the armed value, **unchanged** (v2-vs-truth from EM-306's holdout; a policy choice, not an identity) |
| p95 retrieval | the v3 side's **quiet-turn p95 ≤ 10 × the v2 leg's quiet-turn p95**, both measured in the same window on the same host; **floor 150 ms, cap 1000 ms** |

**The p95 budget's derivation, stated plainly.** The original 150 ms was a
dev-box absolute; against the dev box's ~10–15 ms v2 recall its implied ratio
is ~10×. The re-declared form preserves that intent as a **same-run ratio
measured on the serving host** — the machine context no longer travels with
the verdict as a caveat, it *is* the measurement. The original absolute
becomes the floor (on a very fast host a 10× of a trivial v2 leg must not be
a trivially-passing budget), and a 1000 ms cap bounds the worst case. This is
a **policy choice made from prior evidence only** — the 3.0.1 collection's
recorded shapes — before any new data exists.

## The methodology, pre-declared

- **The v2 leg**: a timed sample of the v2 engine's recall on the same store
  copy, in the same window (the 3.0.1 handback's methodology), gives the
  ratio's denominator. The verdict reports both legs' p95 beside the ratio.
- **Burst exclusion, by rule, not by inspection**: any 60-second window holding
  ≥ **30** usable turns is a burst window. Burst turns are counted and reported
  beside the verdict but leave the p95 sample. **A sample whose burst windows
  hold more than half its usable turns reads CANNOT CONCLUDE** (the quiet-turn
  sample is too thin to judge) — not met, not not-met.
- **The version filter**: the **same-minor carve-out** — landed in
  `_shadow._same_minor` together with this declaration, before any new data —
  scores clean `major.minor.patch` stamps in the same minor line across patch
  versions; dev-tree stamps (`3.0.0.dev0`-shaped), other minor lines,
  `unknown` and empty stay excluded, fail-closed as before.
- **The verdict reads against this page as it stood when the window opened.**

## What this page does not authorize

Nothing here flips a flag, installs a backend, restarts a gateway or touches
the live store. P2's owner word is the only act this page asks for; the
cutover itself remains his separate call, and "conditions met" is not
"proceed".
