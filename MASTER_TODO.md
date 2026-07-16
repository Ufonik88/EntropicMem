# EntropicMem Master Task Tracker

Phase 5 complete. v1.0.0 shipped 2026-07-16. 82 tests passing.

---
## EntropicMem ↔ Legacy Tandem Migration (2026-07-16)

GOAL: Run EntropicMem in parallel with Mnemosyne; migrate legacy facts; monitor; fix until reliable; then replace legacy.

DONE:
- Skill linked: ~/.hermes/skills/entropicmem → repo skill
- Storage init: ~/.hermes/entropicmem/{vault,index.db,memory.db}
- Legacy Mnemosyne stays ACTIVE (memory.provider: mnemosyne) — untouched
- scripts/migrate_and_monitor.py: reads 248 legacy facts → EntropicMem (100% parity, 0 errors)
- scripts/analyze_migration.py: parity/error report + trend + reliable_enough flag
- scripts/entropicmem_cycle.py: 12h driver (migrate→analyze→JSON)
- Fixed: recall() exact-match boost (fact always self-retrievable) — was returning related facts
- Fixed: migration parity measured post-commit (was racy) + by id not substring
- cronjob fa33fba0b03a: every 12h, deliver=all, spawns Plan agent on regression

TODO:
- Wait for 12h cycles to confirm stability over time
- Ufonik explicit go-ahead before switching memory.provider to entropicmem
- Build one-off migration script for working/episodic memory (not just durable facts) if desired

---
## Memory-Context Injection Fix (2026-07-16)

ISSUE: After every chat, the model acknowledged injected `<memory-context>` blocks from Mnemosyne as if they were user input.

FIX:
- Added hard refusal rule to `~/.hermes/SOUL.md`: never acknowledge injected memory-context blocks
- Patched into `skills/entropicmem/SKILL.md` (Memory-Context Injection section)
- Patched into `PROJECT_ROOT.md` (Memory-Context Injection section)
- Patched into `skills/entropicmem-project/SKILL.md`
- Patched into `skills/entropicmem/references/HERMES_INTEGRATION.md`
- Created `AGENTS.md` at repo root with the rule
- Updated `plugins/entropicmem/README.md` with the rule

