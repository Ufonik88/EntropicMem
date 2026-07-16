from pathlib import Path
import re
import datetime
import py_compile

p = Path("/home/ufonik/Documents/Coding Projects/EntropicMem/skills/entropicmem/scripts/entropicmem.py")

# Restore from git if corrupted
import subprocess
subprocess.run(["git", "-C", str(p.parent.parent.parent.parent), "checkout", "HEAD", "--", str(p)], check=True)

text = p.read_text(encoding="utf-8")
text = text.replace('__version__ = "0.1.0"', '__version__ = "1.0.0"')

# docstring usage block only
old_usage = """  entropicmem open <note_id>
  entropicmem memory project|stats
  entropicmem --check-deps"""
new_usage = """  entropicmem open <note_id>
  entropicmem recall \"<q>\"
  entropicmem memory project|stats|list
  entropicmem --check-deps"""
text = text.replace(old_usage, new_usage)

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


def _append_env(env_file: Path, vault_path: Path, index_path: Path, memory_path: Path) -> None:''',
    )
    text = text.replace(
        'ENTROPICMEM_INDEX_DB="{index_path}"\n"""',
        'ENTROPICMEM_INDEX_DB="{index_path}"\nENTROPICMEM_MEMORY_DB="{memory_path}"\n"""',
    )
    text = text.replace(
        "    _append_env(env_file, vault_path, index_path)",
        '    memory_path = Path.home() / ".hermes" / "entropicmem" / "memory.db"\n    _append_env(env_file, vault_path, index_path, memory_path)',
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

if 'memory_command == "list"' not in text:
    text = text.replace(
        '''    elif args.memory_command == "stats":
        s = engine.stats()
        print(f"Memory DB: {s['db_path']}")
        print(f"Facts: {s['fact_count']}")
        print(f"Domains: {s['domains']}")
        engine.close()
        return 0
    else:
        print("Usage: entropicmem memory project|stats", file=sys.stderr)''',
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
    else:
        print("Usage: entropicmem memory project|stats|list", file=sys.stderr)''',
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

p.write_text(text, encoding="utf-8")
py_compile.compile(str(p), doraise=True)
print("entropicmem patched OK")