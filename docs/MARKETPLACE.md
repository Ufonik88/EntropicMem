# EntropicMem and the Hermes Marketplace

How the GitHub repo and the Hermes plugin catalog are managed: what the entry is,
what is owner-gated, and how a release actually reaches users.

**Read this after** [`AGENTS.md`](../AGENTS.md) (the never/always rules live there
and are not repeated here) and [`MASTER_TODO.md`](../MASTER_TODO.md) (current
state). The release procedure below is **owner-gated end to end** — agents prepare,
the owner approves.

> "Marketplace" means the **Hermes plugin catalog**:
> `plugin-catalog/entropicmem.yaml` in `NousResearch/hermes-agent`. That YAML is
> the only way users get EntropicMem via `hermes plugins install entropicmem`.

---

## 1. The repos, and what each one is

| Repo | Visibility | Role |
|---|---|---|
| `Ufonik88/EntropicMem` | **Public** | The source. Everything committed here — **including git history** — is visible to anyone, forever. |
| `NousResearch/hermes-agent` (`plugin-catalog/entropicmem.yaml`) | Public upstream | The Marketplace entry. One reviewed YAML that pins an exact commit of this repo. |
| `Ufonik88/EntropicMem-archive` | **Private** | Old history containing personal data. **Never make public, never link from anything public.** |

**Branch model on this repo:**

- **`main`** — the 3.0 development line (`3.0.0.dev0`). All development happens
  here. Protected: no force-push, no deletion.
- **`release/2.8.x`** — the released line, tip `7e02412` = **v2.8.1**, protected.
  This is what the Marketplace pins and what users install. Frozen.
- The remote carries **only** those two branches. Merged branches are deleted.
- The republish baseline `35a02f4` must stay an ancestor of `main` forever.
- **Dead SHAs — never push them anywhere public:** `e47e956`, `0e5e39c`, `93ef951`,
  `6b62a21`, `f15fe12`, `9a2c1df`, `437c89b`.

---

## 2. How the entry works

- The entry names: `repo`, an **exact 40-hex lowercase commit SHA**, `subdir`,
  `version`, `description`, `capabilities` (`provides_tools` / `provides_hooks` /
  `requires_env`), docs/image/screenshot URLs, maintainer, tier.
- **The pin IS the release.** Branches, tags and short SHAs are rejected by the
  loader. The pinned commit is what is cloned and validated on every install.
- **Install mechanics:** the installer clones the repo at the pin and moves **only
  `subdir`** into `~/.hermes/plugins/entropicmem/`; the rest of the clone is
  discarded. The plugin directory must therefore be **self-contained** —
  `plugin.yaml` plus the full engine under `plugins/entropicmem/scripts/`, deps
  vendored, no repo-root-relative imports at runtime.
- **No self-updating code.** A listed plugin must not fetch and replace its own
  files.
- **`capabilities:` must match what `register()` registers at the pinned commit.**
  The catalog review verifies the plugin against exactly those lists; `plugin.yaml`
  is the single declaration (keep `provides_tools`/`provides_hooks`, no duplicate
  `hooks:` list).
- **`description:` is a security claim, not marketing.** Every behavioural claim
  in the entry, the manifest, the README and the skill docs must be backed by the
  code at the pinned commit. Over-claiming is a review finding.

### Rules that follow from the pin

1. **Never rewrite published history. Never delete a branch, tag or commit that a
   release or catalog pin points at.** If the pinned SHA vanishes the entry becomes
   uninstallable and every installed copy's `hermes plugins update` breaks. This
   already happened once (the 2.8.0 republish made `437c89b` disappear); the
   maintainer asked that it never happen again. Fix mistakes forward with a new
   commit.
2. **Never rename or remove a provider tool, and never change
   `provides_tools`/`provides_hooks`, outside a release that also re-pins the
   catalog entry.** The tool rename `entropicmem_patch_core` →
   `entropicmem_patch_core_memory` ships only with the 3.0 release (EM-904).
3. **A chunk of work leaves the Marketplace entry untouched** unless that chunk
   *is* a release.
4. All SHA-pinned fields move together on a re-pin — `sha`, `docs_url`, `image`,
   every `screenshots:` URL, and `version:` — in the same PR.

---

## 3. How a release reaches the Marketplace

**Owner-gated end to end.** Order of operations matters: the tag exists *before*
the pin moves, so a force-push can never drop the pinned commit.

1. Create/branch the release line from the intended commit; push it.
2. Run the full gate battery ([`AGENTS.md`](../AGENTS.md), and `MASTER_TODO.md`'s
   gates table) on that exact commit, on Python 3.10 **and** your default
   interpreter.
