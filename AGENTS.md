# Rules for agents working on EntropicMem

Read this at the start of every session, then `docs/V3_FOUNDATIONS.md` before touching `plugins/entropicmem/scripts/em/`.

## Never

1. Never push to `main` without green CI on the exact commit you're merging. Check that the check-run `headSha` equals the SHA you pushed; a green result for the previous commit is not a green result.
2. Never force-push, never tag, and never use GitHub's web "Merge" button or web editor (they stamp the owner's account email on the commit). Merge with `git merge --ff-only` from the command line.
3. Never write to the live store (`~/.hermes/entropicmem*`). Measure on copies. Run tests with `ENTROPICMEM_MEMORY_DB`, `ENTROPICMEM_VAULT_PATH` and `ENTROPICMEM_INDEX_DB` unset.
4. Never put a real person, employer, family or bank name in any file, test data included. Use Acme / Globex / Initech, Alice / Bob Example, example.com, and phone digits from the guard's allowlist (`0000`, `1234`, `9876`, `5432`).
5. Never commit an identifier list, hashed or not. The privacy denylist lives outside the repo.
6. Never weaken, skip, delete or xfail a test to get green. If a gate can't go green honestly, stop and report.
7. Never edit an applied migration. Add a new one.
8. Never delete CHANGELOG history. Moving an entry means every line arrives somewhere; check with a line-by-line diff.

## Always

1. One card per commit, each with a CHANGELOG line under `[Unreleased]`, in the right section: Added for new features, Fixed for bugs, Security for privacy/security.
2. Write the test first, watch it fail for the right reason, then mutation-check it: break the code the test protects and confirm it goes red.
3. Before you push, run:
   - `python -m pytest -q`
   - `ruff check .`
   - if you touched anything platform-sensitive, ask "does this hold on Windows?" (see invariant 10 in the foundations doc)
4. Before you push, locate privacy collisions without printing the denylist. Hash each word in your changed files and compare against `~/.config/entropicmem/privacy-digests.txt`, reporting only file, line and column.
5. After every push to `main`, confirm `identity-guard` is green on that commit. If it is red, stop and tell the owner.
6. Keep product code 3.10-compatible. CI runs 3.10–3.13; Hermes itself runs on 3.11.
7. Report plainly: what changed, the test counts, what you could not verify and why.

## Ask the owner only for

- anything touching their real data or the live store (including the v3 cutover);
- releases, tags and the Hermes catalog entry;
- a test that cannot pass without weakening it.
