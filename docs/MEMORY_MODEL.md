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

**Explainable recall (P1 D1):** Every `StoredFact` returned by `recall()`,
`recall_with_relevance()`, `recall_hybrid()`, and the plugin's
`entropicmem_recall` tool carries a `why_retrieved: list[str|dict]` field.
This additive field lists deterministic reason tokens explaining why the
fact was surfaced:

| Token | Meaning |
|-------|---------|
| `exact` | Exact content or ID match (always ranked first) |
| `fts` | FTS5 prefix match |
| `vector` | Vector similarity (when embeddings available) |
| `recency` | Temporal decay contributed to score |
| `importance` | Importance weighting contributed to score |
| `triple` | Graph/triple neighbor boost (hybrid path) |
| `domain` | Domain filter was applied |
| `fts` (LIKE fallback) | LIKE fallback used when FTS5 returned no results |

Tokens are plain strings today (`"fts"`); the field also accepts enriched
dicts (`{"signal": "fts", "score": 0.41}`) so numeric contributions can be
added later without breaking consumers. The list is deterministic and
requires no LLM.

**Write policy:** stable facts → `remember`; source knowledge → `ingest`/`note`; ephemeral reasoning → do not persist.

**Identity:** `entropic_id = SHA256(content)[:16]` deduplicates facts and links vault notes to memory rows.

**Governance:** writes are audited; `secret`-tier content is blocked;
auto-extracted candidates are quarantined as pending until promoted;
destructive operations require explicit confirmation.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the data flow and [CLI_REFERENCE.md](CLI_REFERENCE.md) for every command.
