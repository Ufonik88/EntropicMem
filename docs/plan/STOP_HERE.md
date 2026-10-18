# STOP HERE — S5 is complete (2026-10-17)

**Development stops at this point.** S5 (formation & consolidation) is complete on
`main`, every change is committed and pushed, and **no development chunk is
queued**. The next actions are owner-gated or belong to a later sprint the owner
has not started. Do not begin new development from this state without the owner.

> **Superseded for EM-601 and EM-608 (2026-10-18):** the owner authorised **EM-601,
> the vault-projection card, both halves** — and both landed the same day (slice 1
> `bdc1e20`, slice 2 `e986059`) — and slotted **EM-608**, the 50k warm-p95 gate's
> statistic, which also **landed the same day** (`3b71cf0`), **chunk 38, the
> `remember` content-ceiling fix, landed the same day too** (`c53b182`), and **chunk 39,
> EM-602 in both slices (frontmatter & wikilinks, then the note-id rule and the `index.db`
> migration), landed the same day** (`607d54f` + `c29addc`).
> **Nothing is in
> flight; the next chunk is EM-603.** Every
> owner-gated item in this file still stands; only the "do not begin"
> instruction has moved, and only for EM-601 and EM-608. **The rest of S6 and
> everything after it remain gated** — see the correction in the addendum below.

The S5 code tip is `d331c5e`; the docs reconciliation rides on top of it.

### Addendum (2026-10-18, later) — the owner handed the gated calls to the agent; **they are made**

The owner's instruction: *"I do not have any idea what these are or what I must do …
can you not make a call on these and make a choice for me?"* Taken as the authority this
file's ruling table reserves to the owner, the agent has decided all six. **Five of them
require nothing from the owner; one is real work.**

| Item | Plain meaning | The call |
|---|---|---|
| **P0c's shadow data** | run the new retrieval silently alongside the current one on real usage, changing nothing, to gather evidence | **Skipped.** It exists only as evidence for the cutover (a no, below), and it needs the owner's host running the dev plugin for weeks. |
| **The v3 cutover** | move the live memory database to the new format | **No.** The new format has no user-visible benefit yet and is not released; migrating would risk the real store for nothing. The live store stays v2. |
| **The prune's destructive run** | a background cleanup that deletes old embedding vectors | **Nothing to run.** It can only delete from a v3 store, and there is none (see above). Gated by construction, not by a decision. |
| **Releases, tags, catalog re-pin** | publish a new version to the Hermes Marketplace | **Not now.** `main` is `3.0.0.dev0` with half-wired v3 features behind flags; publishing would ship unfinished work. It is the last step, after a 3.0 the owner *wants*. |
| **Ceiling card slotting + number** | a real bug: a long `remember` is silently cut at 4,000 characters and stored as complete (data loss) | **Build it — next chunk (38), ceiling 8,000.** The one item worth doing now. |
| **The S6 scope question** | whether the owner's earlier "you make the calls" also opened EM-602…EM-607 (vault/graph robustness, security, packaging) | **Yes — opened, agent-owned**, taken in the documented §6.5 order after the ceiling fix. |

**The one action item is the content-ceiling card** (`CONTENT_CEILING_CARD_DRAFT.md`),
now slotted as the next chunk: one shared `CONTENT_MAX_CHARS = 8_000`, and oversize
`content` on `remember`/`update` **refused** (`invalid_arguments`, before any write)
instead of truncated. Reversible in one commit; no migration; the plugin manifest and the
catalog pin do not move. The draft's optional `summary` argument is **deferred**, as the
draft recommends.

**Update, same day: that card landed.** Built, landed and merged as chunk 38 on 2026-10-18
(`c53b182`) — the same two fields moved, 16 new tests, **8 mutation checks all red**, each
restored from a byte copy, no migration, the manifest and catalog pin untouched.
**The next chunk is EM-602**, the first of the now-agent-owned S6 cards.

**Update, same day: EM-602 slice 1 landed too.** Chunk 39 (`607d54f`) hardened the vault's
frontmatter (escaping writer, delimiter rule, PyYAML-or-subset reader) and wikilinks, in the
new `em/vault/frontmatter.py` which `em_internal.vault` now shims — 26 tests, **7 mutation
checks all red** plus a green control, 2 recorded repoints.

