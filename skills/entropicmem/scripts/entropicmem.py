#!/usr/bin/env python3
"""
entropicmem.py — Main CLI for EntropicMem, the Hermes Agent second brain.

Usage:
  entropicmem init [--vault PATH] [--force] [--dry-run]
  entropicmem ingest <source> [--domain DOMAIN]
  entropicmem ingest-pile <dir> [--domain DOMAIN]
  entropicmem query "<q>" [--top-k N] [--semantic] [--domain DOMAIN]
  entropicmem note [title] [--domain DOMAIN]
  entropicmem research "<q>" [--rounds N]
  entropicmem lint [--domain DOMAIN]
  entropicmem moc [--domain DOMAIN]
  entropicmem hotcache
  entropicmem graph export [--format FORMAT] [--max-nodes N] [--domain D]
  entropicmem graph serve [--port N]
  entropicmem remember "fact" [--domain D] [--tags t1,t2]
  entropicmem forget <entropic_id>
  entropicmem open <note_id>
  entropicmem recall "<q>"
  entropicmem memory project|stats|list
  entropicmem --check-deps
  entropicmem --version

Standalone memory: vault + MemoryEngine + graph.
"""

import argparse
import os
import hashlib
import re
import shutil
import sys
from datetime import date
from pathlib import Path

# ── path setup (support both repo-root and ~/.hermes/skills/entropicmem/scripts/) ──
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from vault import (
    DEFAULT_DOMAINS,
    Note,
    Vault,
    resolve_vault_path,
)
from index import VaultIndex
from retrieval import EMBEDDER_AVAILABLE, retrieve_composed
from graph_export import export_json, export_dot, export_html, export_canvas
from memory_engine import MemoryEngine

__version__ = "1.0.0"

# ── input validation helpers ────────────────────────────────────────────────

def validate_domain(domain: str) -> str:
    """Validate and sanitize domain name."""
    if not domain:
        return "Knowledge"
    # Only allow alphanumeric, hyphens, spaces
    import re
    safe = re.sub(r'[^a-zA-Z0-9\s-]', '', domain).strip()
    return safe or "Knowledge"

def validate_query(query: str, max_len: int = 500) -> str:
    """Validate and truncate query string."""
    if not query:
        return ""
    # Remove any potential injection chars, just keep reasonable text
    safe = query.strip()[:max_len]
    return safe

def validate_entropic_id(eid: str) -> str:
    """Validate entropic_id format (16-char hex)."""
    if not eid:
        return ""
    import re
    if re.fullmatch(r'[a-f0-9]{16}', eid.lower()):
        return eid.lower()
    raise ValueError(f"Invalid entropic_id format: {eid}")

def validate_path(path: str, max_len: int = 4096) -> str:
    """Validate file/path input."""
    if not path:
        return ""
    # Basic sanitization - prevent directory traversal
    safe = path.strip()[:max_len]
    if '..' in safe or safe.startswith('/'):
        raise ValueError(f"Invalid path: {path}")
    return safe

def validate_url(url: str) -> str:
    """Validate URL scheme and block internal addresses."""
    if not url:
        return ""
    import urllib.parse
    import ipaddress
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError("Only http/https URLs allowed")
    hostname = parsed.hostname or ""
    # Block private IPs and localhost
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("Private/internal IP addresses not allowed")
    except ValueError as e:
        if "not allowed" in str(e):
            raise
        # Not an IP, check hostname
        if hostname.lower() in ('localhost', 'localhost.localdomain', 'metadata', 'metadata.google.internal', '169.254.169.254'):
            raise ValueError("Internal hostname not allowed")
    return url.strip()

# ── env resolution ──────────────────────────────────────────────────────────

def _resolve_env() -> tuple[Path, Path]:
    """Resolve vault path and index DB path from env vars or defaults."""
    vault_path = resolve_vault_path()
    index_db = Path(
        os.environ.get("ENTROPICMEM_INDEX_DB",
                        str(Path.home() / ".hermes" / "entropicmem" / "index.db"))
    )
    return vault_path, index_db


# ── seed templates ──────────────────────────────────────────────────────────

