# Rules for agents working on EntropicMem

**Start every session at [`MASTER_TODO.md`](MASTER_TODO.md)** — the one short
canonical page: where the project is, what is in flight, what is next, and the
gates. Then this file, which is the rules. Then
`docs/V3_FOUNDATIONS.md` before touching `plugins/entropicmem/scripts/em/`, and
`docs/plan/NEXT_CHUNK.md` for the single chunk currently planned. For anything
touching the Hermes Marketplace — the catalog entry, a re-pin, or a release —
read [`docs/MARKETPLACE.md`](docs/MARKETPLACE.md) first; the release procedure is
owner-gated end to end.

This works the same on any harness or platform: everything needed is a file in
the repo, and nothing depends on which agent or machine you are.

## Document control — first and last

This is not optional, and it is not the last thing you remember.

1. **Before you start any work**, update `MASTER_TODO.md` and the planning docs
   (`docs/plan/REMAINING_PLAN.md`, `docs/plan/NEXT_CHUNK.md`) so they describe the
   project's **real** current state — what is done, in enough detail that nobody
   redoes it, and what the next logical steps are.
2. **Then do the development work.**
3. **Before you finish**, update them again with what you completed and what
   comes next.

**Never end a development session without step 3.** Code that is committed while
the docs still describe the previous state is an unfinished task: it leaves the
next agent to reconstruct history and re-derive what is in flight. A session that
changed code and did not touch these files has failed, however green the gates
are.

Both ends of the rule are load-bearing. Step 1 is what lets you start without
guessing; step 3 is what lets the *next* agent start without guessing.

Accuracy is the point, so **write down what is actually true, including what is
not finished.** A commit on an unmerged branch is "committed, not merged" — not
"landed". An unpushed branch has no CI. If a gate could not be run, say which
and why rather than implying it passed. Overstating progress in these docs is
worse than leaving them out of date, because the whole point is that they can be
trusted.

Enforced by `tests/test_master_todo.py`, which fails when `MASTER_TODO.md` is
missing, unlinked from this file and the README, missing a required section, or
records a SHA that is not a real ancestor of the branch.

## Never

1. Never push to `main` without green CI on the exact commit you're merging. Check that the check-run `headSha` equals the SHA you pushed; a green result for the previous commit is not a green result.
2. Never force-push, never tag, and never use GitHub's web "Merge" button or web editor (they stamp the owner's account email on the commit). Merge with `git merge --ff-only` from the command line.
3. Never write to the live store (`~/.hermes/entropicmem*`). Measure on copies. Run tests with `ENTROPICMEM_MEMORY_DB`, `ENTROPICMEM_VAULT_PATH` and `ENTROPICMEM_INDEX_DB` unset.
4. Never put a real person, employer, family or bank name in any file, test data included. Use Acme / Globex / Initech, Alice / Bob Example, example.com, and phone digits from the guard's allowlist (`0000`, `1234`, `9876`, `5432`).
5. Never commit an identifier list, hashed or not. The privacy denylist lives outside the repo.
6. Never weaken, skip, delete or xfail a test to get green. If a gate can't go green honestly, stop and report.
7. Never edit an applied migration. Add a new one.
8. Never delete CHANGELOG history. Moving an entry means every line arrives somewhere; check with a line-by-line diff.
9. Never rewrite published history, and never delete a published branch or tag that a release or catalog pin points at. The Hermes plugin catalog pins an exact commit SHA. If that commit vanishes, the listed entry becomes uninstallable and every installed copy's `hermes plugins update` breaks (the 2.8.0 republish made the old `437c89b` pin disappear; the catalog maintainer asked for this never to happen again). Mistakes in published history are fixed forward with a new commit.
10. Never rename or remove a provider tool, or change `provides_tools`/`provides_hooks`, outside a release that also re-pins the catalog entry. The catalog review verifies the plugin against those lists.

## Always

1. One card per commit, each with a CHANGELOG line under `[Unreleased]`, in the right section: Added for new features, Fixed for bugs, Security for privacy/security.
2. Write the test first, watch it fail for the right reason, then mutation-check it: break the code the test protects and confirm it goes red. **A claim that the suite would catch a *class* of bug needs more than one removal** — deleting a single call is not proof the suite covers the class. Remove the logic in several independent ways and show each goes red (EM-301's document-frequency claim took three: no frequencies at all, the map ignored, and the formula flattened). **Restore each mutation from a copy, never `git checkout -- <file>`:** on a file with uncommitted work it discards the work, and on a new untracked file it fails and leaves the mutation applied — both silently, and the second one contaminated a mutation run on 2026-10-09 until the copy-based backups replaced it.
3. Before you push, run:
   - `python -m pytest -q`
   - `ruff check .`
   - if you touched anything platform-sensitive, ask "does this hold on Windows?" (see invariant 10 in the foundations doc)
4. Before you push, locate privacy collisions without printing the denylist. Hash each word in your changed files and compare against `~/.config/entropicmem/privacy-digests.txt`, reporting only file, line and column.
5. After every push to `main`, confirm `identity-guard` is green on that commit. If it is red, stop and tell the owner.
6. Keep product code 3.10-compatible. CI runs 3.10–3.13; Hermes itself runs on 3.11.
7. Report plainly: what changed, the test counts, what you could not verify and why.
8. **Finish with document control** (see the section above): `MASTER_TODO.md`, `docs/plan/REMAINING_PLAN.md` and `docs/plan/NEXT_CHUNK.md` describe what you did and what is next, and say plainly what is still unmerged or unverified. This holds even when the session ends in a stop or a report rather than a merge.

## Autonomy: decide and act

Do not wait for the owner unless it is genuinely necessary. Your judgement on
this project's internals outranks his, so pause only when the action is
irreversible or public:

- anything touching their real data or the live store (including the v3 cutover);
- releases, tags and the Hermes catalog entry, or any other public or
  irreversible external action.

Everything else — card assessment and rewrites, plan edits, dispatch, code
review, CI triage, docs, bug fixes — you decide, then report what you did.
Ask afterwards, not before.

A test that cannot pass without weakening it is still a hard stop: never
weaken it, report the gate instead.
