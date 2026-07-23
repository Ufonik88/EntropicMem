# Cron Memory Path (Phase 1 / Gap 1)

**Status:** RESOLVED (by design) — 2026-07-23  
**Severity was:** CRITICAL  
**Resolution:** Permanent, documented cron write path via helper script.  
**Not a bug in EntropicMem.** Hermes core intentionally disables memory in cron.

---

## Root cause

Hermes cron jobs construct `AIAgent` with:

```python
skip_memory=True,  # Cron system prompts would corrupt user representations
```

Source: `hermes-agent/cron/scheduler.py` (AIAgent construction in the job runner).

### What `skip_memory=True` does

From `hermes-agent/agent/agent_init.py`:

1. **External MemoryProvider is not loaded** when `skip_memory` is true.  
   EntropicMem (`memory.provider: entropicmem`) never registers.  
   Therefore `entropicmem_remember` / `entropicmem_recall` / `entropicmem_query`  
   / `entropicmem_patch_core` are **not** available in cron tool schemas.

2. **Built-in `memory` tool store** is only created if the job explicitly enables  
   the `"memory"` toolset. Even then, that store is the **file-backed**  
   `MemoryStore` (`MEMORY.md` / `USER.md`), **not** the EntropicMem engine.  
   Writes would not land in `~/.hermes/entropicmem/memory.db`.

3. When no store is injected, `tools/memory_tool.py` returns:

   > `Memory is not available. It may be disabled in config or this environment.`

### Why Hermes does this

Cron job system prompts are synthetic operator instructions. Injecting them into  
the memory provider’s session / user representation would pollute durable memory  
with cron boilerplate. The gate is intentional product design, not a regression  
from switching to EntropicMem.

**Conclusion:** Do not “fix” this by forcing `skip_memory=False` in cron without  
a carefully designed write-only provider path that does **not** inject cron  
prompts into user representations. Until/unless Hermes adds such a path upstream,  
cron durable writes go through the helper.

---

## Official cron write path

```bash
python3 ~/.hermes/scripts/entropicmem_cron_remember.py \
  "concise durable fact" \
  --domain Knowledge \
  --importance 0.7 \
  --source cron
```

Batch:

```bash
python3 ~/.hermes/scripts/entropicmem_cron_remember.py --json '[
  {"content":"fact one","domain":"Knowledge","importance":0.8},
  {"content":"fact two","domain":"Projects","importance":0.6}
]'
```

Self-test:

```bash
python3 ~/.hermes/scripts/entropicmem_cron_remember.py --self-test
# expect exit 0 and "verified_recall": true
```

### Properties

| Property | Behavior |
|----------|----------|
| Target DB | `~/.hermes/entropicmem/memory.db` (override: `ENTROPICMEM_MEMORY_DB`) |
| Engine | `MemoryEngine.remember()` + immediate `recall()` verify |
| Dedup | Deterministic `entropic_id` (content hash) |
| Exit 0 | All writes verified in recall |
| Exit 2 | Write happened but recall verify failed |
| Exit 1 | Usage / hard error |
| LLM required? | **No** — safe for `no_agent: true` crons |

### Skill

Load `entropicmem-cron-writes` in any agent-driven cron that must persist facts.  
The skill forbids calling interactive `memory` / `entropicmem_*` tools from cron.

### Install / sync from this repo

```bash
install -m 755 scripts/entropicmem_cron_remember.py \
  ~/.hermes/scripts/entropicmem_cron_remember.py
# optional skill copy
mkdir -p ~/.hermes/skills/memory/entropicmem-cron-writes
cp skills/memory/entropicmem-cron-writes/SKILL.md \
  ~/.hermes/skills/memory/entropicmem-cron-writes/SKILL.md
```

---

## Verification (Phase 1 DoD)

```bash
# 1. Self-test
python3 ~/.hermes/scripts/entropicmem_cron_remember.py --self-test

# 2. Write + verified recall
python3 ~/.hermes/scripts/entropicmem_cron_remember.py \
  "Phase1 Gap1 verified $(date -Iseconds)" \
  --domain Knowledge --importance 0.9 --source phase1_verify

# 3. Cron-context (no_agent script path)
bash ~/.hermes/scripts/entropicmem_cron_phase1_verify.sh
# expect: PHASE1_CRON_VERIFY_OK
```

All three must exit 0 before calling Phase 1 complete.

---

## What NOT to do

- Do not set `skip_memory=False` on cron agents without upstream design review.
- Do not teach crons to call the Hermes `memory` tool for EntropicMem writes.
- Do not teach crons to call `entropicmem_*` provider tools (they are not loaded).
- Do not delete Mnemosyne or the rollback package as part of this phase.

---

## Downstream impact

Phases 2–3 (Notion sync, second-brain-capture-review, backups) **must** use this  
helper (or `no_agent` scripts calling MemoryEngine) for all durable writes.
