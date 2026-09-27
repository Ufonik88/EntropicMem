# EntropicMem: next steps (one chunk at a time)

**Written:** 2026-09-27. **Read first:** `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

---

## Part A: Hermes, do these now (finishes the safe point; no development)

The Claude Code review session already did the rest:
- built 2.8.1 on `release/2.8.x` (`7e02412`);
- fast-forwarded `main` with the perf-smoke fix;
- fixed EM-212;
- forward-ported the 2.8.1 notes;
- committed these plans.

Its session is not allowed to push tags or delete branches (HTTP 403), so those steps are here. The owner does not touch GitHub. Everything below is yours, in order.

### H1. Tag and publish 2.8.1
```bash
cd <dev clone> && git fetch origin --prune
git rev-parse origin/release/2.8.x        # must print 7e02412366408234629e759a575edc31eb138721
git log -1 --format=%s origin/release/2.8.x   # "2.8.1 docs: state that native Windows is not supported on 2.8.x"
git show origin/release/2.8.x:CHANGELOG.md | sed -n '/^## \[2.8.1\]/,/^## \[2.8.0\]/p' | sed '$d' > /tmp/notes-2.8.1.md
git -c user.name=Ufonik -c user.email=Ufonik88@users.noreply.github.com \
  tag -a v2.8.1 7e02412366408234629e759a575edc31eb138721 -m "EntropicMem 2.8.1: safety patch on 2.8.0"
