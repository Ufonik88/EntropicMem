# EntropicMem — Risk Register (Standalone Product)

Cross-reference: `PROJECT_PLAN.md` §10. Owner: Entropy / Ufonik.

Severity: **High** = blocks v1.0 · **Med** = degrades product · **Low** = polish

| # | Risk | Severity | Mitigation | Status |
|---|------|----------|------------|--------|
| 1 | Agents keep using chat-only memory and ignore EntropicMem | **High** | SKILL.md write policy + session-end promotion checklist | Open |
| 2 | Dual stores (memory.db + vault) confuse source of truth | **High** | Document L2 vs L3; remember dual-writes; `memory project` for materialization | Open |
| 3 | Incomplete docs leave product unusable without tribal knowledge | **High** | Phase 5 reference + docs completion before v1.0 | Open |
| 4 | Legacy wording implies external dependencies | **Med** | CLI/help/template purge; this replan as language lock | In progress |
| 5 | FTS-only recall misses paraphrases | **Med** | Optional semantic re-rank; tagging/title conventions | Accepted for v1 core |
| 6 | Graph unusable on large vaults | **Med** | max-nodes 500 + domain/importance filters | Mitigated |
| 7 | `/learn` cannot install pip extras | **Med** | Stdlib core; `--check-deps` | Mitigated |
| 8 | Index drift after manual vault edits | **Med** | Document rebuild path; upsert on CLI writes | Open |
| 9 | entropic_id collisions (SHA256[:16]) | **Low** | Negligible at expected scale; log on collision if detected | Accepted |
| 10 | Premature Hermes MemoryProvider work | **Med** | Phase 6 only after v1.0 standalone CLI/skill ships | Open |

## Decision log

| Decision | Rationale |
|----------|-----------|
| Standalone, not companion | Product goal is full ownership of memory workflows |
| Own MemoryEngine | Hermetic installs; no foreign DB required |
| Skill + CLI primary surface | Hermes footprint ladder; works everywhere terminal works |
| Dual vault + fact store | Human browsability + efficient fact identity/dedup |
| Phase 6 provider optional | Deep integration after product is complete |