_SEED_FILES = {
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
- Vault initialized by EntropicMem v1.0.0
- Date: 2026-07-16

---
*Append-only log.*
""",
    "Wiki-Cache.md": f"""# Wiki-Cache

> Hot orientation: recent + high-value links. Regenerate: `entropicmem hotcache`
> Generated: 2026-07-16

*Vault is fresh — run `entropicmem ingest` or `remember` to populate.*
""",
}




# ── subcommand: init ────────────────────────────────────────────────────────

def cmd_init(args) -> int:
    """Bootstrap a new vault (or bind to existing in safe mode)."""
    vault_path = Path(args.vault).expanduser().resolve() if args.vault else _resolve_env()[0]
    index_path = Path(args.index_db).expanduser().resolve() if args.index_db else _resolve_env()[1]

    if args.dry_run:
        print(f"[dry-run] Would create vault at: {vault_path}")
        print(f"[dry-run] Would create index at: {index_path}")
        return 0

    vault_path.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    safe_mode = (vault_path / "AGENTS.md").exists()

    created = []
    skipped = []

    for filename, content in _SEED_FILES.items():
        dest = vault_path / filename
        if dest.exists() and not args.force:
            skipped.append(filename)
            continue
        if dest.exists():
            backup = dest.with_suffix(dest.suffix + ".bak")
            shutil.copy2(dest, backup)
            print(f"  Backed up: {filename} → {backup.name}")
        dest.write_text(content, encoding="utf-8")
        created.append(filename)

    # Create directories
    for d in ["inbox", ".raw", "templates", "attachments"]:
        (vault_path / d).mkdir(exist_ok=True)
        (vault_path / d / ".gitkeep").touch(exist_ok=True)

    for domain in DEFAULT_DOMAINS:
        (vault_path / domain).mkdir(exist_ok=True)
        (vault_path / domain / ".gitkeep").touch(exist_ok=True)

    # Template files
    tmpl_dir = vault_path / "templates"
    _write_template(tmpl_dir / "permanent.md", "permanent")
    _write_template(tmpl_dir / "literature.md", "literature")
    _write_template(tmpl_dir / "moc.md", "moc")
    _write_template(tmpl_dir / "index.md", "index")

    # Initialize index
    vault = Vault(vault_path)
    index = VaultIndex(index_path)
    index.rebuild(vault)
    index.close()

    # Write env vars
    env_file = Path.home() / ".hermes" / ".env"
    memory_path = Path.home() / ".hermes" / "entropicmem" / "memory.db"
    _append_env(env_file, vault_path, index_path, memory_path)

    print(f"\nEntropicMem initialized.")
    print(f"  Vault:      {vault_path} {'(safe mode — AGENTS.md already existed)' if safe_mode else ''}")
    print(f"  Index DB:   {index_path}")
    print(f"  Created:    {', '.join(created) if created else 'none'}")
    if skipped:
        print(f"  Skipped:    {', '.join(skipped)} (use --force to overwrite)")
    print(f"  Domains:    {', '.join(DEFAULT_DOMAINS)}")
    print(f"\nNext: entropicmem ingest <source>  or  entropicmem query \"topic\"")
    return 0


def _write_template(path: Path, ttype: str) -> None:
    """Write a default template file."""
    templates = {
        "permanent": """# {{ title }}

## Context
{{ context }}

## Source
- {{ source_link }}

## Links
- [[{{ domain }}/Index]]
""",
        "literature": """# Lit - {{ title }}

**Source:** {{ source_url }}

## Key Points
{% for point in key_points %}
- {{ point }}
{% endfor %}

## Extracted Entities
{% for entity in entities %}
- [[{{ entity }}]]
{% endfor %}

## Links
- [[Wiki-Cache]]
""",
        "moc": """# {{ domain }} — Map of Content

> Auto-generated MOC. Index of all notes in this domain.

## Notes
<!-- MOC: list -->
""",
        "index": """# {{ title }}

## Contents
""",
    }
    content = templates.get(ttype, "# {{ title }}\n\nContent placeholder.\n")
    path.write_text(content, encoding="utf-8")


def _memory_db_path() -> Path:
    return Path(os.environ.get(
        "ENTROPICMEM_MEMORY_DB",
        str(Path.home() / ".hermes" / "entropicmem" / "memory.db"),
    )).expanduser().resolve()


def _append_env(env_file: Path, vault_path: Path, index_path: Path, memory_path: Path) -> None:
    """Idempotently append EntropicMem env vars to ~/.hermes/.env."""
    entry = f"""
# EntropicMem — added by entropicmem init
ENTROPICMEM_VAULT_PATH="{vault_path}"
ENTROPICMEM_INDEX_DB="{index_path}"
ENTROPICMEM_MEMORY_DB="{memory_path}"
"""
    if env_file.exists():
        text = env_file.read_text(encoding="utf-8")
        if "ENTROPICMEM_VAULT_PATH" in text:
            return  # already configured
    env_file.parent.mkdir(parents=True, exist_ok=True)
    with open(env_file, "a", encoding="utf-8") as f:
        f.write(entry)


# ── subcommand: lint ────────────────────────────────────────────────────────

def cmd_lint(args) -> int:
    """Check vault health: orphans, dead links, stale notes, contradictions."""
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    index = VaultIndex(index_path)

    issues = []
    notes = vault.list_notes(include_archive=False)
    known_paths = {str(n) for n in notes}
    known_titles = vault.get_all_titles()
    known_ids = set()

    skip_stems = {'AGENTS', 'SCHEMA', 'index', 'log', 'Wiki-Cache'}
    for rel in notes:
        # Skip root seed files, templates, and utility files
        if rel.parent == Path('.') and rel.stem in skip_stems:
            continue
        if str(rel).startswith('templates/'):
            continue
        note = vault.read_note(rel)
        known_ids.add(note.note_id)
        nid = note.note_id
        title = note.title

        # Check for dead wikilinks
        links = vault.extract_wikilinks(note.body)
        for link in links:
            if link not in known_titles and link not in known_ids:
                issues.append(f"[dead-link] {nid}: [[{link}]] not found")

        # Check for empty notes (less than 50 chars body)
        if len(note.body.strip()) < 50 and note.note_type != "index":
            issues.append(f"[stub] {nid}: body < 50 chars")

        # Check for missing domain
        if not note.domain and note.note_type != "index":
            issues.append(f"[no-domain] {nid}: missing domain in frontmatter")

        # Check for stale (>90 days since update)
        if note.updated:
            try:
                updated_date = date.fromisoformat(note.updated)
                if (date.today() - updated_date).days > 90:
                    issues.append(f"[stale] {nid}: last updated {note.updated} (>90d)")
            except ValueError:
                pass

    # Check for contradictions
    for rel in notes:
        text = (vault_path / rel).read_text(encoding="utf-8")
        if "[!contradiction]" in text:
            issues.append(f"[contradiction] {rel}: contains [!contradiction] callout")

    index.close()

    if issues:
        print(f"Lint found {len(issues)} issue(s):")
        for issue in issues:
            print(f"  {issue}")
        return 1

    print(f"Lint: {len(notes)} notes, 0 issues.")
    return 0


# ── subcommand: hotcache ────────────────────────────────────────────────────

def cmd_hotcache(args) -> int:
    """Rebuild Wiki-Cache.md with recent and high-value note links."""
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    index = VaultIndex(index_path)

    # Get recent notes (by created date — approximate via path listing)
    now = date.today()
    recent: list[tuple[str, str, str]] = []  # (domain, title, path)
    longest: list[tuple[str, str, str, int]] = []  # (domain, title, path, char_count)

    for rel in vault.list_notes():
        note = vault.read_note(rel)
        body_len = len(note.body)
        title = note.title
        domain = note.domain or "uncategorized"

        # Recent: if created within 14 days
        if note.created:
            try:
                created_date = date.fromisoformat(note.created)
                if (now - created_date).days <= 14:
                    recent.append((domain, title, str(rel)))
            except ValueError:
                pass

        longest.append((domain, title, str(rel), body_len))

    recent.sort(key=lambda x: x[0])
    longest.sort(key=lambda x: x[3], reverse=True)

    lines = [
        "# Wiki-Cache",
        "",
        f"> Auto-generated hot cache. Recent (14d) + high-value notes.",
        f"> Generated: {now.isoformat()}",
        "",
        "## Recent (14 days)",
        "",
    ]
    if recent:
        for domain, title, path in recent[:30]:
            safe_path = path.replace(" ", "%20")
            lines.append(f"- [[{title}]] ({domain})")
    else:
        lines.append("*No recent notes.*")

    lines += ["", "## Longest Notes", ""]
    for domain, title, path, _ in longest[:20]:
        lines.append(f"- [[{title}]] ({domain})")

    lines += ["", "## Domains", ""]
    for domain in vault.get_domains():
        count = len(vault.list_notes(folder=domain))
        lines.append(f"- [[{domain}/Index]] ({count} notes)")

    lines.append("")
    (vault_path / "Wiki-Cache.md").write_text("\n".join(lines), encoding="utf-8")

    index.close()
    print(f"Wiki-Cache.md rebuilt. {len(recent)} recent, {len(longest[:20])} longest, {len(vault.get_domains())} domains.")
    return 0


# ── subcommand: query ──────────────────────────────────────────────────────

def cmd_query(args) -> int:
    """Search the vault and return cited results."""
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    index = VaultIndex(index_path)

    result = retrieve_composed(
        query=args.query,
        vault=vault,
        index=index,
        top_k=args.top_k,
        domain=args.domain,
        use_semantic=args.semantic,
    )

    print(result.to_text())
    index.close()
    return 0


# ── subcommand: note ────────────────────────────────────────────────────────

def cmd_note(args) -> int:
    """Create a permanent note from stdin."""
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)

    body = sys.stdin.read().strip()
    if not body:
        print("Error: no input on stdin. Pipe content to `entropicmem note`.", file=sys.stderr)
        return 1

    title = args.title or "Untitled Note"
    domain = args.domain or "Knowledge"

    path = vault.write_note(
        folder=domain,
        title=title,
        body=body,
        tags=args.tags.split(",") if args.tags else [],
        domain=domain,
    )

    index = VaultIndex(index_path)
    note = vault.read_note(path)
    index.upsert_note(note)
    index.close()

    print(f"Note created: {path}")
    return 0



# ── subcommand: open ────────────────────────────────────────────────────────

def cmd_open(args) -> int:
    vault_path, _ = _resolve_env()
    vault = Vault(vault_path)
    try:
        vault.open_note(args.note_id)
        print(f"Opened: {args.note_id}")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


# ── subcommand: ingest ──────────────────────────────────────────────────────

def cmd_ingest(args) -> int:
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    index = VaultIndex(index_path)

    source = args.source
    if source == "-" or not source:
        text = sys.stdin.read().strip()
        if not text:
            print("Error: no source specified and no stdin input.", file=sys.stderr)
            return 1
        title = "Stdin Capture"
        source_label = "stdin"
    elif source.startswith("http://") or source.startswith("https://"):
        import urllib.parse
        import urllib.request
        import ipaddress
        
        # Validate URL to prevent SSRF
        try:
            parsed = urllib.parse.urlparse(source)
            if parsed.scheme not in ("http", "https"):
                print(f"Error: only http/https URLs allowed", file=sys.stderr)
                return 1
            # Block private/internal IPs
            hostname = parsed.hostname or ""
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    print(f"Error: private/internal IP addresses not allowed", file=sys.stderr)
                    return 1
            except ValueError:
                # Not an IP address, that's fine - it's a hostname
                # Additional check: block localhost and common internal hostnames
                if hostname.lower() in ("localhost", "localhost.localdomain", "metadata", "metadata.google.internal", "169.254.169.254"):
                    print(f"Error: internal hostname not allowed", file=sys.stderr)
                    return 1
        except Exception as e:
            print(f"Error: invalid URL: {e}", file=sys.stderr)
            return 1
            
        try:
            req = urllib.request.Request(source, headers={"User-Agent": "EntropicMem/0.1"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                # Limit response size to prevent memory exhaustion
                text = resp.read(10 * 1024 * 1024).decode("utf-8", errors="replace")
        except Exception as e:
            print(f"Error fetching URL: {e}", file=sys.stderr)
            return 1
        text = re.sub(r'<script.*?</script>', '', text, flags=re.S | re.I)
        text = re.sub(r'<style.*?</style>', '', text, flags=re.S | re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text).strip()
        title = vault.sanitize(source.split("/")[-1] or "Web Capture")
        source_label = source
    else:
        p = Path(source)
        if not p.exists():
            print(f"Error: file not found: {source}", file=sys.stderr)
            return 1
        text = p.read_text(encoding="utf-8", errors="ignore")
        title = vault.sanitize(p.stem)
        source_label = source

    domain = args.domain or "Knowledge"

    entities = set(re.findall(r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})\b', text))
    stop_words = {"The","This","That","When","Where","What","Which","After","Before","There","Their","These","Those","From","With","About","Every","Daily","Your","They"}
    entities = {e for e in entities if e.split()[0] not in stop_words and len(e) > 3}
    known_titles = set(vault.get_all_titles().keys())
    entities = entities - known_titles

    lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 20]
    key_points = lines[:15]

    lit_body = (
        f"**Source:** {source_label}\n\n"
        f"## Key Points\n"
        + "\n".join(f"- {p[:200]}" for p in key_points)
        + "\n\n## Extracted Entities\n"
        + "\n".join(f"- [[{e}]]" for e in sorted(entities)[:15])
        + "\n\n## Links\n- [[Wiki-Cache]]\n"
    )
    lit_path = vault.write_note(
        "inbox", f"Lit - {title}",
        lit_body,
        tags=["literature", "auto-ingested"],
        source=source_label,
        source_url=source if source_label.startswith("http") else "",
        note_type="literature",
        domain=domain,
    )
    lit_note = vault.read_note(lit_path)
    index.upsert_note(lit_note)
    print(f"  Literature: {lit_path}")

    atomic_count = 0
    all_titles = set(vault.get_all_titles().keys())
    for entity in sorted(entities)[:15]:
        if entity in all_titles:
            continue
        m = re.search(rf'.{{0,80}}{re.escape(entity)}.{{0,120}}', text)
        snippet = m.group(0).strip() if m else f"Concept extracted from {title}."
        body = (
            f"## Context\n{snippet}\n\n"
            f"## Source\n- [[Lit - {title}]]\n\n"
            f"## Links\n- [[{domain}/Index]]\n- [[Wiki-Cache]]\n"
        )
        path = vault.write_note(domain, entity, body, tags=["permanent","auto-ingested"], source=source_label, domain=domain)
        note = vault.read_note(path)
        index.upsert_note(note)
        index.upsert_edges_for_note(vault, note)
        atomic_count += 1
        all_titles.add(entity)

    index.close()
    print(f"Ingested: 1 literature + {atomic_count} atomic notes (domain: {domain})")
    return 0


# ── subcommand: ingest-pile ─────────────────────────────────────────────────

def cmd_ingest_pile(args) -> int:
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    index = VaultIndex(index_path)
    d = Path(args.dir)
    if not d.is_dir():
        print(f"Error: not a directory: {d}", file=sys.stderr)
        return 1
    files = [str(f) for f in d.rglob("*") if f.suffix in (".md", ".txt", ".html", ".json")]
    if not files:
        print(f"No readable files found in {d}")
        return 0

    domain = args.domain or "Knowledge"
    print(f"Ingesting {len(files)} sources from {d}")

    all_titles = []
    for f in files:
        with open(f, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
        p = Path(f)
        title = vault.sanitize(p.stem)
        all_titles.append(title)
        key_points = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 20][:10]
        lit_body = (
            f"**Source:** {f}\n\n"
            f"## Key Points\n"
            + "\n".join(f"- {pt[:200]}" for pt in key_points)
            + "\n\n## Links\n"
            + "\n".join(f"- [[{t}]]" for t in all_titles if t != title)[:10]
            + "\n"
        )
        lit_path = vault.write_note("inbox", f"Lit - {title}", lit_body, tags=["literature","pile-ingested","auto-ingested"], source=str(f), domain=domain, note_type="literature")
        lit_note = vault.read_note(lit_path)
        index.upsert_note(lit_note)
        index.upsert_edges_for_note(vault, lit_note)

    index.close()
    print(f"Done: {len(files)} literature notes with cross-references (domain: {domain})")
    return 0


# ── subcommand: moc ─────────────────────────────────────────────────────────

def cmd_moc(args) -> int:
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    index = VaultIndex(index_path)
    domains = [args.domain] if args.domain else vault.get_domains()
    for domain in domains:
        notes = vault.list_notes(folder=domain)
        domain_dir = vault.root / domain
        domain_dir.mkdir(exist_ok=True)
        lines = [
            "---",
            f'title: "{domain} — Map of Content"',
            'type: "index"',
            f'created: "{date.today().isoformat()}"',
            f'domain: "{domain}"',
            'source: "agent"',
            'agent: true',
            '---',
            '',
            f"# {domain} — Map of Content",
            "",
            f"> Auto-generated MOC.",
            f"> Generated: {date.today().isoformat()}",
            "",
            "## Notes",
            "",

            ]
        for rel in notes:
            note = vault.read_note(rel)
            lines.append(f"- [[{note.title}]] — {note.note_type}")
        (domain_dir / "Index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        for rel in notes:
            text = (vault.root / rel).read_text(encoding="utf-8")
            if "## Links" not in text:
                text += f"\n\n## Links\n- [[{domain}/Index]]\n"
            elif f"[[{domain}/Index]]" not in text:
                text = text.replace("## Links", f"## Links\n- [[{domain}/Index]]")
            (vault.root / rel).write_text(text, encoding="utf-8")
            note = vault.read_note(rel)
            index.upsert_note(note)
            index.upsert_edges_for_note(vault, note)
        print(f"  {domain}: {len(notes)} notes indexed + backlinks added")
    index.close()
    print(f"MOC rebuilt for {len(domains)} domain(s).")
    return 0


# ── subcommand: research ────────────────────────────────────────────────────

def cmd_research(args) -> int:
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    q = args.query
    brief = (
        f"# Research: {q}\n\n"
        f"> Agent-driven research brief (created {date.today().isoformat()}).\n"
        f"> Run web_search for the query below, fetch 2-4 top sources with\n"
        f"> web_extract, synthesize into this note, and link related notes.\n\n"
        f"## Query\n{q}\n\n"
        f"## Sources\n_Add findings here after web_search._\n\n"
        f"## Key Findings\n_Add synthesized findings here._\n\n"
        f"## Links\n- [[Wiki-Cache]]\n"
    )
    path = vault.write_note("inbox", f"Research - {q[:40]}", brief, tags=["literature","research"], note_type="literature", source="agent", domain="Knowledge")
    index = VaultIndex(index_path)
    note = vault.read_note(path)
    index.upsert_note(note)
    index.close()
    print(f"Research brief: {path}")
    print(f"NEXT: agent runs web_search then web_extract, appends findings.")
    return 0


# ── subcommand: graph ─────────────────────────────────────────────────────

def cmd_graph(args) -> int:
    vault_path, index_path = _resolve_env()
    index = VaultIndex(index_path)

    if args.graph_command == "export":
        out_dir = Path(args.output_dir).resolve()
        fmt = args.format
        domain = args.domain or None
        min_imp = args.min_importance
        max_n = args.max_nodes

        if fmt == "json":
            export_json(index, out_dir / "graph.json", domain=domain, min_importance=min_imp, max_nodes=max_n)
            print(f"Exported: {out_dir / 'graph.json'}")
        elif fmt == "dot":
            export_dot(index, out_dir / "graph.dot", domain=domain, min_importance=min_imp, max_nodes=max_n)
            print(f"Exported: {out_dir / 'graph.dot'}")
        elif fmt == "html":
            export_html(index, out_dir / "graph.html", domain=domain, min_importance=min_imp, max_nodes=max_n)
            print(f"Exported: {out_dir / 'graph.html'}")
            print(f"Open with: file://{out_dir / 'graph.html'}")
        elif fmt == "canvas":
            export_canvas(index, out_dir / "graph.canvas", domain=domain, min_importance=min_imp, max_nodes=max_n)
            print(f"Exported: {out_dir / 'graph.canvas'}")
    elif args.graph_command == "serve":
        out_dir = Path(args.dir).resolve()
        if not (out_dir / "graph.html").exists():
            print(f"Error: graph.html not found in {out_dir}. Run 'graph export' first.", file=sys.stderr)
            index.close()
            return 1
        import http.server
        import socketserver
        port = args.port
        os.chdir(str(out_dir))
        handler = http.server.SimpleHTTPRequestHandler
        print(f"Serving graph at http://localhost:{port}/graph.html" f" (Ctrl+C to stop)")
        try:
            with socketserver.TCPServer(("", port), handler) as httpd:
                httpd.serve_forever()
        except KeyboardInterrupt:
            print()
    else:
        print("Usage: entropicmem graph export|serve", file=sys.stderr)
        index.close()
        return 1

    stats = index.get_stats()
    index.close()
    return 0


# ── subcommand: project ──────────────────────────────────────────────────

def cmd_memory(args) -> int:
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    index = VaultIndex(index_path)
    mem_path = Path(os.environ.get("ENTROPICMEM_MEMORY_DB",
                   str(Path.home() / ".hermes" / "entropicmem" / "memory.db")))
    engine = MemoryEngine(mem_path)

    if args.memory_command == "project":
        r = engine.project_to_vault(vault, index, limit=500)
        print(f"Memory project: {r['created']} created, {r['updated']} updated, {r['skipped']} skipped")
        index.close()
        engine.close()
        return 0
    elif args.memory_command == "stats":
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
            preview = f.content.replace("\n", " ")[:120]
            print(f"{f.id}\t{f.domain}\t{preview}")
        engine.close()
        return 0
    else:
        print("Usage: entropicmem memory project|stats|list", file=sys.stderr)
        engine.close()
        return 1



# ── subcommand: recall ───────────────────────────────────────────────────

def cmd_recall(args) -> int:
    engine = MemoryEngine(_memory_db_path())
    results = engine.recall(args.query, top_k=args.top_k, domain=args.domain)
    if not results:
        print("No matching facts.")
        engine.close()
        return 0
    for r in results:
        preview = r.content.replace("\n", " ")
        print(f"[{r.id}] ({r.domain}) imp={r.importance:.2f} {preview}")
    engine.close()
    return 0


# ── subcommand: remember ─────────────────────────────────────────────────

def cmd_remember(args) -> int:
    vault_path, index_path = _resolve_env()
    vault = Vault(vault_path)
    domain = args.domain or "Knowledge"
    tags = args.tags.split(",") if args.tags else ["durable", "agent"]
    title = f"Fact - {args.fact[:60]}"
    body = (f"## Fact\n{args.fact}\n\n## Source\n- Agent (EntropicMem remember)\n\n## Links\n- [[{domain}/Index]]\n- [[Wiki-Cache]]\n")
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
    return 0


# ── subcommand: forget (vault-only) ─────────────────────────────────────────

def cmd_forget(args) -> int:
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
    return 0


# ── stub for Phase 3-4 ──────────────────────────────────────────────────────

def _stub(cmd: str) -> int:
    print(f"`entropicmem {cmd}` — not implemented yet. Coming in Phase 3–4.")
    return 0


def cmd_check_deps(args) -> int:
    """Report optional dependency status."""
    print("[EntropicMem deps]")
    print(f"  Core:        OK (Python {sys.version_info.major}.{sys.version_info.minor}, stdlib)")
    print(f"  sentence-tf: {'INSTALLED' if EMBEDDER_AVAILABLE else 'NOT INSTALLED  → semantic re-rank disabled'}")
    has_graphviz = shutil.which("dot") is not None
    print(f"  graphviz:    {'INSTALLED' if has_graphviz else 'NOT INSTALLED  → DOT export disabled'}")
    print(f"  Version:     {__version__}")
    return 0


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="entropicmem",
        description="EntropicMem — standalone agent memory system",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--check-deps", action="store_true", help="Print optional dependency status")

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Bootstrap a vault")
    p_init.add_argument("--vault", help="Vault root path")
    p_init.add_argument("--index-db", help="SQLite index DB path")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing seed files")
    p_init.add_argument("--dry-run", action="store_true", help="Print actions without writing")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Ingest a source (URL, file, or stdin)")
    p_ingest.add_argument("source", nargs="?", help="URL or file path")
    p_ingest.add_argument("--domain", default="Knowledge", help="Target domain folder")

    # ingest-pile
    p_pile = sub.add_parser("ingest-pile", help="Batch ingest a directory")
    p_pile.add_argument("dir", help="Directory of sources")
    p_pile.add_argument("--domain", default="Knowledge", help="Target domain folder")

    # query
    p_query = sub.add_parser("query", help="Search the vault")
    p_query.add_argument("query", help="Search query")
    p_query.add_argument("--top-k", type=int, default=10, help="Max results (default: 10)")
    p_query.add_argument("--semantic", action="store_true", help="Enable semantic re-rank")
    p_query.add_argument("--domain", help="Filter by domain")

    # note
    p_note = sub.add_parser("note", help="Create a note from stdin")
    p_note.add_argument("title", nargs="?", help="Note title")
    p_note.add_argument("--domain", default="Knowledge", help="Target domain folder")
    p_note.add_argument("--tags", help="Comma-separated tags")

    # research
    p_research = sub.add_parser("research", help="Create research brief for agent-driven web research")
    p_research.add_argument("query", help="Research question")
    p_research.add_argument("--rounds", type=int, default=3, help="Research rounds")

    # lint
    p_lint = sub.add_parser("lint", help="Check vault health")
    p_lint.add_argument("--domain", help="Filter by domain")

    # moc
    p_moc = sub.add_parser("moc", help="Build/repair domain Index.md + backlinks")
    p_moc.add_argument("--domain", help="Target domain")

    # hotcache
    sub.add_parser("hotcache", help="Rebuild Wiki-Cache.md")

    # graph
    p_graph = sub.add_parser("graph", help="Graph export and serve")
    g_sub = p_graph.add_subparsers(dest="graph_command")
    g_export = g_sub.add_parser("export", help="Export visual graph")
    g_export.add_argument("--format", default="html", choices=["json", "dot", "html", "canvas"])
    g_export.add_argument("--output-dir", default="./export", help="Output directory")
    g_export.add_argument("--max-nodes", type=int, default=500, help="Max nodes (default: 500)")
    g_export.add_argument("--domain", help="Filter by domain")
    g_export.add_argument("--min-importance", type=float, default=0.0, help="Min importance filter")
    g_serve = g_sub.add_parser("serve", help="Serve graph export dir via HTTP")
    g_serve.add_argument("--port", type=int, default=8069)
    g_serve.add_argument("--dir", default="./export")

    # recall
    p_recall = sub.add_parser("recall", help="Search durable facts in memory engine")
    p_recall.add_argument("query", help="Search query")
    p_recall.add_argument("--top-k", type=int, default=10)
    p_recall.add_argument("--domain", help="Filter by domain")

    # remember
    p_remember = sub.add_parser("remember", help="Store durable fact in memory engine + vault")
    p_remember.add_argument("fact", help="The fact to remember")
    p_remember.add_argument("--domain", default="Knowledge")
    p_remember.add_argument("--tags", help="Comma-separated tags")

    # forget
    p_forget = sub.add_parser("forget", help="Delete fact from memory engine and vault note")
    p_forget.add_argument("entropic_id", help="The entropic_id to forget")

    # memory
    p_memory = sub.add_parser("memory", help="Memory engine operations")
    m_sub = p_memory.add_subparsers(dest="memory_command")
    m_sub.add_parser("project", help="Project memory facts to vault")
    m_sub.add_parser("stats", help="Show memory engine statistics")
    m_list = m_sub.add_parser("list", help="List facts in memory engine")
    m_list.add_argument("--domain", help="Filter by domain")
    m_list.add_argument("--limit", type=int, default=50)

    # open
    p_open = sub.add_parser("open", help="Open a note in system editor")
    p_open.add_argument("note_id", help="Note ID (Domain/Name or vault://Domain/Name)")


    # Parse
    args = parser.parse_args()

    if args.version:
        print(f"entropicmem v{__version__}")
        return 0

    if getattr(args, "check_deps", False):
        return cmd_check_deps(args)

    if not args.command:
        parser.print_help()
        return 0

    # Route to subcommand
    routes = {
        "init": cmd_init,
        "ingest": cmd_ingest,
        "ingest-pile": cmd_ingest_pile,
        "query": cmd_query,
        "note": cmd_note,
        "research": cmd_research,
        "lint": cmd_lint,
        "moc": cmd_moc,
        "hotcache": cmd_hotcache,
        "graph": cmd_graph,
        "recall": cmd_recall,
        "remember": cmd_remember,
        "forget": cmd_forget,
        "open": cmd_open,
        "memory": cmd_memory,
    }

    handler = routes.get(args.command)
    if handler:
        return handler(args)

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
