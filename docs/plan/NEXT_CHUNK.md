# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-08, end of session. **Chunk 20 is the owner's ceiling ruling, implemented the same day:** the shadow's promotion observable no longer conflates a *miss* with a *fabrication* — code `3c8b301` plus its docs commit. **P0c's data still has not been collected, and the blocker is now measured rather than assumed:** this box does not run the plugin at all (no `memory.provider` key, `plugins.enabled` lists only `homeassistant`, no `~/.hermes/plugins/entropicmem`, every table in the live store empty at `user_version=0`), so no turn reaches the write path and none can reach the shadow. The repo rests green: **2061/3/3 on both Pythons**, `ruff` clean, the v2 eval gate unmoved, nothing in flight, the live store and the Marketplace entry untouched.

**Owner decisions in force — the order was re-set on 2026-10-08** (`REMAINING_PLAN.md` §9 item 6):
1. **P0c — collect the shadow data.** The gating empirical step for the cutover. **Freeze before you look: do not fit a threshold to the sample, and report the raw distribution and the margin, not just a green light.**
2. **P2 / EM-306 — `evals tune`.** `dev`/`holdout` split by id hash, starting at `em/config.py`. **Hard constraint: the gate must not depend on EM-301's 92.9%-on-42 intent table.** Tuned defaults land here so the provider cards can wire them. **Its holdout split is also what arms the shadow's miss ceiling**, so P0c's promotion reading depends on it.
3. **EM-307 — packer and renderer.** Closes the *recorded* gap that served prefetch is memories-only.
4. **EM-303 — vectors** (the gate's cosine condition, MMR's embedding path). Lower urgency; the remaining quality lever behind the gate.

**The ceiling ruling (§9 item 7), in force from `3c8b301`:** `max_v3_only = 0` is hard and non-negotiable — a fabricated hit is a correctness/safety failure. The miss side is its own ceiling, `max_v2_miss_rate`, **pre-registered and un-armed**: `_shadow.MISS_CEILING_RULE` says to arm it at v2's own miss rate against a held-out reference (`1 − recall@5` of the v2 adapter on EM-306's holdout split, same corpus), committed with a link to the result file. **Do not arm it from a synthetic sample** — that is evidence about the metric, not about turns. While un-armed the miss rate is reported, the rule is printed on every reading, and the verdict is `cannot conclude`, never `met`.

**Still in force:** **the cutover is the owner's call** — both re-decision conditions are met in code, and **"conditions met" is not "proceed"**. The **flag default flip and `gate.*`/`ranking.*` plumbing are owner-facing**: staged, not pre-empted (the flip is one line plus the tests that pin default-off). **CI's eval gate stays v2 until EM-306** — and that intent is written on the `evals-ci` job in `.github/workflows/test.yml`, not only in this file. **Chunk 13 is forward-only, ratified, internal only**; `release/2.8.x` carries no `em/`, so its only vehicle is 3.0. **Never write to the live store**; the readout and collector are read-only by construction and asserted so.

**Plan exactly one chunk.** Two commits: code+tests+CHANGELOG, then docs with the reconciliation folded in. `MASTER_TODO`'s `In flight` names no commit; `Last reconciled` names a permanent ancestor. **Verify CI with the check-runs API on the exact SHA** (`ghx api repos/Ufonik88/EntropicMem/commits/<sha>/check-runs`), never `ghx run list --branch main --limit 1`.

**The master plan is at `~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`.** EM-301…EM-306 plus §3.6/§4 are transcribed into `REMAINING_PLAN.md` §6.2.

---

## Part A: what has landed

### Chunk 20 — the ceiling split, by owner ruling. **DONE, MERGED (2026-10-08, `3c8b301`)**

