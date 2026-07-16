# Memory Model

EntropicMem uses four cooperating layers:

| Layer | Store | Role |
|-------|-------|------|
| L1 Hot cache | `Wiki-Cache.md` | Fast orientation each session |
| L2 Facts | `memory.db` | Durable facts with FTS (`remember`/`recall`) |
| L3 Vault | Markdown files | Linked knowledge archive |
| L4 Index | `index.db` | FTS + graph edges over vault |
| L5 Graph | `export/graph.html` | Visual exploration |

**Write policy:** stable facts → `remember`; source knowledge → `ingest`/`note`; ephemeral reasoning → do not persist.

**Identity:** `entropic_id = SHA256(content)[:16]` deduplicates facts and links vault notes to memory rows.