git push origin refs/tags/v2.8.1
gh release create v2.8.1 --repo Ufonik88/EntropicMem --verify-tag --title "v2.8.1" --notes-file /tmp/notes-2.8.1.md
git ls-remote origin 'refs/tags/v2.8.1^{}'   # must print 7e02412…
```

**Expected CI on `7e02412`:** 10 jobs green and `windows-import` failing. That failure is allowed on 2.8.x, as on 2.8.0 (the engine imports `fcntl`; the README says so). Any *other* red job means stop and report.

### H2. Protect `release/2.8.x` and delete the leftover branches
```bash
echo '{"required_status_checks":null,"enforce_admins":false,"required_pull_request_reviews":null,"restrictions":null,"allow_force_pushes":false,"allow_deletions":false}' > /tmp/prot.json
gh api -X PUT repos/Ufonik88/EntropicMem/branches/release/2.8.x/protection --input /tmp/prot.json
gh api repos/Ufonik88/EntropicMem/branches/release/2.8.x/protection -q '.allow_force_pushes.enabled, .allow_deletions.enabled'   # false false
git push origin --delete fix/perf-smoke-probes claude/eloquent-fermi-9e73i3 claude/chunk-1-s2-closeout
```
- `fix/perf-smoke-probes` is merged into `main`.
- `claude/eloquent-fermi-9e73i3` equals `7e02412`, which `release/2.8.x` and the tag now hold.
- `claude/chunk-1-s2-closeout` equals a commit already on `main`.
- Keep `main` and `release/2.8.x`.
- Locally, delete the stale branches whose contents are in `main`: `fix/em-211-facade`, `fix/plan-gaps`, `em/em-205…208*`.

### H3. Paste the master plan text into the repo copy of the plan
- In `docs/plan/REMAINING_PLAN.md` §6, under every card marked "(plan text needed)", paste the card's **title, Files and AC verbatim from master plan §5**. The cards: EM-302, EM-304, EM-305, EM-403, EM-503, EM-703, EM-901, and S6's card list.
- Also paste the full §5 text for EM-209, EM-210, EM-211 and EM-212.
- Don't summarise, and don't change existing lines. Where the plan contradicts §6, keep both and mark it `CONFLICT:`.
- Before pushing, run the privacy digest check on the file. Plan text may name real things; replace any hit with a neutral word and report only file, line and column.
- One commit, "Docs: plan §5 card text for the remaining cards". Push to a branch, wait for green CI on that SHA, then fast-forward `main`.

### H4. The cleanup cron (asked four times; paste the line itself)
Paste the exact line of `entropicmem_old_clone_cleanup.sh` that tests `origin/main`. It must be:
```
git merge-base --is-ancestor 35a02f4a2eb6ab1bff2468a6d276b7509774456b origin/main
```
If it isn't, fix it. Dry-run with `--dry-run` and paste the output. It must be right before 2 Oct.

### H5. Catalog re-pin to 2.8.1 (after H1)
1. `PIN = 7e02412366408234629e759a575edc31eb138721` (confirm with `git ls-remote … 'refs/tags/v2.8.1^{}'`).
2. Start a **fresh** branch off upstream `NousResearch/hermes-agent` `main`. Never reuse or push `catalog/entropicmem-2.8.0`, which ends in Teknium's commit.
3. In the `entropicmem` entry, set version `2.8.1`, sha `PIN`, and move every pinned URL to `PIN`. Change nothing else.
4. Checks:
   - `scripts/validate_plugin_catalog.py` passes;
   - every pinned URL returns HTTP 200 with no token;
   - `hermes plugins validate --install-deps plugins/entropicmem` passes on a clean checkout of `PIN`, with only the two known "declared but not registered" warnings.
   Use your safe `HERMES_HOME` method, **on an idle box only**: last time the check exhausted swap.
5. Open the PR. Use this body (plain words):
   > EntropicMem 2.8.1: safety patch on 2.8.0, pinned at the `v2.8.1` tag (`7e02412`). It contains the fixes from the 2.8.0 review:
   > - `ingest` re-validates every redirect hop;
   > - vector embeddings are opt-in, so no model is downloaded unless the user sets `embeddings_enabled: true`;
   > - the CLI honours `HERMES_HOME` for the shared store;
   > - the duplicate `hooks:` list is removed;
   > - the README lists every network touchpoint;
   > - it states that native Windows is unsupported on 2.8.x.
   >
   > Tools and hooks are unchanged (7 and 5, same names). The disclosure only shrinks: embeddings egress is now opt-in. No history was rewritten; `v2.8.0`/`060063d` remain.
6. **After it merges,** run a fresh catalog install:
   - sha is `PIN`, 7 tools and 5 hooks load, remember → recall works;
   - with `sentence-transformers` importable but not enabled, no model download happens (no growth in `~/.cache/huggingface`).
7. Point the catalog-check cron at 2.8.1.

### H6. Public reply on #122476: only if the owner says "post it"
The draft was in the previous hand-off. Don't post without that word.

### H7. Report to the owner (plain language, short)
- H1–H5 results, with the tag SHA and the catalog PR link.
- The H4 cron line.
- Anything you could not do, and why.

When H1–H5 are done, **EntropicMem is at the safe point.** Feature work stays stopped until the owner schedules Chunk 2.

---

## Part B: Chunk 2, the next development chunk (only when the owner schedules it)

**Topic:** decide the EM-209 and EM-210 plan deviations, with at most one small fix.

**Why this chunk:** Hermes's plan §5 comparison found a handful of places where the job queue and backup manager differ from the plan's wording. Most are naming or numbers and only need recording. At most one is a missing piece a user would feel. It's small, touches no schema or migration, and nothing near the provider's live path.

**Budget:** one session, at most 4 commits. Stop at any stop condition in plan §3.1.

**Owner:** Hermes implements. Claude Code reviews the branch before merge (the owner relays the report).

### 2.0 Pre-flight (read-only)
1. `main` must contain `cdff579`, and `35a02f4` must be an ancestor of `main`.
2. **Baseline:** `env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_VAULT_PATH -u ENTROPICMEM_INDEX_DB ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1 python -m pytest -q` gives 1462 passed, 2 skipped, 3 xfailed (or more passed, if H3 added nothing that changes tests). `ruff check .` is clean.
3. H3 must be done: the EM-209 and EM-210 §5 text must be in `docs/plan/REMAINING_PLAN.md`.

### 2.1 Decide each deviation (docs only, one commit)
In `docs/V3_FOUNDATIONS.md`, add a section **"Recorded deviations from the plan"**. Give each item one line with **Decision** (keep / fix) and **Why**, quoting the plan's AC line.

| Card | Deviation | Default decision |
|---|---|---|
| EM-209 | no `entropicmem worker run` CLI subcommand, and no cron doc | **fix** if the AC names it (2.2) |
| EM-209 | no per-job `time_budget` | keep; leases + heartbeat cover runaway jobs. Fix only if AC |
| EM-209 | backoff `30·2^(attempts-1)`, cap 3600, ±10 % jitter, versus `2^attempts·30s` | keep; same curve shifted by one step, tested |
| EM-209 | `claim(worker_id, *, types, lease_seconds)` versus `(worker_id, types, lease_s)` | keep; keyword-only is safer. Record |
| EM-210 | `create()` versus `snapshot()` | keep, and add `snapshot = create` alias only if the AC names `snapshot` |
| EM-210 | `memory.db` only, not `index.db` | keep; `index.db` is rebuildable from the vault. Fix only if AC |
| EM-210 | flat files versus `backups/<ts>-<reason>/` dirs | keep; manifests pair the files. Record |
| EM-210 | retention 7 routine + 5 safety, versus EM-113 keep-10 + 1/day/7 days | record. EM-113 governs the v2 engine's own backups, which are unchanged |
| EM-210 | no once-per-hour throttle, and no "100 forgets" AC test | **fix** only if it's EM-210's AC (not EM-113's) |

### 2.2 At most one small fix (one commit, test first)
Pick the first item that the pasted AC makes mandatory; otherwise skip this step.
- **Preferred: `entropicmem worker run [--once] [--max-jobs N]`.** It runs `JobWorker.run_until_idle()` against a v3 database with the registered handlers. Today that is only the `backup` handler.
  - It **refuses a live path** exactly like migrations (`assert_safe_db_path`), unless `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1`.
  - It prints outcomes as JSON (`{"done": n, "failed": n, "dead": n}`) and exits non-zero on any `dead`.
  - Tests: run it on a temp v3 database; a refused live path; mutation check.
- **Otherwise: the EM-210 throttle.** `BackupManager.create(reason="pre-forget")` makes at most one per hour, and the AC's "100 forgets" test gives at most 1 new backup.

### 2.3 End of chunk
1. Push `em/chunk-2-deviations`. Wait for green CI on the exact SHA (`windows-import` included on `main`). Claude Code reviews, then fast-forward `main` and delete the branch.
2. **Update `docs/plan/REMAINING_PLAN.md`:** §2 (SHAs, counts), §5 (ledger) and §6.1 (remove decided items).
3. **Replace this file's Part B** with the next single chunk. Recommended: **EM-211 facade, reads only**:
   - `get_fact`, `stats` and `recall_with_relevance` over `em.store`, with the `legacy_id = sha256(content)[:16]` rule;
   - added to `ENGINES` behind a test flag, so no provider code path changes.
4. Report to the owner in plain language. Hermes updates MASTER_TODO. Claude Code produces a `/save` file.

### Explicitly out of scope for Chunk 2
- The EM-211 facade itself, and any provider wiring to v3.
- The v3 cutover, or anything touching `~/.hermes/entropicmem*`.
- Releases, tags, catalog PRs and public comments.
- The tool rename.
- Changes to `provides_*`, or to migrations `0001`–`0003`.
- New dependencies.
- S3 and later.