- **The ruling, and why it was legitimate.** The symmetric `max_divergence_rate = 0.10` counted "v3 dropped a hit v2 had" exactly like "v3 invented one". Chunk 19's measured sample was **150 misses and 0 additions**, so the gate failed a system for being *more selective* — what EM-305's gate exists to do — while `v3_only_never`, the condition the observable calls decisive, passed on every line. The owner split it **before any real turn was read**, which is the only circumstance in which amending a frozen observable is not fitting it to the sample.
- **Fabrication stays hard:** `max_v3_only = 0`, and the render says on that line that a fabricated hit is a correctness failure, not a tuning one.
- **The miss side is its own ceiling and is `None` — NOT ARMED.** `max_v2_miss_rate` = ids v3 dropped / ids v2 injected (id-level, because a turn that kept 1 of 3 is a smaller failure than one that kept 0 of 3; the turn-level counts are printed beside it).
- **The arming rule is pre-registered in code**, as `_shadow.MISS_CEILING_RULE`: arm at **v2's own miss rate against a held-out reference** — `1 − recall@5` of the v2 adapter on **EM-306's holdout split**, same corpus — committed with a comment linking the result file. The relative form was chosen over an absolute rate because no defensible absolute number exists before real turns, **and because it cannot be fitted to the shadow sample: it is measured on a different dataset.**
- **Un-armed is loud, never silent.** The miss rate is still reported, the arming rule is printed on every reading (render *and* `--json`), the verdict is `not armed`, and it **blocks `met`** — so the sample reads `cannot conclude`. An ungated dimension cannot be skimmed as a pass, which is exactly the accident the ruling forbade.
- **The retired number is still reported** (`context.divergence_rate_symmetric`) so the earlier finding stays comparable rather than restated: the same 240-turn sample now reads **38.46% id-level (150 of 390 ids), 90 of 240 turns, fabrication 0, verdict CANNOT CONCLUDE, exit 2**.
- **Mutation testing found a defect review did not.** The first id-level definition test used one id per turn, where id-level and turn-level rates are *numerically identical* — so two mutations (symmetric rate restored; silent switch to turn-level) **survived**. The fixture now injects 4/2/1 ids so the three candidate definitions disagree (4/7 vs 2/3) and the test asserts they are distinguishable. **26 mutation checks, all caught**, tree restored byte-identical.
- `tests/unit/test_provider_shadow.py`'s observable pin was updated **deliberately, not to get green**: it now asserts the split shape, that `max_v2_miss_rate is None`, that `max_divergence_rate` is gone for good, and that the arming rule is written down — with the ruling and its date in the docstring.
- 32 tests in `test_shadow_report.py` (rewritten around the split); **2061 passed / 3 skipped / 3 xfailed on 3.10 and 3.12**; `ruff==0.16.2` clean; v2 eval gate unmoved.

### Chunk 19 — P0c's readout and collector. **DONE, MERGED (2026-10-08, `94dd3c7`)**

- **The readout lives beside the thresholds it uses.** `_shadow.evaluate / read_log / report / render / main` reads every value from `PROMOTION` **at report time** — tighten the dict and the verdict follows, which a copied literal could not. Same module, so the observable and its scoring cannot drift apart.
- **A green light has to mean something.** A short, **no-signal** or unreadable sample is never `met`: on a zero-fact store v2 injects nothing and v3 injects nothing, and a naive rate reads that as "0% divergence — promote". Conversely **a violation outranks a short sample** — one fabricated hit in three turns is `not met`, so "we need more data" can never dissolve a finding.
- **The writer's own fields are cross-checked, not trusted:** `stale` against the bound in *both* directions, `divergence`/`v3_only` against the ids recorded on the line. A disagreement refuses the reading instead of averaging it.
- **Distribution and margin, not just a verdict** (what the owner asked for): how much room each condition left (rates in points, not bare fractions), `p50/p95/max` together (the `perf-smoke` tell: a low p50 with a huge max is one noisy sample), the alternate denominators shown as context while the verdict uses the frozen one, the **miss/add decomposition**, and the first offending line numbers. **Findings cite line numbers and ids and never question text — in the render *and* in the `--json` body.**
- **`scripts/shadow_collect.py`: a real sample, no live write.** The source is opened `mode=ro` and copied with `sqlite3.Connection.backup`; the **real v2 engine** supplies `v2_ids`; the real S3 pipeline and the real migration run per turn. Asserted on **bytes *and* mtime** that the source does not move; the env it borrows is given back; a missing `--source` is refused rather than quietly degraded to an empty store. A test proves the ids *arrive*, because a stub returning `[]` would still exit 2 with "no signal" and look like a clean run.
- **Deliberate omission, recorded:** the runner is `python plugins/entropicmem/_shadow.py report`, **not** an `entropicmem shadow` CLI command. `plugins/entropicmem/__init__.py` imports `agent.memory_provider`, so the v2 CLI cannot import the provider package in a plain shell — and a test parses `_shadow.py` and fails if a module-level relative or host import is ever added there, since that would break the collector with no other symptom. Exit code: 0 met, 1 not met, 2 cannot conclude.
- **Measured, twice.** (1) The **actual live store** (zero facts, 12 turns): every condition reported, divergence `no signal`, verdict **CANNOT CONCLUDE**, p95 1.48 ms; the store's sha256 and mtime were identical afterwards. (2) A **temp store, 8 invented facts, 240 turns**: `turns` met (240/200), `copy staleness` met (max age 0.5 s), `v3_only` **met (0 lines)**, `p95` met (1.89 ms), `divergence` **not met — 37.5%** (90 of 240 turns).
- **The finding, and why nothing was tuned.** That 37.5% decomposes into **150 ids v3 missed and 0 ids it added**: v3 kept the strongest hit where v2 injected two or three. The condition the observable calls decisive passed on every line; the symmetric ceiling failed because it counts a miss like an addition — which is what EM-305's gate was built to do (the adapter measured noise 0.172 vs v2's 0.219 for the same reason). **The threshold was not moved.** The definition question goes back to the owner, **before real turns are read** (Part B, and plan §9 item 7).
- 36 new tests (26 + 10); **2055 passed / 3 skipped / 3 xfailed on 3.10 and 3.12**; `ruff==0.16.2` clean; v2 eval gate unmoved. **18 mutation checks: 17 caught first pass; one survived, and the survivor was a gap in my tests, not in the code** — the privacy mutation put the question text into the *findings*, and I had asserted only against the human render, not the `--json` that prints them. Both tests now check the serialised report and the mutation dies.
- **Also landed alongside:** a comment on the `evals-ci` job stating in the workflow itself that the gate runs **v2 only** by decision, that `--adapter v3` exists and scores, and that making v3 fail a build belongs with EM-306.