3. Create the annotated tag with an explicit noreply identity, push it:
   ```bash
   git -c user.name=Ufonik88 -c user.email=Ufonik88@users.noreply.github.com \
     tag -a vA.B.C <sha> -m "..."
   git ls-remote origin 'refs/tags/vA.B.C^{}'    # verify it resolves
   ```
4. Publish the GitHub Release: `gh release create vA.B.C --verify-tag ...`.
5. Protect the release branch (block force-push and deletion).
6. **Only now** open the catalog re-pin PR.
7. Catalog PR mechanics:
   - **Start a fresh branch off upstream `NousResearch/hermes-agent` main.** Never
     reuse or push the old fork branch `catalog/entropicmem-2.8.0` (it ends in
     Teknium's `cdfcd83`).
   - Run both gates locally first:
     - structural: `python3 scripts/validate_plugin_catalog.py <dir-with-the-yaml>`
       from an activated `hermes-agent` checkout (otherwise it fails on missing
       `ruamel.yaml`);
     - pinned source: `hermes plugins validate --install-deps <plugin-dir>` against
       a fresh clone checked out **at the new pin**.
   - Title: `chore(plugin-catalog): re-pin entropicmem to <version>`.
   - PR body = evidence: validator output, security-scan outcome, capabilities-match
     statement, owner-submission statement, license, and that image/screenshot URLs
     return 200 **after** pushing the SHA.
   - Expect `action_required` / "no checks reported" / `BLOCKED` while awaiting
     maintainer approval. That is the normal state for a fork PR, not a failure.
8. Verify a fresh install in an **isolated** `HERMES_HOME`:
   ```bash
   export TEST_HOME=$(mktemp -d)
   rm -f "$TEST_HOME"/installs/*/source-completion-pending   # see pitfall below
   HERMES_HOME=$TEST_HOME hermes plugins install entropicmem --ref <40-hex> --no-enable --no-deps
   cat "$TEST_HOME/plugins/entropicmem/.hermes-catalog.json"  # sha must equal the pin
   ```
   Until the PR merges, the local catalog cache still carries the old pin, so
   always test with an explicit `--ref`.
9. Report to the owner: what landed, where, verified how.

---

## 4. Verifying the live entry

Do not assume the entry matches this doc — check it:

```bash
~/.local/bin/ghx api repos/NousResearch/hermes-agent/contents/plugin-catalog/entropicmem.yaml \
  -H "Accept: application/vnd.github.raw"
```

**Last verified 2026-10-07:** entry `entropicmem`, **version 2.8.1, pinned at
`7e02412366408234629e759a575edc31eb138721`**, subdir `plugins/entropicmem`,
maintainer `Ufonik88`, tier `community`, `requires_hermes: ">=0.21"`, and
capabilities matching `plugin.yaml` exactly (7 `provides_tools`, 5
`provides_hooks`). That SHA is the `v2.8.1` tag commit on `release/2.8.x`.

---

## 5. Pitfalls that have already cost time

- **`main` and `release/2.8.x` are not patchable into each other.** `main` imports
  the `em` package, so it is a different program. Cherry-picks only ever go one
  way, with `-x`.
- **There is no 2.8.x work left.** 2.8.1 is tagged, released, catalog-pinned and
  install-verified. Check [`MASTER_TODO.md`](../MASTER_TODO.md) before "finishing"
  anything already finished.
- **The v2 `MemoryEngine` is still the live path.** Editing `em/` changes nothing
  users see until the wiring chunk.
- **`hermes plugins validate` prints two "declared but not registered" warnings**
  for `provides_tools`/`provides_hooks`. Expected and kept on purpose — the catalog
  verifies against those lists, and the validator cannot see tools a
  MemoryProvider exposes via `get_tool_schemas()`.
- **raw.githubusercontent.com negative-caches 404s** for a few minutes after a
  repo visibility flip, and a private repo 404s anonymously for *every* URL. Check
  pins authenticated (`gh api repos/.../contents/<path>?ref=<sha>`) before
  concluding an asset is missing.
- **The catalog-check cron exhausted 4 GiB of swap once** by building a second
  `HERMES_HOME`. Run it only when the box is idle.
- **The first `hermes` CLI run in a fresh `HERMES_HOME`** arms a source-completion
  tail whose next run rebuilds the desktop app and **stops the running desktop
  session**. Neutralize it with the `rm -f .../source-completion-pending` above.
- **GitHub access:** `git push` uses the machine's stored credential for
  `Ufonik88`; `~/.local/bin/ghx` wraps `gh` with the same token. Never write, log
  or print tokens.
