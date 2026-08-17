# Memory Model

EntropicMem uses five cooperating layers:

| Layer | Store | Role |
|-------|-------|------|
| L1 Hot cache | `Wiki-Cache.md` | Fast orientation each session |
| L2 Facts | `memory.db` | Durable facts with FTS5 (`remember`/`recall`) |
| L3 Vault | Markdown files | Linked knowledge archive |
| L4 Index | `index.db` | FTS + graph edges over vault |
| L5 Graph | `export/graph.html` | Visual exploration |

Within L2, three complementary memory kinds live in `memory.db`:

| Kind | Table | Purpose | CLI |
|------|-------|---------|-----|
| Durable facts | `facts` + `facts_fts` | Stable knowledge, preferences, identity | `remember` / `recall` |
| Episodic memory | `episodes` + `episodes_fts` | "What happened when" session summaries | `episode add/list/stats` |
| Knowledge triples | `triples` | Subject–predicate–object relations (deduped, validity/confidence scored) | `triple extract/list/neighbors/path` |

Embeddings (`embeddings` table) attach 384-dim vectors to facts and enable
hybrid FTS+vector recall when `sentence-transformers` is installed.

**Write policy:** stable facts → `remember`; source knowledge → `ingest`/`note`; ephemeral reasoning → do not persist.

**Identity:** `entropic_id = SHA256(content)[:16]` deduplicates facts and links vault notes to memory rows.

**Governance:** writes are audited; `secret`-tier content is blocked;
auto-extracted candidates are quarantined as pending until promoted;
destructive operations require explicit confirmation.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the data flow and [CLI_REFERENCE.md](CLI_REFERENCE.md) for every command.
