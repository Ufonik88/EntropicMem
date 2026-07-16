#!/usr/bin/env python3
"""One-shot Phase 5 patches for EntropicMem."""
from __future__ import annotations

import datetime
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/entropicmem/scripts/entropicmem.py"


def patch_entropicmem() -> None:
    text = SCRIPTS.read_text(encoding="utf-8")
    text = text.replace('__version__ = "0.1.0"', '__version__ = "1.0.0"')
    text = text.replace(
        "entropicmem memory project|stats",
        'entropicmem recall "<q>"\n  entropicmem memory project|stats|list',
    )
    text = text.replace(
        'for d in ["inbox", ".raw", "Mnemosyne", "templates", "attachments"]:',
        'for d in ["inbox", ".raw", "templates", "attachments"]:',
    )

    today = datetime.date.today().isoformat()
    ver = "1.0.0"
    new_seed = f'''_SEED_FILES = {{
    "AGENTS.md": """# AGENTS.md — EntropicMem Vault Boot File

> Boot instructions for any Hermes/agent session reading this vault.

## What This Vault Is
A durable, linked Markdown knowledge base managed by **EntropicMem** — the agent's standalone memory system.

## Storage layout
- `AGENTS.md` — this file
- `SCHEMA.md` — conventions and frontmatter
- `index.md` — sectioned catalog
- `log.md` — append-only action log
- `Wiki-Cache.md` — hot orientation (regenerate with `hotcache`)
- `inbox/` — fleeting captures
- `.raw/` — raw clipper landing
- `templates/` — note templates
- `_archive/` — write-protected archive
- `<Domain>/` — structured knowledge by domain

## Agent loop (CLI)
| Command | Purpose |
|---------|---------|
| `ingest <source>` | Literature + atomic notes |
| `query "q"` | Cited vault retrieval |
| `recall "q"` | Search memory engine facts |
| `remember "fact"` | Durable fact → memory engine + vault |
| `note [title]` | Stdin → permanent note |
| `lint` | Orphans, dead links, stale |
| `moc` | Domain Index + backlinks |
| `hotcache` | Refresh Wiki-Cache.md |
| `graph export` | Galaxy knowledge graph |

## Rules
- Use `[[wikilinks]]` liberally (case-sensitive on Linux)
- Promote `inbox/` → domain folders during maintenance
- Never write to `_archive/` (protected)
- Do not store credentials in the vault
""",
    "SCHEMA.md": """# Vault Schema — EntropicMem

## Conventions
- One idea per permanent note when possible
- Minimum two outbound wikilinks on permanent notes
- Filenames: lowercase, hyphens

## Frontmatter (required)
```yaml
title: "Note Title"
type: literature|permanent|moc|index|log
tags: [tag1, tag2]
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"
source: agent|url|file|conversation
entropic_id: "16-hex-id"
domain: "Knowledge"
agent: true
```
""",
    "index.md": """# Index — Vault Content Catalog

## Knowledge
<!-- MOC: Knowledge/Index -->

## Infrastructure
<!-- MOC: Infrastructure/Index -->

## Projects
<!-- MOC: Projects/Index -->

## People
<!-- MOC: People/Index -->

## Workflows
<!-- MOC: Workflows/Index -->

## Finance
<!-- MOC: Finance/Index -->
""",
    "log.md": f"""# Action Log

## Created
- Vault initialized by EntropicMem v{ver}
- Date: {today}

---
*Append-only log.*
""",
    "Wiki-Cache.md": f"""# Wiki-Cache

> Hot orientation: recent + high-value links. Regenerate: `entropicmem hotcache`
> Generated: {today}

*Vault is fresh — run `entropicmem ingest` or `remember` to populate.*
""",
}}

'''
    text = re.sub(
        r"_SEED_FILES = \{.*?\n\}\n\n\n# ── subcommand: init",
        new_seed + "\n\n\n# ── subcommand: init",
        text,
        flags=re.DOTALL,
    )

    if "def _memory_db_path" not in text:
        text = text.replace(
            'def _append_env(env_file: Path, vault_path: Path, index_path: Path) -> None:',
            '''def _memory_db_path() -> Path:
    return Path(os.environ.get(
        "ENTROPICMEM_MEMORY_DB",
        str(Path.home() / ".hermes" / "entropicmem" / "memory.db"),
    )).expanduser().resolve()


def _append_env(env_file: Path, vault_path: Path, index_path: Path) -> None:''',
        )
        text = text.replace(
            'ENTROPICMEM_INDEX_DB="{index_path}"\n"""',
            'ENTROPICMEM_INDEX_DB="{index_path}"\nENTROPICMEM_MEMORY_DB="{memory_path}"\n"""',
        )
        text = text.replace(
            "    _append_env(env_file, vault_path, index_path)",
            "    memory_path = Path.home() / \".hermes\" / \"entropicmem\" / \"memory.db\"\n    _append_env(env_file, vault_path, index_path, memory_path)",
        )
        text = text.replace(
            "def _append_env(env_file: Path, vault_path: Path, index_path: Path) -> None:",
            "def _append_env(env_file: Path, vault_path: Path, index_path: Path, memory_path: Path) -> None:",
        )

    recall_fn = '''
# ── subcommand: recall ───────────────────────────────────────────────────

def cmd_recall(args) -> int:
    engine = MemoryEngine(_memory_db_path())
    results = engine.recall(args.query, top_k=args.top_k, domain=args.domain)
    if not results:
        print("No matching facts.")
        engine.close()
        return 0
    for r in results:
        preview = r.content.replace("\\n", " ")
        print(f"[{r.id}] ({r.domain}) imp={r.importance:.2f} {preview}")
    engine.close()
    return 0


'''
    if "def cmd_recall" not in text:
        text = text.replace("# ── subcommand: remember", recall_fn + "# ── subcommand: remember")

    old_remember = '''def cmd_remember(args) -> int:
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    domain = args.domain or "Knowledge"
    tags = args.tags.split(",") if args.tags else ["durable", "agent"]
    title = f"Fact - {args.fact[:60]}"
    body = (f"## Fact\\n{args.fact}\\n\\n## Source\\n- Agent (EntropicMem remember)\\n\\n## Links\\n- [[{domain}/Index]]\\n- [[Wiki-Cache]]\\n")
    path = vault.write_note(domain, title, body, tags=tags, domain=domain)
    index = VaultIndex(index_path)
    note = vault.read_note(path)
    index.upsert_note(note)
    index.upsert_edges_for_note(vault, note)
    index.close()
    print(f"Remembered: {note.entropic_id}")
    print(f"Vault note: {path}")
    return 0'''

    new_remember = '''def cmd_remember(args) -> int:
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    domain = args.domain or "Knowledge"
    tags = args.tags.split(",") if args.tags else ["durable", "agent"]
    title = f"Fact - {args.fact[:60]}"
    body = (f"## Fact\\n{args.fact}\\n\\n## Source\\n- Agent (EntropicMem remember)\\n\\n## Links\\n- [[{domain}/Index]]\\n- [[Wiki-Cache]]\\n")
    engine = MemoryEngine(_memory_db_path())
    eid = engine.remember(content=args.fact, title=title, domain=domain, tags=tags, source="agent")
    path = vault.write_note(domain, title, body, tags=tags, domain=domain, frontmatter={"entropic_id": eid})
    index = VaultIndex(index_path)
    note = vault.read_note(path)
    index.upsert_note(note)
    index.upsert_edges_for_note(vault, note)
    index.close()
    engine.close()
    print(f"Remembered: {eid}")
    print(f"Vault note: {path}")
    return 0'''
    text = text.replace(old_remember, new_remember)

    old_forget = '''def cmd_forget(args) -> int:
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    index = VaultIndex(index_path)
    eid = args.entropic_id
    found = None
    for rel in vault.list_notes():
        note = vault.read_note(rel)
        if note.entropic_id == eid or note.note_id == eid:
            found = rel
            break
    if not found:
        print(f"Error: no note found with id: {eid}", file=sys.stderr)
        index.close()
        return 1
    index.delete_note(str(found))
    vault.delete_note(found)
    index.close()
    print(f"Forgot: {found}")
    return 0'''
    new_forget = '''def cmd_forget(args) -> int:
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    index = VaultIndex(index_path)
    engine = MemoryEngine(_memory_db_path())
    eid = args.entropic_id
    engine.forget(eid)
    found = None
    for rel in vault.list_notes():
        note = vault.read_note(rel)
        if note.entropic_id == eid or note.note_id == eid:
            found = rel
            break
    if found:
        index.delete_note(str(found))
        vault.delete_note(found)
        print(f"Forgot vault note: {found}")
    else:
        print(f"No vault note for id {eid} (memory engine updated if present)")
    index.close()
    engine.close()
    return 0'''
    text = text.replace(old_forget, new_forget)

    text = text.replace(
        'print("Usage: entropicmem memory project|stats", file=sys.stderr)',
        'print("Usage: entropicmem memory project|stats|list", file=sys.stderr)',
    )
    if 'memory_command == "list"' not in text:
        text = text.replace(
            '''    elif args.memory_command == "stats":
        s = engine.stats()
        print(f"Memory DB: {s['db_path']}")
        print(f"Facts: {s['fact_count']}")
        print(f"Domains: {s['domains']}")
        engine.close()
        return 0
    else:''',
            '''    elif args.memory_command == "stats":
        s = engine.stats()
        print(f"Memory DB: {s['db_path']}")
        print(f"Facts: {s['fact_count']}")
        print(f"Domains: {s['domains']}")
        engine.close()
        return 0
    elif args.memory_command == "list":
        domain = getattr(args, "domain", None)
        limit = getattr(args, "limit", 50)
        facts = engine.list_facts(domain=domain, limit=limit)
        for f in facts:
            preview = f.content.replace("\\n", " ")[:120]
            print(f"{f.id}\\t{f.domain}\\t{preview}")
        engine.close()
        return 0
    else:''',
        )

    if 'p_recall = sub.add_parser("recall"' not in text:
        text = text.replace(
            '    # remember\n    p_remember = sub.add_parser("remember"',
            '''    # recall
    p_recall = sub.add_parser("recall", help="Search durable facts in memory engine")
    p_recall.add_argument("query", help="Search query")
    p_recall.add_argument("--top-k", type=int, default=10)
    p_recall.add_argument("--domain", help="Filter by domain")

    # remember
    p_remember = sub.add_parser("remember"''',
        )
    text = text.replace(
        '    m_sub.add_parser("stats", help="Show memory engine statistics")',
        '''    m_sub.add_parser("stats", help="Show memory engine statistics")
    m_list = m_sub.add_parser("list", help="List facts in memory engine")
    m_list.add_argument("--domain", help="Filter by domain")
    m_list.add_argument("--limit", type=int, default=50)''',
    )
    text = text.replace(
        '        "remember": cmd_remember,',
        '        "recall": cmd_recall,\n        "remember": cmd_remember,',
    )

    SCRIPTS.write_text(text, encoding="utf-8")
    import py_compile
    py_compile.compile(str(SCRIPTS), doraise=True)
    print("patched entropicmem.py")


