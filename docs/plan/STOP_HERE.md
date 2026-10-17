# STOP HERE — S5 is complete (2026-10-17)

**Development stops at this point.** S5 (formation & consolidation) is complete on
`main`, every change is committed and pushed, and **no development chunk is
queued**. The next actions are owner-gated or belong to a later sprint the owner
has not started. Do not begin new development from this state without the owner.

The S5 code tip is `d331c5e`; the docs reconciliation rides on top of it.

## What S5 delivered

| Card | State | Where |
|---|---|---|
| **EM-501 — the formation LLM backend** | **DONE** (`2a6a892`) | `em/formation/llm.py` — four backends, per-task timeouts, the circuit breaker, the hourly budget, C.1/C.2 parsing on the tiny validator |
| **EM-502 — extraction** | **DONE** (slice 1 `2576dcc`, slice 2 `1f88e8f`) | `em/formation/rules.py`, `extract.py`, `extract_jobs.py`; the CI-gated rule precision ≥ 0.8 on 55 transcripts; the handlers, pending quarantine, the scope-carried write |
| **EM-503 — reconciliation & commit policy** | **DONE** (core `597aac8`, wiring `d331c5e`) | `em/formation/reconcile.py` — the deterministic decider, the C.2 model path, the §3.7 step-3 commit policy, the versioned apply, the neighbour retrieval, the `reconcile` job |
| **§4.1's `sync_turn` transcript capture** | **DONE** (`d331c5e`) | the missing link: a synced turn appends its redacted user/assistant text to `transcript_chunks`, so a sealed window has something to extract |

## The S5 exit criteria — met

1. **With `formation.llm=none` the system still learns and keeps truth.**
   `tests/unit/test_s5_learning_e2e.py` drives the whole rule path (no LLM):
   a preference stated in session 1 is extracted, reconciled, auto-committed and
   **served in session 2 with no explicit `remember` call**. Supersession
   (`SUPERSEDE` for a changed attribute) is pinned by the EM-503 apply tests and
   the supersession end-to-end test.
2. **With an LLM configured, the extraction F1 is reported.**
   `tests/unit/test_em502_extraction.py` measures precision/recall/F1 over the
   extraction dataset through the EM-501 seam. It is **not gated** — a reference
   model is not available on this box — and it is documented as such.
3. **Learning is visible in the harness.** The session-1 → session-2 test above.

## Verification at the stop point

- **CI 3.12: 2754 passed / 4 skipped / 3 xfailed** (11/11 jobs green on the exact
  tip; read from the check-runs API, not `run list`).
- Bare `.venv311`: **2678 / 16 / 3**.
- Digest list in place: **2679 / 15 / 3**.
- CI-equivalent 3.12 (extras + digest): **2756 / 2 / 3**.
- `ruff==0.16.2` clean; the docs guards (document-control, links, cited SHAs, CLI
  drift) green.
- The 3 xfails are the pre-existing `F-004` / `F-008a` / `F-009` in
  `tests/regressions/test_findings_v27.py` — tracked debt, not new failures.

## What remains — owner-gated

- **P0c** — the shadow data: needs a host running the dev-line plugin with
  `ENTROPICMEM_SHADOW_V3` set for ≥ 200 real turns. Owner's environment.
- **The v3 cutover** — owner decides, with **F-004** (full per-user isolation)
  resolved or explicitly accepted in writing first. Plan §9 item 9 has the
  remediation plan and the draft acceptance.
- **Releases, tags, the Hermes catalog re-pin** — including the new logo's
  `image` field, and the `entropicmem_patch_core` → `…_core_memory` rename.
- **The EM-303 prune** — its own destructive card, awaiting the owner's slot and
  sign-off (`docs/plan/PRUNE_CARD_DRAFT.md`).
- **S6+** — vault & graph, security, packaging, the 3.0 release: not started;
  the owner has not opened that sprint.

## If a future session resumes

Read `MASTER_TODO.md` → `docs/plan/NEXT_CHUNK.md` → `docs/plan/REMAINING_PLAN.md`.
There is no next chunk: the owner chooses. Do not start the cutover, a release,
or the prune without an explicit owner instruction.
