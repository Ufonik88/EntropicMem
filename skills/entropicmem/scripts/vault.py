"""
vault.py — Core vault operations for EntropicMem.

Reads, writes, and manages Markdown notes in an Obsidian-style vault.
Stdlib-only. All paths are Path objects. Never writes to protected prefixes.

Protected prefixes (never write):
    Mnemosyne/   — auto-generated mirror
    .obsidian/   — Obsidian config
    _archive/    — historical exports
"""

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ── protected prefixes (never write) ────────────────────────────────────────
PROTECTED_PREFIXES = ("Mnemosyne/", ".obsidian/", "_archive/", ".stfolder/")

# ── domain list (seeded at init) ────────────────────────────────────────────
DEFAULT_DOMAINS = [
    "Infrastructure",
    "Ajax Systems",
    "X-Growth",
    "Finance",
    "Workflows",
    "People",
    "Knowledge",
    "Products-Research",
    "Projects",
]

# ── data classes ────────────────────────────────────────────────────────────

@dataclass
class Note:
    """Parsed representation of a vault note."""
    path: Path                      # relative to vault root
    title: str
    body: str                       # everything after frontmatter
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    created: str = ""
    updated: str = ""
    source: str = ""
    source_url: str = ""
    aliases: List[str] = field(default_factory=list)
    agent: bool = False
    entropic_id: str = ""
    domain: str = ""
    note_type: str = "permanent"    # literature|permanent|moc|index|log

    @property
    def note_id(self) -> str:
        """Stable identifier: Domain/filename-without-extension."""
        try:
            rel = self.path.relative_to(self.path.parent.parent)
        except ValueError:
            rel = self.path
        return str(rel.with_suffix(""))

    @property
    def importance(self) -> float:
        """Heuristic importance score based on tags, links, length."""
        score = 0.3
        score += min(len(self.tags) * 0.05, 0.2)
        link_count = len(re.findall(r'\[\[(.+?)\]\]', self.body))
        score += min(link_count * 0.03, 0.3)
        score += min(len(self.body.split()) / 500 * 0.1, 0.2)
        return round(min(score, 1.0), 2)

    def compute_entropic_id(self) -> str:
        """Deterministic content hash for Mnemosyne round-trip."""
        payload = self.title + "\n" + self.body
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_frontmatter_block(self) -> str:
        """Serialize frontmatter to YAML-like block."""
        lines = ["---"]
        lines.append(f'title: "{self.title}"')
        lines.append(f'type: "{self.note_type}"')
        if self.tags:
            tags_str = ", ".join(self.tags)
            lines.append(f"tags: [{tags_str}]")
        today = self.created or date.today().isoformat()
        lines.append(f'created: "{today}"')
        lines.append(f'updated: "{today}"')
        if self.source:
            lines.append(f'source: "{self.source}"')
        if self.source_url:
            lines.append(f'source_url: "{self.source_url}"')
        if self.aliases:
            aliases_str = ", ".join(self.aliases)
            lines.append(f"aliases: [{aliases_str}]")
        if self.agent:
            lines.append("agent: true")
        eid = self.entropic_id or self.compute_entropic_id()
        lines.append(f'entropic_id: "{eid}"')
        if self.domain:
            lines.append(f'domain: "{self.domain}"')
        lines.append("---")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Render full note as Markdown text."""
        fm = self.to_frontmatter_block()
        return f"{fm}\n\n{self.body}\n"


# ── vault class ─────────────────────────────────────────────────────────────

class Vault:
    """Operations on an Obsidian-style Markdown vault."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    # ── path helpers ────────────────────────────────────────────────────

    def resolve_path(self, relative: str) -> Path:
        """Resolve a relative path within the vault. Accepts vault://Domain/Note format."""
        clean = relative.removeprefix("vault://")
        return self.root / clean

    def sanitize(self, name: str) -> str:
        """Sanitize a string into a safe filename stub."""
        slug = name.lower().strip()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"\s+", "-", slug)
        return slug[:80]

    def _is_protected(self, rel: Path) -> bool:
        """Check if a relative path falls under a protected prefix."""
        r = str(rel)
        return any(r.startswith(p) for p in PROTECTED_PREFIXES)

    def is_safe_mode(self) -> bool:
        """Detect safe mode: AGENTS.md already exists in the vault root."""
        return (self.root / "AGENTS.md").exists()

    # ── file operations ─────────────────────────────────────────────────

    def read_frontmatter(self, path: Path) -> Dict[str, Any]:
        """Parse YAML-like frontmatter from a note file. Stdlib-only — no PyYAML."""
        text = path.read_text(encoding="utf-8")
        fm: Dict[str, Any] = {}
        if not text.startswith("---"):
            return fm
        parts = text.split("---", 2)
        if len(parts) < 3:
            return fm
        block = parts[1]
        for line in block.strip().split("\n"):
            line = line.strip()
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # parse list values: [a, b, c]
            if val.startswith("[") and val.endswith("]"):
                val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
            # parse bool
            elif val.lower() == "true":
                val = True
            elif val.lower() == "false":
                val = False
            fm[key] = val
        return fm

    def read_note(self, path: Path) -> Note:
        """Read a note from disk and parse frontmatter + body."""
        full = self.root / path if not path.is_absolute() else path
        text = full.read_text(encoding="utf-8")
        fm: Dict[str, Any] = {}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm = self.read_frontmatter(full)
                body = parts[2].strip()
        title = fm.get("title", full.stem.replace("-", " ").title())
        return Note(
            path=path if not path.is_absolute() else path.relative_to(self.root),
            title=title,
            body=body,
            frontmatter=fm,
            tags=fm.get("tags", []),
            created=fm.get("created", ""),
            updated=fm.get("updated", ""),
            source=fm.get("source", ""),
            source_url=fm.get("source_url", ""),
            aliases=fm.get("aliases", []),
            agent=fm.get("agent", False),
            entropic_id=fm.get("entropic_id", ""),
            domain=fm.get("domain", ""),
            note_type=fm.get("type", "permanent"),
        )

    def write_note(
        self,
        folder: str,
        title: str,
        body: str,
        tags: Optional[List[str]] = None,
        frontmatter: Optional[Dict[str, Any]] = None,
        note_type: str = "permanent",
        source: str = "agent",
        source_url: str = "",
        domain: str = "",
        agent: bool = True,
    ) -> Path:
        """
        Create a new note. Returns the relative path within the vault.

        Raises ValueError if the path is write-protected (Mnemosyne/, .obsidian/, _archive/).
        """
        slug = self.sanitize(title)
        filename = f"{slug}.md"
        filepath = self.root / folder / filename

        # ── write guard ──
        rel_check = Path(folder) / filename
        if self._is_protected(rel_check):
            raise ValueError(
                f"Path '{rel_check}' is write-protected. "
                f"EntropicMem never writes to {', '.join(PROTECTED_PREFIXES)}."
            )

        filepath.parent.mkdir(parents=True, exist_ok=True)

        note = Note(
            path=Path(folder) / filename,
            title=title,
            body=body,
            tags=tags or [],
            note_type=note_type,
            source=source,
            source_url=source_url,
            domain=domain or folder,
            agent=agent,
            created=date.today().isoformat(),
        )
        if frontmatter:
            for k, v in frontmatter.items():
                setattr(note, k, v) if hasattr(note, k) else None

        filepath.write_text(note.to_markdown(), encoding="utf-8")
        return Path(folder) / filename

    def append_note(self, path: Path, content: str, anchor: Optional[str] = None) -> None:
        """Append content to an existing note, optionally after an anchor line."""
        text = (self.root / path).read_text(encoding="utf-8")
        if anchor and anchor in text:
            idx = text.index(anchor) + len(anchor)
            text = text[:idx] + "\n" + content + text[idx:]
        else:
            text += "\n" + content
        (self.root / path).write_text(text, encoding="utf-8")

    def patch_note(
        self, path: Path, old_string: str, new_string: str, replace_all: bool = False
    ) -> None:
        """Find-and-replace inside a note body."""
        text = (self.root / path).read_text(encoding="utf-8")
        if replace_all:
            text = text.replace(old_string, new_string)
        else:
            count = text.count(old_string)
            if count == 0:
                raise ValueError(f"old_string not found in {path}")
            if count > 1:
                raise ValueError(f"old_string appears {count} times in {path} — use replace_all=True")
            text = text.replace(old_string, new_string, 1)
        (self.root / path).write_text(text, encoding="utf-8")

    def delete_note(self, path: Path) -> None:
        """Delete a note. Refuses to delete protected paths."""
        if self._is_protected(path):
            raise ValueError(f"Cannot delete protected path: {path}")
        full = self.root / path
        if full.exists():
            full.unlink()

    def list_notes(
        self,
        folder: Optional[str] = None,
        include_archive: bool = False,
    ) -> List[Path]:
        """List all Markdown files, optionally scoped to a folder. Skips protected + archive."""
        base = self.root / (folder or "")
        if not base.exists():
            return []
        notes = []
        for md in base.rglob("*.md"):
            rel = md.relative_to(self.root)
            if self._is_protected(rel):
                continue
            if not include_archive and any(p in str(rel) for p in ["_archive/", ".obsidian/"]):
                continue
            notes.append(rel)
        return sorted(notes)

    def search_notes(
        self, pattern: str, folder: Optional[str] = None
    ) -> List[Tuple[Path, int, str]]:
        """Grep-like search inside note bodies. Returns (path, line_number, line)."""
        results = []
        base = self.root / (folder or "")
        if not base.exists():
            return results
        for md in base.rglob("*.md"):
            rel = md.relative_to(self.root)
            if self._is_protected(rel):
                continue
            for i, line in enumerate(md.read_text(encoding="utf-8").split("\n"), 1):
                if pattern.lower() in line.lower():
                    results.append((rel, i, line.strip()[:200]))
        return results

    def get_all_titles(self) -> Dict[str, Path]:
        """Build {title: relative_path} for all notes (for linkify)."""
        titles: Dict[str, Path] = {}
        for rel in self.list_notes():
            note = self.read_note(rel)
            titles[note.title] = rel
            for alias in note.aliases:
                titles[alias] = rel
        return titles

    def linkify(self, text: str) -> str:
        """Convert known note titles in text to [[wikilinks]]."""
        titles = self.get_all_titles()
        # sort by length descending to match longest first (avoid partial matches)
        for title in sorted(titles.keys(), key=len, reverse=True):
            if title in text and f"[[{title}]]" not in text:
                # only replace standalone occurrences (word boundaries)
                text = re.sub(
                    rf"(?<!\[\[)(?<!\w){re.escape(title)}(?!\w)(?!\]\])",
                    f"[[{title}]]",
                    text,
                )
        return text

    def extract_wikilinks(self, text: str) -> List[str]:
        """Extract all [[wikilink]] targets from text."""
        return re.findall(r"\[\[(.+?)\]\]", text)

    def get_domains(self) -> List[str]:
        """Return list of domain folders that have content."""
        domains = []
        for item in sorted(self.root.iterdir()):
            if item.is_dir() and not item.name.startswith(".") and item.name not in ("inbox", "templates", ".raw", "Mnemosyne", "_archive", "attachments"):
                if item.name in DEFAULT_DOMAINS or any(item.iterdir()):
                    domains.append(item.name)
        return domains

    def open_note(self, note_id: str) -> None:
        """
        Open a note in the system editor. Accepts 'vault://Domain/Note' or 'Domain/Note' format.
        Falls back to $EDITOR → code → xdg-open.
        """
        path = self.resolve_path(note_id)
        if not path.exists():
            # try with .md extension
            path = Path(str(path) + ".md")
        if not path.exists():
            raise FileNotFoundError(f"Note not found: {note_id}")

        editors = [
            os.environ.get("EDITOR"),
            os.environ.get("VISUAL"),
            "code",
            "gedit",
            "xdg-open",
        ]
        for editor in editors:
            if editor and shutil.which(editor):
                subprocess.run([editor, str(path)], check=False)
                return
        raise RuntimeError("No editor found. Set $EDITOR or install code.")


# ── module-level helpers ────────────────────────────────────────────────────

def resolve_vault_path(explicit: Optional[str] = None) -> Path:
    """
    Resolve vault path from env vars or defaults.

    Order of precedence:
    1. ENTROPICMEM_VAULT_PATH env var
    2. OBSIDIAN_VAULT_PATH env var
    3. ~/Documents/Obsidian Vault (if AGENTS.md exists → safe mode)
    4. ~/.hermes/entropicmem/vault (new vault)
    """
    if explicit:
        return Path(explicit).expanduser().resolve()

    env_path = os.environ.get("ENTROPICMEM_VAULT_PATH") or os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_path:
        return Path(os.path.expandvars(env_path)).expanduser().resolve()

    default_vault = Path.home() / "Documents" / "Obsidian Vault"
    if (default_vault / "AGENTS.md").exists():
        return default_vault

    return Path.home() / ".hermes" / "entropicmem" / "vault"
