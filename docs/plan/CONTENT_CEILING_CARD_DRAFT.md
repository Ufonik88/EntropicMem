# DRAFT — the remember content ceiling: a raised cap and a refusal-over-truncation contract

**Status:** **SLOTTED 2026-10-18 as chunk 38** — the owner handed the outstanding gated
calls to the agent ("make a call … make a choice for me"), so the agent opened this card
and set **the ceiling number at 8,000** (open decision 1) and **deferred the optional
`summary` argument** (open decision 2), both the draft's recommendations. It is the next
chunk. The original drafting note follows.

Drafted 2026-10-17 for the owner's slotting decision and ceiling number —
found 2026-10-17 by a live incident (an `entropicmem_remember` of a 4.3 KB
technical summary was silently cut to its first 4,000 characters and still
registered `active/created`), audited against the dev-line code the same day.
No EM id yet — the id is assigned in the tracker when the owner approves the
card. Nothing here is built. This is the §6.4-style pre-draft the
[PRUNE_CARD_DRAFT.md](PRUNE_CARD_DRAFT.md) model made: a scoped card, ready to
pick up, with acceptance criteria and mutation checks declared before work
starts. **Per the stop-point discipline it builds only when the owner opens it.**

## The gap, in today's code (two defects, one seam each)

1. **The ceiling is too tight for the facts it is supposed to hold.**
   `REMEMBER_SCHEMA`/`UPDATE_SCHEMA` pin `content` at `maxLength: 4000`
   (`em/provider/tools.py`), hand-calibrated against "facts may span several
   hundred words". The observed working set already overruns it: a single
   technical state summary measured 4,314 characters — over the cap, so its
   tail was destroyed. The persona-side rule ("a fact may be stored in FULL
   DETAIL ... facts may span several hundred words") and the schema now live on
   opposite sides of the same string.
2. **Oversize input is destroyed, not refused.** `validate_arguments`
   (`em/util/jsonschema_lite.py`) implements §4.4's `maxLength` clause as
   **clamp-with-a-warning**: line ~114 truncates the value in place and appends
   "`content` truncated to 4000 characters" to the warnings list. The truncated
   value then flows into the handler and **is persisted** — so the fact
   registers `active/created` with silent data loss baked into the store. For
   everything else the clamp is fine (a 500-char `query` losing its tail is a
   non-event); for the one field that carries the user's durable knowledge it
   is the worst possible failure mode: `full` and `cut` become
   indistinguishable at recall time, forever.

Both findings verified against `@6fe2a4b` (tools.py REMEMBER/UPDATE schemas,
`jsonschema_lite.validate_arguments`'s clamp branch, `handle_tool_call` at
`tools.py:395` where the clamp runs before `_remember`/`_update` ever see the
value).

## The proposed approach

### A. One ceiling constant, shared by schema, validator and tests

A module-level constant in `em/provider/tools.py`:

```python
CONTENT_MAX_CHARS = 8_000   # see Open decision 1 for 16_000
```

`REMEMBER_SCHEMA["parameters"]["properties"]["content"]["maxLength"]` and
`UPDATE_SCHEMA`'s same field build from it, so the number exists exactly once
— the schema advertises it to the model, the validator enforces it, and the
tests pin both to the one literal. No config key: the Appendix B schemas are
verbatim-pinned artifacts; making the advertised schema config-driven would
put the schema and the validator on independent drift paths for a knob nobody
has asked to move at runtime. The raise is a deliberate owner decision at
build time, not a tuning dial.

### B. `jsonschema_lite` learns a fatal-oversize mode — additive, default-unchanged

`validate_arguments(tool_schema, arguments)` gains a third, keyword-only
parameter:

```python
def validate_arguments(tool_schema, arguments, *, fatal_length_keys=frozenset()):
```

For keys named in the set, over-long input **raises `ArgumentError` naming the
argument, what arrived and the limit** — the same fatal shape the function
already uses for types and enums — instead of clamping. The default call keeps
every existing behavior byte-identical (the clamp branch stays for all other
callers, and the message stays generic; the file keeps knowing nothing about
tools, providers or the host). The existing §4.4 tests pass unmodified.

`handle_tool_call` passes the set per tool:

```python
FATAL_LENGTH_KEYS = {"entropicmem_remember": {"content"},
                     "entropicmem_update": {"content"}}
```

so the refusal rides the machinery that already exists: the
`except ArgumentError → self._blocked(str(exc), "invalid_arguments", ...)`
branch renders `{"ok": false, "reason_code": "invalid_arguments", ...}` and —
critically — still runs **before any store write**, so a refused remember
leaves no row, no audit entry, no queue work. The refusal is loud by
construction: an `invalid_arguments` answer names `content`, its actual length
and the limit, and the model that made the call sees it in the same turn.

### C. Guidance moves to the place the model already reads

`content`'s field description gains one sentence, decided with Appendix B's
letter ("Beyond the embedding window — long documents belong in the vault; a
remember stores the fact or a pointer to the note"). The description is what
prevents oversize calls better than any runtime check can; the refusal is the
backstop, not the teacher.

## How this resolves the gap

* **The truncation path for `content` is gone**, on both `remember` and
  `update` — nothing in the pipeline can store a clipped fact and report
  success. Oversize content now fails closed (`invalid_arguments`) instead of
  failing silently (`ok: true` with eaten tail).
* **The ceiling describes reality**: the observed working set (4.3 KB +
  headroom) fits inside the cap, so the persona's full-detail rule and the
  schema stop fighting. Anything larger is, per the model's own
  [five-layer design](../../docs/MEMORY_MODEL.md), a vault artifact rather
  than a memory — and the guidance sentence says so at the moment the model
  is composing the call.
* **`update` inherits the fix for free** — supersede/edit mode with oversize
  content is refused by the same validator path, so a correction cannot blow
  away history with a truncated copy either.

## Performance containment (why nothing on the read path moves)

Injection and recall are **budget-bound and top-k-bound**, not fact-length
bound, so the raised ceiling cannot stretch them:

* **Serving (the turn path).** The packer (`em/retrieval/packer.py`) keeps a
  row in full only while the rendered block fits, else falls back to its
  distinct `summary`, else skips the row — never cut mid-sentence, and
  §4.2's block cap (`min(budget×4, 9000)` chars) and the 450-token default
  govern regardless of what a row contains. A long fact therefore crowds
  itself out of a block the same way an over-long one does today — it does
  not stretch the budget. **Recorded consequence:** a remembered fact above
  roughly `budget × 4` characters (≈1,800 at the default 450-token budget)
  with no distinct `summary` never fits a served block at all — and that is
  already true at the current 4,000 cap; the raise does not change injection,
  it changes what the store will *hold*. Open decision 2 records the optional
  `summary` argument as the follow-up lever if injection of long facts is
  ever wanted.
* **Search.** `bm25` runs its single bounded top-k query (`em/retrieval`
  chunk 33/34 shape); the analyzer reads the IDF cache; the injection screen
  is O(len) over the returned rows. A longer row costs bytes in the FTS
  index, not extra queries.
* **Embeddings.** `em/embeddings/service.py`'s `MAX_TEXT_CHARS = 2_000` is
  untouched — a fact above the window embeds its (summary-or-content) head
  exactly as it does today, on the background embed job, never on the turn
  or prefetch thread. The 50k × 128 warm-search AC (`p95 < 25 ms`) is
  input-length independent and unchanged.
* **Writes.** The one new per-write cost is FTS tokenizing a longer row at
  `remember` time — SQLite-side, sub-millisecond at the proposed sizes, and
  off the turn path in every case that matters (tool writes are
  user-prompted, not per-turn).
* **Storage.** `facts.content` is TEXT with no length constraint and no
  migration: the raise changes no store schema, no audit shape, no backup
  format, and v2 stores are untouched by construction (the tool layer is the
  seam, both engines sit behind it).

**Measurement AC (not a gate, a recorded number):** a 20k-fact fixture at
~2,000-char average content is built once, and the run records warm prefetch
p95 against the pre-declared 150 ms ceiling, FTS index build seconds per 10k,
and index size MB per 10k (the `dbstat`/page-accounting recipe from
[PRUNE_CARD_DRAFT.md](PRUNE_CARD_DRAFT.md) applies unchanged). CI's existing
perf gates (`evals.perf --sizes 1000 --probes 20`; the embedding AC) keep
their budgets and add nothing.

**No new dependency, no stdlib-exit, no Windows hazard** — the change is one
constant, one optional keyword on an existing validator function, and one map
in the tool layer.

## Acceptance criteria (test-first, per AGENTS.md — every group starts red)

1. `remember` with content at exactly `CONTENT_MAX_CHARS` writes, and the
   stored row's content is byte-equal to the input (the truncation path is
   provably dead for the reachable case).
2. `remember` at ceiling+1 answers `{"ok": false, "reason_code":
   "invalid_arguments"}` with a message naming `content`, its length and the
   limit; the store's row count and the audit log are unchanged by the
   refused call.
3. `update` (supersede and edit) shows the same two behaviors.
4. The two schemas' `maxLength` equals the one constant, and the
   fatal-length map covers exactly `remember`/`update` `content` — no other
   tool's fields change; the Appendix B surface test passes with only the
   two expected fields moved (the recorded deviation).
5. `validate_arguments`' default two-arg call behaves exactly as today
   (existing tests unmodified); the fatal mode raises with the standard
   message shape and never returns a truncated value for a fatal key.
6. Packer characterization at the raised cap: a ceiling-size fact **with** a
   distinct summary renders the summary into a served block; **without** one,
   it is skipped, and block budgets never stretch (§4.2 cap pin unchanged).
7. The 20k × ~2,000-char fixture reports its recorded numbers; the existing
   perf gates stay within their budgets.
8. Refusal messages and schema wording are consistent (one wording, pinned).

## Test plan and mutation checks

* New: `tests/unit/test_em_content_ceiling.py` (groups 1–4, 6, 8 above);
  groups 5 rides additions to the existing `jsonschema_lite` test module so
  the clamp-vs-fatal contract lives beside its own tests.
* Mutation checks, restored from byte copies per the standing rule:
  (1) the `FATAL_LENGTH_KEYS` entry for `remember` dropped — the call must
  persist silently and die the AC-2 test; (2) `handle_tool_call`'s
  `fatal_length_keys` argument removed — same; (3) the schemas' `maxLength`
  re-hardcoded away from the constant — the surface pin goes red; (4) the
  fatal branch clamps instead of raising — the validator test goes red;
  (5) the refusal payload loses `reason_code: invalid_arguments` — the
  reason-code pin goes red.
* Count impact: the card adds one tracked markdown file, so the
  `tests/test_docs_links.py` parametrization grows by one case in every
  environment — expected counts move +1 each (CI 3.12, bare, digest list,
  CI-equivalent) and the three pages state the same new triad, per the
  count-uniformity guard.

## Risks and recorded consequences

* **Injection of long facts is still governed by budgets, not by this card.**
  Without a distinct summary a near-ceiling fact remains injection-excluded
  (already true today); search finds it, the served block may not. The
  schema's new guidance sentence is the workflow answer (artifacts to the
  vault, facts as pointers); open decision 2 holds the `summary` lever.
