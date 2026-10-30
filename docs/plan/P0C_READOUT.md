# P0c — the readout (2026-10-30)

The promotion observable (§ the shadow contract, `_shadow.PROMOTION`) was frozen before
collection and its shape ruled by the owner **before a single real turn was read** —
which is the only circumstance in which changing it is not fitting it to the sample.
This page reads the verdict against the frozen thresholds, honestly, including the
parts that failed.

## Sufficiency and the sample

- **330 usable turns against the 200 floor — met, with margin 130** (the snapshot of
  record: 343 lines, 330 usable on build 3.0.0, 13 excluded as other-build, 0 malformed,
  window 2026-10-29T19:41Z → 2026-10-30T12:17Z; 0 "v3 shadow is failing" warnings since
  collection start). Three further abstain-only lines arrived after the 327-turn midday
  read and are included here.
- The `200+ real turns` condition the P0c was gated on is **satisfied**; this readout
  is the handback.

## The verdict: **not met** — three behavioural conditions fail

Every number below is from the live-log report on the final collection build; the raw
distributions live beside it (to be attached from the handback artifacts).

| Condition | Measured | Frozen threshold | Verdict |
|---|---|---|---|
| copy age | p95 874.3 s, max 885.4 s | ≤ 900 s | **met (tight)** |
| v3 never fabricates | **0 lines refined** (`refined=true`; 5 489 v3-only ids all resolve to real, active, in-scope memories — `extras_resolved`, reported, never gated) | ceiling 0 | **met** |
| v2 misses | 798 of 798 injected (rate 1.0; 254 of 304 injection turns with a miss, 50 abstentions) | ≤ 0.107143 | **not met** |
| p95 retrieval-only shadow cost | 24 644.15 ms (p50 3 175.63; **294 non-refresh turn(s)**; refresh turns 36) | ≤ 150 ms | **not met** |

The pre-declared reading of **NOT MET** with sufficiently met is a finding, not a tuning
opportunity: the thresholds do not move after the data is in. The cutover gate applies
as armed:

> **The cutover does not go.** The store stays v2-served unchanged; no `memory upgrade`
> runs; nothing restarts. Hermes was stood down immediately on the handback and has
> confirmed the stop.

**Readout correction (2026-10-30, on the handback artifacts).** An earlier draft of this
page cited a "260-line fabrication read" — that was the **unrefined fail-closed read**
(`--copy /nonexistent` reproduces it exactly: 260 / `extras_resolved` 0 / `refined`
false). With the configured copy the read is **0 fabricated / 5 489 resolved / refined
true**: the safety condition is **met**. The verdict failures are therefore **two**
(miss, p95), not three. The evidence of record is committed beside this page under
[`p0c_evidence/`](p0c_evidence/): `report_conditions.json` (the live report's
thresholds/conditions/distribution/gatemix/reasons — findings omitted, they carry id
samples by design, with the unrefined cross-check recorded), `lines.jsonl` (330
sanitized per-line rows: line/ts/ms/gate/copy_age_s/copy_refreshed — queries and id
lists stripped), and `timed_sample.json` (the retrieval/evaluation attribution and the
p95 burst read).

## What the failures attribute to — closed on the handback artifacts

1. **The shadow ran with no query embedding, and so would the cutover.** The timed
   sample answers the first readout's "would production have one?" directly: the
   **vector generator returns before SQL when query_vector/embedding_model are absent,
   measured 0.0 ms** — no attempt, no backend. The shadow's v3 side served exactly the
   configuration the cutover would serve (lexical/entity/episodic only), so **the miss
   rate is not a shadow artifact.** Re-arming the P0c with embeddings on requires an
   embedding backend to exist first; on this host it does not. Until one does, or the
   miss-rate evidence is otherwise resolved, the v2 engine keeps serving.
2. **The 24.6 s p95 is burst queueing, not retrieval.** 260 of the 294 non-refresh
   turns sit in one 16-minute storm (40+ turns on one process in single-second windows;
   turns 23.8–25.3 s each); the two worst lines replay at **198.6/210.9 ms** against
   24–25 s logged. Retrieval itself is 0.17–0.51 s end-to-end on the copy (v2 recall
   10–22 ms), and the id comparison is < 0.5 ms. **Outside the storm** the p95 is 10.8 s
   over the sampling window's own later bursts (11:20/11:25/11:30Z) and **453 ms with
   turns > 1.5 s dropped** — 54× below the reported p95 and still over the 150 ms
   budget. The condition therefore stays **not met on the quiet-turn figures too**; the
   artifact never decides the verdict either way. A re-armed P0c would also re-declare
   the burst methodology (burst exclusion is *documented before collection*, not read
   out of the data afterwards).
3. **Fabrication was answered, and the answer is "met".** The unrefined fail-closed
   read (260 lines / `extras_resolved` 0) is exactly reproduced by `--copy /nonexistent`;
   with the configured copy the read is **0 fabricated / 5 489 resolved / refined true**.
   The fail-closed property behaved correctly on a missing copy; the real read has the
   copy and is clean.
4. **Gatemix travels with the verdict:** abstain 54 / no-candidates 14 / pass 262 over
   330 usable turns at the snapshot — the earlier abstain-heavy shape inverted once
   daytime user traffic returned; the miss-rate denominator (262 + 14 = 276
   non-abstained turns) is no longer thin.
5. **Sanitized per-line evidence committed beside this page** — one JSON object per
   usable line (line/ts/ms/gate/copy_age_s/copy_refreshed, queries and id lists
   stripped), the live report's `conditions`/`distribution`/`gatemix`/`reasons`, and the
   timed sample. Single-line timings are indicative only: the shared log receives every
   code tree (build filters apply, code-tree identity does not), so per-line costs vary
   by writer — the line/aggregate attribution above rests on the replay measurements.

## What happens next, in order

1. **The readout goes to the owner with the NOT MET verdict as the headline** and this
   page's attribution attached. No threshold changes; a re-armed P0c must be pre-declared
   *before* any new collection, exactly as this one was — and its first precondition
   (an embedding backend on the serving host) is not met.
2. **The cutover stays held** until a verdict reads a clean go.
3. Recorded alongside (non-blocking): the gateway's exported `ENTROPICMEM_*` env breaks
   21 wiring tests on the host (Finding 1) — a tests/conftest.py hermeticity fixture is
   the fix, landed here rather than there so the suite-surface figures dance stays in one
   place.
