# EntropicMem v1.0 — Release Checklist

Mirror of `PROJECT_PLAN.md` §10. All items must be ✅ before tagging `v1.0.0`.

---

## 10.1 Repository (Public GitHub)

- [ ] `README.md` — one-line description, `/learn` install command, architecture diagram, quickstart, license
- [ ] `LICENSE` — MIT
- [ ] `PROJECT_PLAN.md` — this document (all 10 sections)
- [ ] `RISKS.md` — risk register with owners
- [ ] `RELEASE-CHECKLIST.md` — this file
- [ ] `.github/workflows/test.yml` — passing (lint + unit tests)
- [ ] Tagged release `v1.0.0` with changelog

---

## 10.2 Skill Package (`skills/entropicmem/`)

- [ ] `SKILL.md` — description ≤60 chars, triggers, workflows, tool framing (Hermes tools only)
- [ ] `SETUP.md` — first-run checklist (vault resolution, env vars, init, smoke test)
- [ ] `references/` — 5 docs: MEMORY_MODEL, VAULT_SCHEMA, HERMES_INTEGRATION, CLI_REFERENCE, VISUALIZER
- [ ] `templates/vault/` — complete seed skeleton (AGENTS.md, SCHEMA.md, index.md, log.md, templates/, domains/)
- [ ] Progressive disclosure: SKILL.md <100 lines, detail in references

---

## 10.3 CLI (`skills/entropicmem/scripts/entropicmem.py`)

| Subcommand | Required | Test Criteria |
|------------|----------|---------------|
| `init [--vault PATH] [--force] [--dry-run]` | ✅ | Creates valid vault, writes env vars |
| `ingest <source> [--domain DOMAIN]` | ✅ | URL/file/stdin → lit + 8-15 permanents |
| `ingest-pile <dir> [--domain DOMAIN]` | ✅ | Parallel + cross-ref |
| `query "<q>" [--top-k N] [--semantic]` | ✅ | Returns cited snippets |
| `note [title] [--domain DOMAIN]` | ✅ | Stdin → permanent note |
| `research "<q>" [--rounds N]` | ✅ | Research brief in inbox |
| `lint [--domain DOMAIN]` | ✅ | Orphans, dead links, stale (>90d), contradictions |
| `moc [--domain DOMAIN]` | ✅ | Builds Index.md + backlinks |
| `hotcache` | ✅ | Rebuilds Wiki-Cache.md |
| `graph export [--format json\|dot\|html\|canvas] [--max-nodes N] [--domain D] [--min-imp F]` | ✅ | Viewable graph.html |
| `graph serve [--port N]` | ✅ | Serves export dir |
| `remember "fact" [--domain D] [--tags t1,t2]` | ✅ | Vault note + Mnemosyne row (same entropic_id) |
| `forget <entropic_id>` | ✅ | Deletes both sides |
| `open <note_id>` | ✅ | Opens note in $EDITOR / VS Code |
| `bridge export [--since DATETIME]` | ✅ | Mnemosyne → Vault Mnemosyne/ |
| `bridge import [--folder Mnemosyne]` | ⏳ v1.1 | Vault → Mnemosyne |
| `--check-deps` | ✅ | Prints optional dep status |
| `--version` | ✅ | Prints version |

---

## 10.4 Core Library Modules

- [ ] `vault.py` — all ops tested (path resolution, write, read, linkify, sanitize, search)
- [ ] `index.py` — FTS5 schema, rebuild, upsert, delete, search, backlinks, graph edges
- [ ] `graph_export.py` — JSON, DOT, HTML (galaxy), Canvas
- [ ] `mnemosyne_bridge.py` — export, import, remember, dedup via content hash
- [ ] `retrieval.py` — composed stack with optional semantic
- [ ] `templates.py` — string.Template rendering for all note types

---

## 10.5 Visual Graph (`graph.html`)

