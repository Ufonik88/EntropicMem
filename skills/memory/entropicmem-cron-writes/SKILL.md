---
name: entropicmem-cron-writes
description: Persist durable facts to EntropicMem from scheduled cron jobs / non-interactive contexts. Use whenever a cron or background task must store knowledge and the interactive memory / entropicmem_* tools are unavailable or unreliable.
version: 1.1.0
---

# EntropicMem durable writes from cron / non-interactive contexts

## When to use

A scheduled cron job, background task, or any non-interactive run must persist durable
facts to **EntropicMem**.

## Why interactive tools fail here

Hermes cron constructs `AIAgent(skip_memory=True)` on purpose so cron system prompts
do not corrupt user representations (`cron/scheduler.py`). Effects:

- External MemoryProvider (EntropicMem) is **not loaded**
- `entropicmem_*` tools are **absent** from the cron tool list
- Hermes `memory` tool returns **"Memory is not available"** (store is None), unless
  the `"memory"` toolset is explicitly enabled — and even then it writes the
  **file-backed** MEMORY.md store, **not** EntropicMem

Full write-up: `docs/CRON_MEMORY_PATH.md` in the EntropicMem repo.

## The correct call (preferred)

One-shot helper (stores + verifies recall):

```bash
python3 ~/.hermes/scripts/entropicmem_cron_remember.py \
  "concise durable fact here" \
  --domain Knowledge \
  --importance 0.7 \
  --source cron
```

Batch JSON:

```bash
python3 ~/.hermes/scripts/entropicmem_cron_remember.py --json '[
  {"content":"fact one","domain":"Knowledge","importance":0.8},
  {"content":"fact two","domain":"Projects","importance":0.6}
]'
```

Self-test (cron smoke check):

```bash
python3 ~/.hermes/scripts/entropicmem_cron_remember.py --self-test
```

## Direct Python API (equivalent)

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".hermes" / "skills" / "entropicmem" / "scripts"))
from memory_engine import MemoryEngine

db = Path.home() / ".hermes" / "entropicmem" / "memory.db"
content = "...concise durable fact..."
with MemoryEngine(db) as engine:
    eid = engine.remember(
        content=content,
        title=content[:60],
        domain="Knowledge",
        source="cron",
        importance=0.7,
    )
    hits = engine.recall(content, top_k=5)
assert any(getattr(h, "id", None) == eid for h in hits), "recall verify failed"
```

`entropic_id` is deterministic (SHA256 of content) — re-storing identical content dedups.

## Paths (locked)

| Artifact | Path |
|----------|------|
| Memory DB | `~/.hermes/entropicmem/memory.db` |
| Vault | `~/.hermes/entropicmem/vault/` |
| Engine scripts | `~/.hermes/skills/entropicmem/scripts/` |
| Cron helper | `~/.hermes/scripts/entropicmem_cron_remember.py` |
| Repo canonical | `scripts/entropicmem_cron_remember.py` |
| Design doc | `docs/CRON_MEMORY_PATH.md` |

## Verify after writing (mandatory)

- Helper exit code `0` and `"verified_recall": true`, **or**
- Manual `engine.recall(content)` returns a hit with matching `entropic_id`.

Never report success without verification.

## What NOT to do

- Do not call Hermes `memory` tool for EntropicMem durable writes from cron.
- Do not call `entropicmem_remember` / other provider tools from cron (not loaded).
- Do not set `skip_memory=False` on cron agents without upstream design review.