* **Appendix B deviation.** Two `maxLength` values and two field
  descriptions move off the appendix's literal text. Recorded here, pinned
  at the surface test with only those two fields in play; every other field
  byte-identical.
* **Interoperability of ceiling and cutoff generations:** an agent prompt or
  convention that treats 4,000 as the limit will now be under-utilizing, not
  misusing — the refusal and the schema make the new limit self-describing.
* **The card is dev-line work.** The released 2.8.1 carries its own provider
  and gains nothing; the catalog pin does not move; the plugin manifest is
  untouched (`provides_tools` stays 9).

## Rollback

Both halves reverse in one commit: re-point the constant to 4,000 and drop
the two `fatal_length_keys` pass-through sites (or the one `FATAL_LENGTH_KEYS`
dict). No migration, no data rewrite — rows already stored at the larger
cap stay valid TEXT; a rollback merely re-tightens future writes. The
validator's default behavior never changed, so nothing else in the tree
remembers the card existed.

## Build order (when the owner opens it)

1. Tests first, red: the ceiling groups, then the validator group, then the
   refusal/handler groups.
2. Implementation: the constant in `tools.py`; the two schemas build from
   it; `jsonschema_lite`'s `fatal_length_keys`; `handle_tool_call` passes the
   map; the two field descriptions.
3. CHANGELOG under `[Unreleased]`/`Fixed` (the truncation gap) and `Added`
   (the raised ceiling), one card one commit.
4. Docs: this file's status flips draft → landed; the count triads move +1
   together; the reconciliation line names the pushed **docs tip that
   carried the run** — the check-runs API pattern this repo landed 2026-10-17
   (cite the tip that carried CI, never the bare code SHA).
5. Branch-first end to end: push, all 11 jobs green on the exact tip,
   `git merge --ff-only`, delete; `identity-guard` green on the main push.

## Open decisions for the owner

1. **The ceiling number.** Recommended: **8,000** (2× the observed working
   set — a guard stays a guard; the guide line handles documents). The
   alternative 16,000 is mechanized identically; it trades a softer guard for
   more headroom, and changes nothing else in the plan.
2. **An optional `summary` argument on `remember`** (flows into the store's
   existing summary column, giving the packer its fallback for long facts).
   Recommended: **defer** — not needed for the cap raise, and it is an
   Appendix B surface change of its own; record the consequence instead and
   decide when a real workflow wants injectable long facts.