def write_docs() -> None:
    refs = ROOT / "skills/entropicmem/references"
    docs = ROOT / "docs"
    refs.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)

    (refs / "MEMORY_MODEL.md").write_text("""# Memory Model

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
""", encoding="utf-8")

    (refs / "VAULT_SCHEMA.md").write_text("""# Vault Schema

## Layout
```
vault/
├── AGENTS.md, SCHEMA.md, index.md, log.md, Wiki-Cache.md
├── inbox/, .raw/, templates/, attachments/, _archive/
└── <Domain>/*.md
```

## Note types
`literature`, `permanent`, `moc`, `index`, `log`

## Frontmatter
See seed `SCHEMA.md` in vault. Required: `title`, `type`, `tags`, `created`, `source`, `domain`, `entropic_id` (when from `remember`).

## Wikilinks
`[[Note Title]]` or `[[Domain/Note Title]]` — case-sensitive on Linux.
""", encoding="utf-8")

    (refs / "CLI_REFERENCE.md").write_text("""# CLI Reference

All commands: `python3 ~/.hermes/skills/entropicmem/scripts/entropicmem.py <cmd>`

| Command | Description |
|---------|-------------|
| `init` | Bootstrap vault, index, env vars |
| `ingest <source>` | URL/file/stdin → notes |
| `ingest-pile <dir>` | Batch ingest |
| `query "<q>"` | Vault search with citations |
| `recall "<q>"` | Memory engine fact search |
| `remember "fact"` | Fact → memory.db + vault |
| `forget <id>` | Remove from memory + vault note |
| `memory stats` | Engine statistics |
| `memory list` | List facts (`--domain`, `--limit`) |
| `memory project` | Materialize facts into vault |
| `note [title]` | Stdin → permanent note |
| `research "<q>"` | Research brief in inbox |
| `lint` | Vault health |
| `moc` | Domain indexes |
| `hotcache` | Rebuild Wiki-Cache |
| `graph export` | json/dot/html/canvas |
| `graph serve` | HTTP serve export dir |
| `open <id>` | Open note in editor |

Env: `ENTROPICMEM_VAULT_PATH`, `ENTROPICMEM_INDEX_DB`, `ENTROPICMEM_MEMORY_DB`
""", encoding="utf-8")

    (refs / "VISUALIZER.md").write_text("""# Visualizer

`entropicmem graph export --format html --output-dir ./export`

- Single self-contained `graph.html` (D3 v7, dark theme)
- Nodes = vault notes; edges = wikilinks
- Filters: `--domain`, `--max-nodes`, `--min-importance`
- Serve: `entropicmem graph serve --port 8080 --dir ./export`
""", encoding="utf-8")

    (refs / "HERMES_INTEGRATION.md").write_text("""# Hermes Integration

## Install
```
/learn https://github.com/Ufonik88/EntropicMem
```

## Agent workflow
1. `skill_view(name='entropicmem')`
2. Follow `SETUP.md`: `entropicmem init`
3. Use `terminal` to run CLI commands

## Write path
Promote durable conclusions with `remember`. Capture sources with `ingest`. Do not store secrets.

## Read path
`query` for linked knowledge; `recall` for stored facts; `hotcache` for orientation.

## Maintenance
End heavy knowledge sessions with `lint` and optional `hotcache`.
""", encoding="utf-8")

    for name, body in {
        "ARCHITECTURE.md": (refs / "MEMORY_MODEL.md").read_text() + "\n\nSee `skills/entropicmem/scripts/` modules: vault, index, retrieval, memory_engine, graph_export, entropicmem.\n",
        "MEMORY_MODEL.md": (refs / "MEMORY_MODEL.md").read_text(),
        "CLI_REFERENCE.md": (refs / "CLI_REFERENCE.md").read_text(),
        "VISUALIZER.md": (refs / "VISUALIZER.md").read_text(),
        "SELF_INSTALL.md": """# Self-Install (`/learn`)

1. User: `/learn https://github.com/Ufonik88/EntropicMem`
2. Agent loads skill `entropicmem` and `SETUP.md`
3. Run `entropicmem init` (creates `~/.hermes/entropicmem/`)
4. Smoke: `lint`, `remember "install smoke test"`, `recall install`, `graph export --format html`

Dry-run acceptance recorded when steps 3–4 succeed on a clean temp vault.
""",
        "COMPARISON.md": """# Capability Comparison (generic classes)

| Capability class | Typical approach | EntropicMem |
|------------------|----------------|-------------|
| Session-only context | Rely on chat history | `remember` + `recall` persist facts |
| Markdown wiki | Manual notes + plugins | Vault + `ingest`/`moc`/`lint` |
| Vector memory SaaS | Hosted API | Optional local semantic re-rank; core FTS stdlib |
| Agent skills | Ad-hoc scripts | Unified CLI + skill + tests |

EntropicMem is designed to cover durable memory, linked archive, retrieval, maintenance, and visualization in one installable package.
""",
        "COMPARISON_TABLE.md": """| Feature | EntropicMem |
|---------|-------------|
| Durable fact store | memory.db + remember/recall |
| Linked notes | Markdown vault + wikilinks |
| Full-text search | index.db + query |
| Graph view | graph.html export |
| Hermes install | /learn + skill |
| Offline core | stdlib Python |
""",
    }.items():
        (docs / name).write_text(body, encoding="utf-8")

    skill = ROOT / "skills/entropicmem/SKILL.md"
    skill.write_text("""---
name: entropicmem
description: Standalone knowledge engine: vault, memory, graph.
version: 1.0.0
author: Hermes
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Memory, Knowledge, Vault, Graph]
    category: memory
---

# EntropicMem — Standalone Agent Memory

Complete memory system for Hermes: **memory engine** (facts), **vault** (linked notes), **index** (search), **graph** (visual map).

## Install
`/learn https://github.com/Ufonik88/EntropicMem` then follow `SETUP.md` and run `entropicmem init`.

## Operating contract

### When to WRITE
| Situation | Command |
|-----------|---------|
| Durable fact, preference, identity, stable lesson | `remember "..."` |
| URL/file/source capture | `ingest` / `ingest-pile` |
| Structured note from stdin | `note` |
| Research to pursue | `research` (then agent uses web tools) |
| Ephemeral reasoning | **Do not** persist |
| Credentials | **Never** store |

### When to READ
| Need | Command |
|------|---------|
| Linked conceptual context | `query "..."` |
| Stored facts | `recall "..."` or `memory list` |
| Session orientation | read `Wiki-Cache.md` or `hotcache` |
| Relationships | `graph export --format html` |

### Session pattern
1. Orient (`hotcache` if stale)
2. Retrieve before long-horizon answers (`query` / `recall`)
3. Capture outcomes (`remember` / `ingest` / `note`)
4. Maintain after heavy work (`lint`, `moc`)

### Promotion from chat
When the user states a preference, correction, or fact that will matter later → `remember` immediately (do not rely on chat memory alone).

## Commands
See `references/CLI_REFERENCE.md`.

## References
- `SETUP.md`, `references/MEMORY_MODEL.md`, `references/VAULT_SCHEMA.md`, `references/HERMES_INTEGRATION.md`
""", encoding="utf-8")

    (ROOT / "CHANGELOG.md").write_text("""# Changelog

## [1.0.0] - 2026-07-16

### Added
- Standalone MemoryEngine (`memory.db`)
- CLI: `recall`, `memory list`
- Full reference and product documentation
- Phase 5 ship gate: standalone product framing

### Changed
- `remember`/`forget` dual memory engine + vault
- Seed vault AGENTS/SCHEMA (EntropicMem-only)
- Version 1.0.0

### Includes from prior releases
- Vault engine, ingest loop, graph visualizer, 80+ tests
""", encoding="utf-8")

    ci = ROOT / ".github/workflows/test.yml"
    ci.write_text("""name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -q pytest
      - run: pytest -q tests/
""", encoding="utf-8")
    print("docs written")


if __name__ == "__main__":
    patch_entropicmem()
    write_docs()