### Chunk 18 and earlier

P0b (`be6352e` — a v3 store serving prefetch from S3 behind `ENTROPICMEM_V3_RETRIEVAL`, with the gate's `kind='constraint'` bypass fix), P0a (`f0a7c70`), the v3 eval adapter (`ff0d3c3`), EM-305/304/301/302, the `visibility` fix. `REMAINING_PLAN.md` §5.

---

## Part B: next — the P0c data step, then P2/EM-306

**Two things, in the owner's order. The first is data collection — now blocked on the environment, not on a decision, since the ceiling ruling is implemented. The second is the next buildable chunk. If the real turns cannot be collected, build EM-306 (which is also what arms the miss ceiling).**

### Step 1 — collect the real turns (**blocked on the environment, which is now measured**)

- **The ceiling question is settled** — see Part A and plan §9 item 7. Do not reopen it, and do not arm `max_v2_miss_rate` from a synthetic sample: the pre-registered rule in `_shadow.MISS_CEILING_RULE` arms it from **EM-306's holdout**, i.e. from v2's own miss rate against a held-out reference.
- **The blocker is that this box does not run the plugin at all** (plan §9 item 8, measured read-only): `~/.hermes/config.yaml` has **no `memory.provider` key**, `plugins.enabled` lists only `homeassistant`, there is **no `~/.hermes/plugins/entropicmem`** and no live clone, no vault, `index.db` holds 0 notes, and every table in the live store is empty at `user_version=0`. So the zero-fact state is **expected**: no turn reaches the plugin, so no write path runs and nothing can reach the shadow. **It will not fix itself by accumulating.** Real turns need a host where the plugin is installed and enabled — an owner-facing change, not an agent's.
- **Collect, once such a host exists:** set `ENTROPICMEM_SHADOW_V3=<v3 copy path>` (the log defaults beside it; `ENTROPICMEM_SHADOW_LOG` overrides) and let real turns accumulate. **Read:** `python <plugin>/_shadow.py report` — it prints the distribution, the margin on every gated condition, the miss/add shape, the staleness bound, the no-vectors caveat and the arming rule, and exits 0/1/2 for met/not met/cannot conclude.
- **Plumbing smoke without waiting on traffic:** `python scripts/shadow_collect.py --source <a store with facts> --turns 200` (or `--empty`). It opens the source `mode=ro`, copies it, and never writes it. On a zero-fact store it correctly returns `CANNOT CONCLUDE` with `no signal`; on the 8-fact synthetic store it returns a real reading — **which is evidence about the metric, never about turns.**
- **Never lower a threshold to fit a sample**, and never read a miss or divergence number without its `copy_age_s`/`stale` (divergence is a **lower bound**) or its caveat (no vectors until EM-303, so **not** an apples-to-apples quality comparison). The report carries both by default; a hand-written summary that drops them is the failure mode.
- **Until the miss ceiling is armed, no sample can read `met`** — by design. A `cannot conclude` with a clean fabrication line is the expected shape of a good sample today, and the report says exactly which dimension is ungated.

### Step 2 — P2 / EM-306, the calibration harness (**the buildable chunk**)

**Card, from the master plan:** *Calibration & tuning harness · M. Depends on EM-301–305, EM-002.* *Spec:* split scenarios into `dev` (70%) / `holdout` (30%) **by id hash**; `python -m evals tune --params gate.min_score,gate.min_coverage,ranking.w_* --grid …` optimising **`0.4*recall@5 + 0.3*mrr + 0.3*abstain_correct − 0.2*noise_rate`**; write chosen defaults into `em/config.py` with a comment linking the result file; per-model cosine thresholds calibrated separately. *AC:* holdout metrics reported; defaults committed; §6.3's gates updated to the new baseline.

- **`em/config.py` does not exist yet — this is where it starts.** Keep it to the scalars this card tunes (`gate.*`, `ranking.*`). EM-407's typed nested `Config`, loader precedence, validation and `get_config_schema()` emission are **not** this chunk; if it grows a loader or a schema, stop and report.
- **Split by id hash, not by order**, so a rerun scores the same holdout. Report the **holdout** numbers; the dev numbers are what the grid optimised and prove nothing on their own.
- **The gate must not depend on EM-301's intent table** (92.9% on 42). If tuning shows it does, **widen the table first** — never tune around the miss.
- **Per-model cosine is last: the grid is empty until EM-303.** Record that as deliberately deferred in the result file, not silently skipped.
- **CI's gate stays v2.** Making v3 fail a build is EM-306's decision with §6.3's gates moved to match; until then `tests/evals/test_adapter_v3.py` is v3's only regression protection, and it runs in the default suite. The intent is on the `evals-ci` job itself now.
- **`gate.*`/`ranking.*` reach the call sites only via the provider cards** (EM-401–403). EM-306 commits tuned *defaults*; saying which parts stay unwired is part of the PR, not an implication.

### Step 3 — a cheap guard for the pre-flight count itself (**deferred, recorded, small**)

Chunk 18's pre-flight said **1995** while `MASTER_TODO` and reality said **1998**: the drift is not
that a number was wrong once, it is that four pages state the suite size by hand and nothing
compares them. A candidate no-bump hygiene commit: one test asserting that the *stated* baseline
in `MASTER_TODO`'s gates table, `NEXT_CHUNK.md`'s pre-flight and `REMAINING_PLAN.md` §11's
verify block name the same `passed / skipped / xfailed` triple — cross-file agreement only, not
agreement with a live collection run, because a nested `--collect-only` would trade a silent
drift for a flaky gate. Deliberately not added to Chunk 19: it is a different area, and the
rules say one chunk at a time. Until it lands, the defence is the pre-flight itself — run the
suite, compare the number, **stop and report on a mismatch**.

### Size guards — stop and report if

- **a threshold needs moving to get a reading** — that is not a reading (this is Part B step 1's decision, and it is the owner's).
- **EM-306 starts restructuring the provider or the facade**, or grows into EM-407's config system.
- **either chunk needs EM-303's vectors to be meaningful** — do not invent a cosine path or an embedding cache.
- **anything would write the live store, move the Marketplace entry, or touch a tag.**

### Pre-flight

1. `main` must be at `3c8b301` or later: `git merge-base --is-ancestor 3c8b301 main`.
2. **Baseline:** `pytest -q` gives **2061 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12** (3 skips on a box without the private digest list; CI runs with it — and note the list is *not* on this dev box, so the local collision check has never run here; closing it is a one-file copy, recorded in plan §11, and `ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1` is what makes a missing list fail closed instead of skipping).
3. **Re-measure from the code, not this file:** `_shadow.py` (`PROMOTION`, `MISS_CEILING_RULE`, `evaluate`, `read_log`, `render`, `main`), `scripts/shadow_collect.py`, `em/facade/engine.py` (`v3_retrieval_enabled`, `_recall_from_v3`), `em/retrieval/pipeline.py`, `em/retrieval/gate.py` (`load_rows`' pinned input), `evals/` (`runner`, `metrics`, `adapters/engine_v3.py`), `.github/workflows/test.yml`.
4. **Verify CI with the check-runs API on the commit**, and read `head_sha`.

### Document control

Per `AGENTS.md`, with the reconciliation folded into the docs commit. `In flight` names no commit; `Last reconciled` names the previous chunk's permanent ancestor. Chunk 13 stays internal; the Marketplace entry is untouched. **Never write to the live store** — and remember the two rules this chunk was shaped by: **run the thing once, on a real store** (that is how the `kind='constraint'` bug and the symmetric-ceiling finding surfaced), and **a test that asserts on a stopwatch measures the runner.**
