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

- **CI 3.12: 2755 passed / 4 skipped / 3 xfailed** (11/11 jobs green on the exact
  tip; read from the check-runs API, not `run list`).
- Bare `.venv311`: **2679 / 16 / 3**.
- Digest list in place: **2680 / 15 / 3**.
- CI-equivalent 3.12 (extras + digest): **2757 / 2 / 3**.
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

### Who actually decides what (recorded 2026-10-17, with the owner)

The owner asked for every gate above to be settled down to the smallest
possible action, and this table is that ruling — future sessions must not
re-ask it:

| Gate | Ruling | What is actually left, and for whom |
|---|---|---|
| **P0c's shadow data** | Agent ruled: it is a **collection step, not a decision**. | One mechanical owner step on the active host — enable the dev-line plugin + `ENTROPICMEM_SHADOW_V3` and let ≥ 200 real turns accrue (NEXT_CHUNK's "The owner's run checklist"). The agent reads `_shadow.py report` from there; the cutover's evidence is then in place. |
| **F-004** | Agent ruled on both halves it left open: the migration rule for the ~1,700 existing profile-wide facts is **keep profile-wide** (no read-visible change — the changing half, per-author re-bucketing, would need a signed owner instruction), and the build (a)+(c) is **the first queued dev chunk, agent-owned — queued, not started.** If it lands green, the draft acceptance never needs signing for a single-user cut-over. | Nothing from the owner now. |
| **The v3 cutover** | **Still the owner's one-word go** — irreversible, touches the real store. The staged `ENTROPICMEM_V3_RETRIEVAL` default flip and the adapter-defaults unification ride that same card, so they are not separate asks. | One "go" (or "not yet") when the shadow report and the F-004 chunk are both in hand. |
| **Releases, tags, the catalog re-pin** | Owner-gated end to end (`docs/MARKETPLACE.md`); the agent does every non-public step. | One "go" when the owner wants users on 3.0. The live catalog serves 2.8.1 today; two GitHub-UI uploads (the avatar and the social preview) only the owner can do and are separately optional. |
| **The EM-303 prune** | Agent ruled the slot: **its own card** (the draft's recommendation), queued behind the F-004 chunk. The build is agent-owned; **the destructive run needs a later, separate owner sign-off**, and it only ever acts on a v3 store's embeddings rows — nothing exists for it to delete today. | Nothing from the owner now. |
| **S6+** (vault & graph, security, packaging, the 3.0 release) | Recommended, not opened: **start S6 while the P0c data accrues** — it is dev-line work, it never touches the live store, and it fills the collection window. | One word from the owner ("open it"). |

The owner's sole physical step is the P0c run checklist. Everything else that
is on the owner is a one-word go/no-go on the day the artifacts above are
ready — surfaced as explicit questions, never again as open questions.

## If a future session resumes

Read `MASTER_TODO.md` → `docs/plan/NEXT_CHUNK.md` → `docs/plan/REMAINING_PLAN.md`.
There is no next chunk: the owner chooses. Do not start the cutover, a release,
or the prune without an explicit owner instruction.
