# P0c — the readout (2026-10-30)

The promotion observable (§ the shadow contract, `_shadow.PROMOTION`) was frozen before
collection and its shape ruled by the owner **before a single real turn was read** —
which is the only circumstance in which changing it is not fitting it to the sample.
This page reads the verdict against the frozen thresholds, honestly, including the
parts that failed.

## Sufficiency and the sample

- **327 usable turns against the 200 floor — met, with margin.** Collection window
  2026-10-29T19:41Z → 2026-10-30T11:30Z (Hermes's host, build 3.0.0, one writer tree,
  13 lines excluded as other-build, 0 malformed, 0 "v3 shadow is failing" warnings
  since collection start).
- The `200+ real turns` condition the P0c was gated on is **satisfied**; this readout
  is the handback.

## The verdict: **not met** — three behavioural conditions fail

Every number below is from the live-log report on the final collection build; the raw
distributions live beside it (to be attached from the handback artifacts).

| Condition | Measured | Frozen threshold | Verdict |
|---|---|---|---|
| copy age | p95 874.3 s, max 885.4 s | ≤ 900 s | **met (tight)** |
| v3 never fabricates | 260 lines | ceiling 0 | **not met** |
| v2 misses | 798 of 798 injected (rate 1.0) | ≤ 0.107143 | **not met** |
| p95 retrieval-only shadow cost | 24 644.15 ms (p50 3 175.63, max 25 275.98, **293 non-refresh turns**) | ≤ 150 ms | **not met** |

The pre-declared reading of **NOT MET** with sufficiently met is a finding, not a tuning
opportunity: the thresholds do not move after the data is in. The cutover gate applies
as armed:

> **The cutover does not go.** The store stays v2-served unchanged; no `memory upgrade`
> runs; nothing restarts. **(Hermes was instructed to stand down immediately on the
> handback — confirmation not yet received at the time of writing.)**

## What the failures attribute to (pending the handback artifacts)

1. **The shadow ran with no query embedding, so v3 served lexical/entity/episodic only.**
   The writer's recorded caveat is that the semantic band of v3's retrieval was inert and
   the divergence is therefore a *lower bound*. This is the load-bearing context for both
   miss-side numbers — but it is **not, by itself, neutralizing**, because one question it
   does not answer is: *would the production cutover have an embedding?* If the host's
   provider config ships a semantic backend, the shadow measured a degraded stand-in and
   the readout proposes re-arming the P0c with the embedding on. If it does **not**, the
   cutover would serve v3 exactly as measured here and the miss-rate result is the
   production risk itself. **This is the decision-fact the readout needs before anything
   else.**
2. **The 24.6 s p95 is tail-only and unattributed so far.** The refresh turns (34) are
   already excluded (chunk 62); the remaining tail is the shadow's own in-turn machinery,
   which production does not run — but the budget the observable names (§4.2) is a dev-box
   figure. Direct retrieval on the same box measured 0.55–0.82 s earlier, so the tail is
   dominated by something other than retrieval as such — likely the embedding-attempt path
   (ask/timeout) — and the timed sample requested from Hermes is what turns that from a
   suspicion into an attribution.
3. **The 260 fabrication-read lines must be read refined vs unrefined** (`refined` and
   `extras_resolved` are in the report JSON — artifact `a` from the handback). With the
   copy present the refinement should resolve real v3 ids into `extras_resolved`
   (reported, never gated) and leave fabrication at what cannot resolve. If the read says
   all 260 count *because the read ran unrefined*, the fabrication condition may not be
   the real failure; if it says they count **refined**, that is a hard-safety finding that
   cannot sit under any context.
4. **Gatemix travels with the verdict** (the report-shape landing): abstain 51 /
   no-candidates 14 / pass 262 over 327 usable — the earlier abstain-heavy shape inverted
   once daytime user traffic returned; the miss-rate denominator (262 turns + 14
   no-candidates = 276) is no longer thin.

## What happens next, in order

1. Handback artifacts land (report JSON + sanitized line dump + the timed sample) —
   questions 1–3 above close.
2. The readout goes to the owner **with the NOT MET verdict as the headline** and the
   root-cause attribution attached. No threshold changes; a re-armed P0c (if proposed)
   must be pre-declared *before* any new collection, exactly as this one was.
3. The cutover stays gated on a verdict that reads a clean go — either from a legitimate
   resolution of the attribution questions, or from a re-armed pre-declared run.
4. Recorded alongside (non-blocking): the gateway's exported `ENTROPICMEM_*` env breaks
   21 wiring tests on the host (Finding 1) — a tests/conftest.py hermeticity fixture is
   the fix, landed here rather than there so the suite-surface figures dance stays in one
   place.
