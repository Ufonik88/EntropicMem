# Memvid Feature Analysis — Deep Dive

**Date:** 2026-07-26  
**Source:** https://github.com/memvid/memvid (16K+ stars, Rust core, Apache 2.0)

## What Memvid Is

Memvid is a single-file memory layer for AI agents. It packages data, embeddings, search indices, and metadata into one portable `.mv2` file. No databases, no servers.

### Core Concepts

| Concept | Description |
|---------|-------------|
| **Smart Frames** | Immutable, append-only content units with checksums, timestamps, and metadata. Grouped into segments for compression and parallel reads. |
| **Embedded WAL** | Write-ahead log inside the file for crash recovery. Checkpoints at 75% occupancy or every 1,000 transactions. |
| **URI scheme** | Hierarchical paths (`mv2://meetings/2024-01-15`) for structured addressing. |
| **Time-travel** | Replay engine can rewind, replay, or branch any memory state. |
| **Codec Intelligence** | Auto-selects and upgrades compression (Zstd, LZ4) over time. |

### Feature Flags

| Flag | What It Provides |
|------|-----------------|
| `lex` | Full-text search with BM25 ranking via Tantivy |
| `vec` | HNSW vector similarity search with ONNX embeddings (384-dim BGE-small) |
| `clip` | CLIP visual embeddings for image search |
| `whisper` | Audio transcription |
| `api_embed` | Cloud API embeddings (OpenAI) |
| `temporal_track` | Natural language date parsing ("last Tuesday") |
| `parallel_segments` | Multi-threaded ingestion |
| `encryption` | Password-based encryption capsules (.mv2e) |
| `symspell_cleanup` | Robust PDF text repair |

### MV2 File Format

```
┌─────────────────────────────────────────────────────────────┐
│                        .mv2 FILE                            │
├─────────────────────────────────────────────────────────────┤
│ Header                 │ 4 KB                               │
├─────────────────────────────────────────────────────────────┤
│ Embedded WAL           │ 1-64 MB (capacity-dependent)       │
├─────────────────────────────────────────────────────────────┤
│ Data Segments          │ Frame payloads, compressed content │
├─────────────────────────────────────────────────────────────┤
│ Lex Index Segment      │ Tantivy index (optional)           │
├─────────────────────────────────────────────────────────────┤
│ Vec Index Segment      │ HNSW vectors (optional)            │
├─────────────────────────────────────────────────────────────┤
│ Time Index Segment     │ Chronological ordering             │
├─────────────────────────────────────────────────────────────┤
│ TOC (Footer)           │ Segment catalog + SHA-256 checksum │
└─────────────────────────────────────────────────────────────┘
```

### Frame Structure

Each frame is an immutable content unit:
- `frame_id` (u64) — monotonic unique identifier
- `uri` (String) — hierarchical path
- `payload` (bytes) — compressed content (Zstd/LZ4)
- `payload_checksum` (SHA-256) — integrity verification
- `tags` (Map) — user-defined key-value pairs
- `status` — active or tombstoned

### Search Architecture

1. **Lex search** — BM25 over full-text content (Tantivy)
2. **Vector search** — HNSW with cosine similarity (384-dim BGE-small)
3. **Graph search** — Entity pattern matching + triple extraction + hybrid ranking
4. **Hybrid fusion** — Combines BM25 + vector scores with configurable weights

### Graph Search Module

The `graph_search.rs` module provides:
- **QueryPlanner** — Analyzes natural language queries for relational patterns
- **EntityPattern** — Keyword-triggered patterns matching entity relationships
- **Triple extraction** — (subject, predicate, object) extraction from text
- **Hybrid ranking** — Graph-filtered candidates ranked by vector similarity

### Python API Surface

```python
import memvid_sdk

mem = memvid_sdk.Memvid("knowledge.mv2")
mem.put("document text", title="Doc", uri="mv2://docs/1")
mem.commit()
results = mem.search("query", top_k=10)
```

## Gap Analysis: Memvid vs EntropicMem

| # | Feature | Memvid | EntropicMem | Gap | Priority |
|---|---------|--------|-------------|-----|----------|
| G1 | **Semantic/vector search** | HNSW + ONNX embeddings (384-dim BGE-small), cosine similarity | FTS5 keyword only | YES | HIGH |
| G2 | **Hybrid search** | BM25 + vector fusion ranking | FTS5 only | YES | HIGH |
| G3 | **Temporal queries** | NL date parsing ("last Tuesday"), time index | `created_at` column, no NL parsing | YES | MEDIUM |
| G4 | **PII detection** | Built-in PII scanner/redaction | None | YES | MEDIUM |
| G5 | **Graph/relational query** | Entity patterns, triple extraction, graph-filtered search | Vault wikilinks exist but not queryable | YES | MEDIUM |
| G6 | **Time-travel / replay** | Rewind, replay, branch memory states | No temporal state queries | YES | LOW |
| G7 | **Append-only immutability** | Smart Frames immutable with SHA-256 | Facts are mutable (reinforce, patch_core) | Partial | LOW |
| G8 | **Single-file capsule** | Self-contained `.mv2` with rules + expiry | SQLite DB + vault directory | Partial | LOW |
| G9 | **Compression** | Zstd / LZ4 per-frame | SQLite WAL (implicit) | Minimal | LOW |
| G10 | **Encryption at rest** | Password-based encrypted capsules (.mv2e) | None | YES | LOW |
| G11 | **Multi-modal ingestion** | PDF, CLIP images, Whisper audio | Text only | SKIP | N/A |
| G12 | **Predictive caching** | Sub-5ms with predictive cache | SQLite ~1ms directly | SKIP | N/A |

## What We're NOT Adopting (and Why)

| Memvid Feature | Why Skip |
|---------------|----------|
| Multi-modal (CLIP, Whisper, PDF) | EntropicMem is a text memory system for an AI agent. Multi-modal ingestion is out of scope. |
| Predictive caching | SQLite recall is already ~1ms. Predictive caching adds complexity for negligible gain. |
| Rust rewrite | EntropicMem's stdlib-Python approach is a feature, not a limitation. Hermes integration requires Python. |
| `.mv2` binary format | SQLite is already a single-file, portable, battle-tested format. No need for a custom binary. |
| Serverless architecture | EntropicMem is already serverless (embedded SQLite). No gap here. |

---

*For the implementation plan and acceptance criteria, see `MASTER_TODO.md` → "## Memvid Integration Plan (Phase 7–11)".*
