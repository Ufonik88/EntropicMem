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

## Memory Provider
When activated via `memory.provider: entropicmem` in `~/.hermes/config.yaml`:
- Tools: `entropicmem_remember`, `entropicmem_recall`, `entropicmem_query`
- Prefetch: top facts injected each turn via `<memory-context>` block
- Mirror: built-in `memory` tool writes copied to EntropicMem engine

## Vault Note Naming Convention (v2.2.0+)

Vault note filenames are **humanized**, not slugified — the vault must be
searchable by eye in Obsidian, not just by query.

- **Preserve case**: `Budget Sprint — 2026-08-05` stays as written (Title Case).
- **Keep safe punctuation**: spaces, `- — – . , ( ) & ' # +`
- **Strip unsafe chars**: `/ \ : * ? " < > |` and control chars are replaced
  with spaces (filesystem + Windows-reserved safety).
- **Titles come from content, not prefixes**: `Vault.make_title()` extracts the
  first sentence of a fact (strips markdown, emoji, and the old `Fact - `
  prefix). Never use `f"Fact - {content[:50]}"` style truncation.
- **Never overwrite**: `write_note()` is collision-safe — if a filename exists
  it appends `-2`, `-3`, … (`Same Title.md` → `Same Title-2.md`).
- **Truncation**: max 90 chars, cut on a word boundary.
- **Fallback**: empty titles become `untitled`.

Enforced by `Vault.sanitize()` / `Vault.humanize()` / `Vault.make_title()` in
`skills/entropicmem/scripts/vault.py`. When adding any new code path that
creates vault notes, use `Vault.make_title()` for the title and `write_note()`
for the file — never construct filenames manually.