**Update, same day: EM-602 slice 2 landed, and the card is complete.** Chunk 39's second
commit (`c29addc`) made `note_id` the full vault-relative path — `A/Sub/Note` and
`B/Sub/Note` no longer share one primary key — and added the `index.db`
`PRAGMA user_version` 2 migration (ids recomputed from each row's `path`, `notes_meta` and
`notes_fts` renamed in two passes, the `wikilink` endpoints remapped, `triple:*` edges left
alone, Windows-shaped ids normalised to POSIX), with 10 tests and **6 mutation checks all
red**. One Windows CI fix is recorded (the fixture's legacy ids were platform-shaped; the
product was right). **Nothing is in flight; the next chunk is EM-603** (the incremental
index by mtime).

### Addendum (2026-10-17, later the same day) — the F-004 chunk landed

The owner opened the F-004 remediation ("the stage is yours"), and it landed as
`c30aa54` (branch-first, all check-runs green on the exact SHA, `--ff-only`).
**No product code changed** — the audit found the v3 line already bucket-clean —
so this does not reopen S-phase development: the strict xfail
`test_f004_cross_user_isolation` is now a passing guard driving a v3 store, the
two-provider surface is pinned in the new `tests/harness/test_f004_shared_profile.py`
(write attribution, both-directions prefetch/search isolation, the five
foreign-row refusals, episode isolation, and the ruled profile-wide-sharing
half), 5 mutation checks went red, and the xfail count moves 3→2. The suite
reads **2693 / 16 / 2** bare, **2694 / 15 / 2** with the digest list, **2771 /
2 / 2** CI-equivalent. One discovered asymmetry is **recorded and pinned, not
changed**: the episodes read rule is exact-bucket (no profile-wide half), so a
profile-wide episode is under-read (never over-read) for a user-mode caller —
its semantic call rides the cutover card. **The v3 cutover is unblocked on the
F-004 axis**, the draft acceptance needs no signature for a single-user
cut-over, and the next agent work was the EM-303 prune build (its own card;
the destructive run stays owner-signed) — **it landed the same day
(`99151d3`)**. Concurrently, another session drafted the
**remember content ceiling card** (`docs/plan/CONTENT_CEILING_CARD_DRAFT.md`,
from a live silent-truncation incident) — it awaits the owner's slotting and
the ceiling number before anything is built. The full record: `CHANGELOG.md`
under `[Unreleased]`/Fixed, `REMAINING_PLAN.md` §9 item 9, `NEXT_CHUNK.md`'s
new Part A block.


### Addendum (2026-10-18) — EM-601, EM-608, chunk 38 and chunk 39 are complete

The owner opened **EM-601 (the vault-projection card, both halves)** with the
explicit session assignment *"We're doing this YOLO, so you dont need my
permission… you make the logical calls on the build"*, the session target named
as **chunk 36 = EM-601 slice 1**: **dev-line work only — nothing touching the
live store or any other owner-gated item.** **EM-601 slice 1 — the vault
projection engine — landed the same day as `bdc1e20`** (branch-first on
`em-601-projection`, all 11 check-runs green on that exact SHA including
`identity-guard`, `--ff-only`, branch deleted; the merge re-ran all 11 to success on
`main`). **Slice 2's go came explicitly the same day** ("proceed with slice 2") **and
landed the same day (`e986059`); the owner then slotted EM-608 — the 50k warm-p95
gate's statistic — and it also landed the same day (`3b71cf0`), so nothing is in
flight.**

> **Corrected 2026-10-18.** This addendum originally read "**S6 (vault &
> graph)** is open" and said the "do not begin" instruction no longer applied to
> S6. **That was an extrapolation, and it is retracted.** The owner named one
> card (EM-601), not a stage. What is authorised is EM-601 in both halves.
> **S6's remaining cards (EM-602…EM-607), S7 security, packaging and the 3.0
> release remain gated and are not opened by this word** — the open question is
> recorded in `NEXT_CHUNK.md` for the owner. Everything owner-gated below is
> untouched, and the "do not begin" instruction still applies to every card
> except EM-601.

