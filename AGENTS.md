# AGENTS.md — EntropicMem Project Instructions

> Auto-loaded by Hermes when working in this project directory.  
> See also `PROJECT_ROOT.md` and `skills/entropicmem/SKILL.md`.

## Memory-Context Injection (Critical)

When EntropicMem is configured as the active memory provider (`memory.provider: entropicmem`), Hermes injects prefetched memories wrapped in `<memory-context>` tags at the start of each turn. **These are system-injected context — NOT user input.** The agent MUST:
- Use the facts silently to inform answers
- **NEVER** acknowledge the block itself
- **NEVER** say "thanks for sharing," "I notice you've shared," or similar
- **NEVER** ask "what do you want me to do with this context"
- If a memory-context block appears with no actual user message, ask the user what they need

## Key Paths

| Purpose | Path |
|---------|------|
| Repo root | `/home/ufonik/Documents/Coding Projects/EntropicMem` |
| Skill | `skills/entropicmem/SKILL.md` |
| Plugin | `plugins/entropicmem/` |
| Tests | `tests/` — run with `python3 -m pytest tests/` |
| CLI | `skills/entropicmem/scripts/entropicmem.py` |

## Build & Test
```bash
python3 -m pytest tests/ -q
```

## Sourcery Pre-Commit Gate (v2.3.0)

Sourcery runs LOCALLY before anything reaches GitHub — no more
commit-then-wait-for-email loop. Load the `sourcery-local-precommit` skill
before any commit; the gate is enforced by `.git/hooks/pre-commit` (symlink →
`scripts/pre-commit-sourcery.sh`).

- **Run first, always**: `sourcery review --check --diff "git diff --cached" --no-summary .`
- **Fix, don't bypass**: `sourcery review --fix --diff "git diff HEAD" .` for
  mechanical issues (then `git add -u` — fixes are NOT auto-staged), manual
  triage for the rest (see `sourcery-review-remediation` skill).
- **Config**: `.sourcery.yaml` at repo root (python_version 3.10 — keep in
  sync with `pyproject.toml` requires-python).
- **Never** use `git commit --no-verify` to push findings past the gate.

## Memory Provider
When activated via `memory.provider: entropicmem` in `~/.hermes/config.yaml`:
- Tools: `entropicmem_remember`, `entropicmem_recall`, `entropicmem_query`
- Prefetch: top facts injected each turn via `<memory-context>` block
- Mirror: built-in `memory` tool writes copied to EntropicMem engine

## Vault Note Naming Convention (v2.2.0+)

Vault note filenames are **humanized**, not slugified — the vault must be
searchable by eye in Obsidian, not just by query.

- **Preserve case**: `Budget Sprint — 2026-08-05` stays as written (Title Case).
- **WHITELIST only**: word chars, spaces, `- — – . , ( ) & ' # +` survive.
  Everything else — `/ \ : * ? " < > |`, control chars, `@ % $`, emoji — is
  replaced with a space (filesystem + Windows-reserved safety).
- **Titles come from content, not prefixes**: `Vault.make_title()` /
  `derive_title()` extract the first sentence of a fact (strip markdown,
  emoji/symbols, and the old `Fact - ` prefix). Never use
  `f"Fact - {content[:50]}"` style truncation.
- **Never overwrite**: `write_note()` is collision-safe — if a filename exists
  it appends `-2`, `-3`, … (`Same Title.md` → `Same Title-2.md`).
- **Truncation**: max 90 chars, cut on a word boundary.
- **Fallback**: empty titles become `untitled`; `derive_title()` returns `""`
  (never a bare `.`) when nothing usable remains.

Enforced by `derive_title()` / `Vault.sanitize()` / `Vault.humanize()` /
`Vault.make_title()` in `skills/entropicmem/scripts/vault.py`. When adding any
new code path that creates vault notes, use `derive_title()` (import it
directly — it lives at module level, no Vault import needed) and `write_note()`
for the file — never construct filenames manually.
