# EntropicMem Project Root

This folder (`/home/ufonik/Documents/Coding Projects/EntropicMem`) is the canonical project root for EntropicMem development.

## Auto-Load Skill

**Skill**: `entropicmem-project` (at `~/.hermes/skills/entropicmem-project/`)
**Purpose**: Sync conversations to Obsidian vault at `Brain/2nd Brain/EntropicMem Project.md`

### Session Protocol

1. **Start**: Read `/home/ufonik/Documents/Obsidian Vault/Brain/2nd Brain/EntropicMem Project.md`
2. **During**: Capture decisions/insights via `entropicmem-project` protocol
3. **End**: Update project note with dated Conversation Log entry

### Memory-Context Injection (Critical)
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
| Vault project note | `~/Documents/Obsidian Vault/Brain/2nd Brain/EntropicMem Project.md` |
| EntropicMem storage | `~/.hermes/entropicmem/` |
| EntropicMem skill | `~/.hermes/skills/entropicmem/` |
| EntropicMem plugin | `~/.hermes/plugins/entropicmem/` |
| Wiki script | `~/.hermes/scripts/wiki.py` |

## Current State

See vault project note — always the source of truth for project context across sessions.