Counts since the stop point (**the "Verification at the stop point" figures below are
the stop point's own, three chunks back**): CI's 3.12 leg reads **2842 / 4 / 2** (read
green from the job log at `3b71cf0` — the EM-608 landing; before it `bdc1e20` read
2813/4/2), this box bare **2766 / 16 / 2**, with the digest
list **2767 / 15 / 2**, CI-equivalent 3.12 **2844 / 2 / 2**; ruff `0.16.2` clean. The
current gates live in `MASTER_TODO.md`'s Gates table — that is the figure to trust, not
this file's historical ones.


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

> **Superseded by the 2026-10-18 "later" addendum above.** Five of the items below are now
> decided (skipped / no / nothing to run / not now), and the sixth — the content-ceiling
> card — is the next chunk. The list is kept as the record of what *was* open.
> **Chunk 38 (the ceiling card) then landed the same day (`c53b182`); see the update at the
> end of the addendum above. Nothing is in flight and the next chunk is EM-602.**

- **P0c** — the shadow data: needs a host running the dev-line plugin with
  `ENTROPICMEM_SHADOW_V3` set for ≥ 200 real turns. Owner's environment.
- **The v3 cutover** — owner decides. **F-004 is resolved and pinned (`c30aa54`)** — no signed acceptance is needed, and the cutover is unblocked on that axis; the episodes exact-bucket under-read rides the card as a recorded semantic item.
- **Releases, tags, the Hermes catalog re-pin** — including the new logo's
  `image` field, and the `entropicmem_patch_core` → `…_core_memory` rename.
- **The EM-303 prune** — its own destructive card, awaiting the owner's slot and
  sign-off (`docs/plan/PRUNE_CARD_DRAFT.md`); the agent builds the card next.
- **DONE — the 50k warm-p95 gate's measurement** (`docs/plan/PERF_GATE_CARD_DRAFT.md`,
  **EM-608**, agent-owned): the AC flapped twice in two days on
  unchanged code, and re-running a red `main` job until green was a workaround, not
  a fix. **Landed 2026-10-18 as `3b71cf0`** — it fixed the **statistic**
  (best-of-five 20-probe windows — EM-407's
  precedent) and **did not widen the 150 ms budget**.
- **Drafted — the remember content ceiling** (`docs/plan/CONTENT_CEILING_CARD_DRAFT.md`):
  raises the `remember`/`update` content cap and replaces oversize **truncation**
  with a refusal (`invalid_arguments`). Found from a live incident on 2026-10-17
  (a 4.3 KB remember was silently clipped to 4,000 and stored "complete").
  Awaiting the owner's slotting decision and the ceiling number (8,000
  recommended; 16,000 mechanized identically). Builds only when the owner opens it.