- [ ] Single file, works via `file://` and `http://localhost:8080/`
- [ ] D3 v7 (CDN) + local fallback copy
- [ ] Galaxy theme: dark bg, per-domain palette, node glow, edge weight = thickness
- [ ] Physics tuned for web/galaxy (not hairball)
- [ ] Hover tooltip, click → `entropicmem://open/<id>` (protocol handler documented)
- [ ] Filter panel: domain, tags, importance slider
- [ ] Legend: domain colors + node type shapes
- [ ] Fixed seed for reproducibility

---

## 10.6 Tests (pytest)

| Test Module | Coverage Target |
|-------------|-----------------|
| `test_vault.py` | write/read/linkify/sanitize/search, path-with-spaces |
| `test_index.py` | rebuild, upsert, delete, FTS search, backlinks, graph edges |
| `test_retrieval.py` | composed stack returns correct citations for 10 fixture queries |
| `test_graph.py` | JSON/DOT/HTML/Canvas export valid; node/edge counts match |
| `test_bridge.py` | Round-trip remember → vault + Mnemosyne same entropic_id; dedup works |

---

## 10.7 `/learn` Dry-Run (Acceptance Test)

On a **fresh Hermes profile** (no EntropicMem):

```bash
/learn https://github.com/Ufonik88/EntropicMem
```

**Expected agent behavior:**
1. Fetches repo, reads SKILL.md + SETUP.md
2. `skill_manage create name=entropicmem category=memory`
3. Runs: `python3 ~/.hermes/skills/entropicmem/scripts/entropicmem.py init`
4. Runs: `entropicmem lint && entropicmem hotcache && entropicmem graph export --format html`
5. Opens graph.html (or reports path)
6. Reports: "EntropicMem installed. Vault: ~/Documents/Obsidian Vault. Commands: entropicmem ingest|query|graph..."

**Pass Criteria:** All steps complete without manual intervention; vault is valid; graph renders; no errors in Hermes logs.

---

## 10.8 Coexistence Guarantees

- [ ] Never writes to `Mnemosyne/`, `.obsidian/`, `_archive/` (guarded in `vault.py`)
- [ ] Respects existing `AGENTS.md`, `SCHEMA.md`, `index.md`, `log.md` (backs up on `--force`)
- [ ] Works with Syncthing (plain Markdown, no DB in vault)
- [ ] Works with git auto-commit (no binary files in vault)
- [ ] `obsidian` and `llm-wiki` skills remain functional

---

## 10.9 Documentation Suite (`docs/`)

- [ ] `ARCHITECTURE.md` — module diagram, data flows, why skill+scripts+MCP
- [ ] `MEMORY_MODEL.md` — 5-layer table, entropic_id round-trip, Mnemosyne bridge
- [ ] `CLI_REFERENCE.md` — every subcommand with examples
- [ ] `VISUALIZER.md` — D3 spec, node/edge schema, color palettes, physics params
- [ ] `SELF_INSTALL.md` — `/learn` walkthrough transcript, troubleshooting
- [ ] `COMPARISON.md` — vs obsidian skill, llm-wiki skill, Mnemosyne, OpenViking, Mem0, Tencent lineage
- [ ] `COMPARISON_TABLE.md` — machine-readable CSV for automated checks

---

## Phase Gates (from §7)

| Phase | Gate |
|-------|------|
| 1 | `pytest tests/test_vault.py` + `entropicmem lint` on 100-note test vault = 0 errors |
| 2 | `entropicmem query` on seeded vault returns correct citations for 10/10 test queries |
| 3 | `graph.html` opens in browser, shows >50 nodes, click opens note in editor (via protocol) |
| 4 | Round-trip `remember` → vault note + Mnemosyne row with same `entropic_id`; re-run = no dup |
| 5 | Clean `/learn` install on fresh Hermes profile; skill loads, `init` works, graph renders |

---

**Sign-off:** All ✅ → tag `v1.0.0` → GitHub release → announce in Nous Discord `#plugins-skills-and-skins`
