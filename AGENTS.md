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