- **EM-601 (vault projection, both halves) — COMPLETE (authorised 2026-10-18** by the
  owner's explicit session assignment (*"you make the logical calls on the
  build"*, target named as **chunk 36 = EM-601 slice 1**); slice 1 landed the
  same day (`bdc1e20`) and slice 2's go came explicitly the same day and landed as
  `e986059` (`em/vault/schedule.py`: the `project_vault` job, the 60 s debounce, the
  `vault.projection` → `modes` switch, the provider's write-path enqueue, and
  `vault lint --root`). **Corrected 2026-10-18: an earlier version of this entry read
  "S6 (vault & graph) — OPENED on the owner's word", which overclaimed.** The owner
  named one card. **S6's remaining cards (EM-602…EM-607), S7 security, packaging and the
  3.0 release are not authorised** and stay behind their own gates — see the
  open question in `NEXT_CHUNK.md`.
- **EM-608 — the 50k warm-p95 gate's statistic — COMPLETE (slotted 2026-10-18 by
  the owner's word, this session; landed the same day as `3b71cf0`).**
  `docs/plan/PERF_GATE_CARD_DRAFT.md`: the gate's
  *measurement* was the defect, not its budget (the AC flapped twice in two days on
  unchanged code). Both warm-p95 ACs now read the best of five 20-probe windows via
  `tests/harness/perf_stats.py`; **the 150 ms budget was not touched**. 8 new tests,
  6 mutation checks red, no product code changed.

### Who actually decides what (recorded 2026-10-17, with the owner)

The owner asked for every gate above to be settled down to the smallest
possible action, and this table is that ruling — future sessions must not
re-ask it:

| Gate | Ruling | What is actually left, and for whom |
|---|---|---|
| **P0c's shadow data** | Agent ruled: it is a **collection step, not a decision**. | One mechanical owner step on the active host — enable the dev-line plugin + `ENTROPICMEM_SHADOW_V3` and let ≥ 200 real turns accrue (NEXT_CHUNK's "The owner's run checklist"). The agent reads `_shadow.py report` from there; the cutover's evidence is then in place. |
| **F-004** | Agent ruled on both halves it left open: the migration rule for the ~1,700 existing profile-wide facts is **keep profile-wide** (no read-visible change — the changing half, per-author re-bucketing, would need a signed owner instruction), and the build (a)+(c) is **the first queued dev chunk, agent-owned — landed within the day (`c30aa54`): the strict xfail is flipped, the surface is pinned, and the chunk certifies that no product code was needed on the v3 line.** The draft acceptance never needs signing for a single-user cut-over. | Nothing from the owner now. |
| **The v3 cutover** | **Still the owner's one-word go** — irreversible, touches the real store. The staged `ENTROPICMEM_V3_RETRIEVAL` default flip and the adapter-defaults unification ride that same card, so they are not separate asks. | One "go" (or "not yet") when the shadow report and the F-004 chunk are both in hand. |
| **Releases, tags, the catalog re-pin** | Owner-gated end to end (`docs/MARKETPLACE.md`); the agent does every non-public step. | One "go" when the owner wants users on 3.0. The live catalog serves 2.8.1 today; two GitHub-UI uploads (the avatar and the social preview) only the owner can do and are separately optional. |
| **The EM-303 prune** | Agent ruled the slot: **its own card** (the draft's recommendation). **The build is DONE (landed 2026-10-17, `99151d3`) — no destructive run happened.** The handler refuses before deletion (no current model, an incomplete transition record, an unreadable clock), keeps current + previous past the grace (the test plan corrected the draft's AC2 tail: the previous model is the rollback set, demoted only by a newer completed backfill), and is `dry_run`-first. A real run only ever acts on a v3 store's embeddings rows — nothing exists for it to delete today. | **One owner sign-off for the first real destructive run** (when a store with real vector rows exists to protect — and the run should name the model set it prunes down to). |
| **EM-601 — vault projection, both halves** | **GIVEN and DISCHARGED 2026-10-18** — the owner's explicit session assignment: *"We're doing this YOLO, so you dont need my permission… you make the logical calls on the build"*, with the session target named as **chunk 36 = EM-601 slice 1**. Slice 2's go came explicitly the same day ("proceed with slice 2"). That is owner approval for **this card**, not for a stage. **Both halves landed: slice 1 `bdc1e20`, slice 2 `e986059`.** | Nothing from the owner on EM-601. **CORRECTED 2026-10-18 — an earlier version of this row read "S6+ (vault & graph, security, packaging, the 3.0 release) — GIVEN". That overclaimed, and it is retracted: the owner named one card, not a stage.** S6's remaining cards (EM-602…EM-607), S7 security, packaging and the 3.0 release are **not** authorised by that word; the open question is recorded in `NEXT_CHUNK.md`, and the releases row above still gates the actual 3.0 release. |
| **EM-608 — the 50k warm-p95 gate's statistic** | **GIVEN and DISCHARGED 2026-10-18** — the owner slotted the card in this session, answering the draft's own ask ("one word: slot EM-608 (or don't)"). Agent-owned; **the 150 ms budget was not touched** by the ruling or the card. **Landed the same day as `3b71cf0`.** | Nothing from the owner. |

The owner's sole physical step is the P0c run checklist. Everything else that
is on the owner is a one-word go/no-go on the day the artifacts above are
ready — surfaced as explicit questions, never again as open questions.

## If a future session resumes

Read `MASTER_TODO.md` → `docs/plan/NEXT_CHUNK.md` → `docs/plan/REMAINING_PLAN.md`.
Since the addendum above, that chunk **landed**: the **EM-303 prune card is
built and merged (`99151d3`, 2026-10-17) — with no destructive run performed;
real runs stay owner-gated** and the full record rides plan §5 and
`NEXT_CHUNK.md` Part A. **Remember the correction the build's test plan
arbitrated:** the previous model's rows survive the grace (the rollback set);
only a newer completed backfill demotes them to prunable. **EM-601 is COMPLETE —
both halves**, slice 1 the vault projection engine (`bdc1e20`) and slice 2 the
`project_vault` job, its debounce, the mode switch and `vault lint` (`e986059`),
both landed 2026-10-18 (addendum above). **EM-608 is COMPLETE too — the 50k
warm-p95 gate's statistic**, landed the same day as `3b71cf0` (slotted by the owner
2026-10-18; `PERF_GATE_CARD_DRAFT.md`). **Nothing is in flight.**
**The rest of S6 and everything after it stay gated.** The **remember content ceiling card is drafted but builds only when the
owner opens it** (slotting + the ceiling number). Still
never start the cutover, a release, or the prune's destructive run without an
explicit owner instruction.
