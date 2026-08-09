"""
triple_extract.py — Rule-based knowledge-triple extraction (v2.2.0 G2).

Scans EntropicMem facts (and optionally vault notes) and emits
(subject, predicate, object) triples from a known-entity dictionary plus
relation patterns. Stdlib-only; no LLM required for the incremental path.

Entity dictionary: people, projects, services, accounts, banks, infra.
Relation patterns: explicit phrases ("works at", "replaced", "migrated to",
"backed up to", ...) plus co-occurrence heuristics (subject + domain tags).

The extractor is deliberately conservative: it only emits triples whose
subject AND object are both known entities, or whose relation phrase is
explicit. Precision over recall — the legacy triple backfill (12k+
legacy triples) provides breadth; this module keeps the graph growing
incrementally from new facts.
"""

import os
import re
import sys
from typing import Dict, List, Optional, Set, Tuple

# ── known entity dictionary ────────────────────────────────────────────────
# NOTE: This repo is public — keep this dict to GENERIC, non-personal names.
# Personal entities (owner names, family, employers, banks, personal
# projects) live in a LOCAL override file ($HERMES_HOME/entropicmem/
# known_entities_local.json) that is merged in at import time. Do not add
# personal identifiers here.

KNOWN_ENTITIES: Dict[str, Set[str]] = {
    "person": {
        "alice", "bob",
    },
    "company": {
        "nous research", "microsoft", "google", "openai", "meta",
    },
    "project": {
        "entropicmem", "mnemosyne", "hermes", "hermes agent", "mem0",
        "vaultknox", "tencentdb", "notion", "obsidian", "logseq",
    },
    "service": {
        "google drive", "gdrive", "tailscale", "cloudflare", "signal",
        "telegram", "discord", "notion", "obsidian", "logseq", "openrouter",
        "deepseek", "backblaze", "rclone", "gmail", "google calendar",
        "github",
    },
    "infra": {
        "linux", "ubuntu", "docker", "nginx", "systemd", "sqlite",
        "postgresql", "redis", "fastapi", "uvicorn", "python", "node",
        "typescript", "flutter", "tailscale", "cloudflare tunnel",
        "hermes gateway", "gateway", "graph server", "memory.db", "index.db",
    },
    "concept": {
        "memory", "recall", "prefetch", "embedding", "fts5", "hybrid search",
        "episodic memory", "knowledge graph", "triple store", "backup",
        "stability gate", "health check", "sole provider", "cutover",
        "migration", "dual-write", "cron", "plugin", "skill", "vault",
    },
}

# Flattened alias → canonical name map (lowercase alias → canonical entity).
_ALIAS_TO_ENTITY: Dict[str, str] = {}
for _cat, _names in KNOWN_ENTITIES.items():
    for _n in _names:
        _ALIAS_TO_ENTITY[_n] = _n

# Extra alias expansions (short forms, punctuation-stripped).
_EXTRA_ALIASES = {
    "gdrive": "Google Drive",
    "hermes agent": "Hermes",
    "memory.db": "memory.db",
    "index.db": "index.db",
}
_ALIAS_TO_ENTITY.update(_EXTRA_ALIASES)

# ── local (non-public) entity overrides ────────────────────────────────────
# The shipped dictionary stays generic because this repo is public. A local
# JSON file may add personal entities (owner names, employers, banks,
# personal projects) at import time. It lives OUTSIDE the repo, at
# $HERMES_HOME/entropicmem/known_entities_local.json, and is gitignored by
# virtue of not being in the repo. Shape:
#   {"person": ["alice"], "company": ["acme corp"], "aliases": {"acme": "Acme Corp"}}
def _load_local_entities() -> None:
    global KNOWN_ENTITIES, _ALIAS_TO_ENTITY, _CANONICAL_TITLE
    try:
        import json as _json
        from pathlib import Path as _Path
        home = _Path(os.environ.get("HERMES_HOME", _Path.home() / ".hermes"))
        local_file = home / "entropicmem" / "known_entities_local.json"
        if not local_file.is_file():
            return
        data = _json.loads(local_file.read_text(encoding="utf-8"))
        for cat, names in data.items():
            if cat == "aliases":
                continue
            if cat not in KNOWN_ENTITIES:
                KNOWN_ENTITIES[cat] = set()
            KNOWN_ENTITIES[cat].update(str(n).lower() for n in names)
        for alias, canonical in data.get("aliases", {}).items():
            _ALIAS_TO_ENTITY[str(alias).lower()] = str(canonical)
            _CANONICAL_TITLE[str(canonical)] = str(canonical)
            _CANONICAL_TITLE[str(canonical).lower()] = str(canonical)
        # Rebuild alias map for newly added known entities.
        for _cat, _names in KNOWN_ENTITIES.items():
            for _n in _names:
                _ALIAS_TO_ENTITY[_n] = _n
                _CANONICAL_TITLE.setdefault(_n, _n.title())
                _CANONICAL_TITLE.setdefault(_n.lower(), _n.title())
    except Exception as _e:  # local overrides must never break extraction
        print(f"note: local entity overrides skipped ({_e})", file=sys.stderr)


# Capitalize canonical display forms.
_CANONICAL_TITLE: Dict[str, str] = {
    "Hermes": "Hermes", "Mnemosyne": "Mnemosyne",
    "EntropicMem": "EntropicMem", "Google Drive": "Google Drive",
    "Obsidian": "Obsidian", "Notion": "Notion",
    "Logseq": "Logseq", "Tailscale": "Tailscale", "Cloudflare": "Cloudflare",
    "Signal": "Signal", "Telegram": "Telegram", "Discord": "Discord",
    "OpenRouter": "OpenRouter", "DeepSeek": "DeepSeek",
    "GitHub": "GitHub", "VaultKnox": "VaultKnox", "TencentDB": "TencentDB",
    "Linux": "Linux", "Ubuntu": "Ubuntu", "Docker": "Docker", "Nginx": "Nginx",
    "systemd": "systemd", "SQLite": "SQLite", "FastAPI": "FastAPI",
    "Python": "Python", "Node": "Node", "TypeScript": "TypeScript",
    "Flutter": "Flutter", "Rclone": "Rclone",
    "Mem0": "Mem0", "memory.db": "memory.db", "index.db": "index.db",
}

# Also index lowercase forms so alias lookups resolve to display case.
for _key, _disp in list(_CANONICAL_TITLE.items()):
    _CANONICAL_TITLE.setdefault(_key.lower(), _disp)
for _name in KNOWN_ENTITIES["person"]:
    _CANONICAL_TITLE.setdefault(_name, _name.title())
    _CANONICAL_TITLE.setdefault(_name.lower(), _name.title())

# Local (non-public) entity overrides — merged AFTER the canonical maps are
# built so both dictionaries stay consistent.
_load_local_entities()


def canonical_entity(name: str) -> str:
    """Map an alias to its canonical display form (title-cased where known)."""
    key = name.strip().lower()
    canonical = _ALIAS_TO_ENTITY.get(key, name.strip())
    return _CANONICAL_TITLE.get(canonical) or _CANONICAL_TITLE.get(key) or canonical


def known_entity(name: str) -> bool:
    """True if the name (case-insensitive) is in the entity dictionary."""
    key = name.strip().lower()
    return key in _ALIAS_TO_ENTITY


def find_entities(text: str) -> List[str]:
    """All known entities mentioned in a text, canonicalized, de-duplicated."""
    found: List[str] = []
    seen: Set[str] = set()
    lower = text.lower()
    for alias, canonical in _ALIAS_TO_ENTITY.items():
        if len(alias) < 3:
            continue
        # Word-boundary match, tolerant of punctuation (@, :, etc.)
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", lower):
            display = canonical_entity(canonical)
            if display not in seen:
                seen.add(display)
                found.append(display)
    return found


# ── relation patterns ───────────────────────────────────────────────────────

# (regex, predicate). Subject = entity before the phrase, object = after.
_RELATION_PATTERNS: List[Tuple[str, str]] = [
    (r"\b(works? at|works? for|employed by|is employed at)\b", "works_at"),
    (r"\b(is|was) (the )?(founder|owner|author|creator|maintainer) of\b", "owns"),
    (r"\b(uses?|relies? on|depends? on|runs? on|built with|built on)\b", "uses"),
    (r"\b(replaced|replaces|superseded|supersedes|migrated (away )?from)\b", "replaced"),
    (r"\b(migrated to|moved to|switched to|cut over to|cutover to)\b", "migrated_to"),
    (r"\b(backed? up to|backups? to|synced? to|syncs? to|exports? to)\b", "backs_up_to"),
    (r"\b(integrat(es|ed)? with|connects? to|talks? to|interfaces? with)\b", "integrates_with"),
    (r"\b(part of|member of|component of|module of)\b", "part_of"),
    (r"\b(built|developed|created|wrote|designed|maintains?)\b", "developed"),
    (r"\b(runs? (on|under)|deployed on|hosted on|installed on)\b", "runs_on"),
    (r"\b(provides?|offers?|delivers?)\b", "provides"),
    (r"\b(belongs? to|owned by)\b", "owned_by"),
    (r"\b(prefers?|likes?|favou?rs?)\b", "prefers"),
    (r"\b(planned?|scheduled?|targeted?) (for|at)\b", "scheduled_for"),
    (r"\b(price|cost|worth|valued at|budgeted? at|is|was) (R|ZAR|USD|EUR|\\$)?\\s?\\d", "valued_at"),
]

# Negated predicates (subject excludes object) — e.g. "no longer uses".
_NEGATION_PREFIX = re.compile(r"\b(no longer|not|never|stopped|quit|removed)\b")


def extract_triples_from_text(text: str) -> List[Tuple[str, str, str]]:
    """Rule-based triple extraction from a single text blob.

    Returns (subject, predicate, object) tuples with canonical entity names.
    Only emits triples where both endpoints are known entities, or where an
    explicit relation phrase connects a known entity to a noun phrase.
    """
    triples: List[Tuple[str, str, str]] = []
    entities = find_entities(text)
    if not entities:
        return triples

    for pattern, predicate in _RELATION_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            before = text[max(0, m.start() - 80):m.start()]
            after = text[m.end():m.end() + 80]
            before_entities = find_entities(before)
            after_entities = find_entities(after)
            if not before_entities and not after_entities:
                continue
            # Subject = nearest entity before the phrase; object = nearest after.
            subject = before_entities[-1] if before_entities else (after_entities[0] if after_entities else None)
            object_ = after_entities[0] if after_entities else (before_entities[-1] if before_entities else None)
            if not subject or not object_ or subject == object_:
                continue
            # Negation handling: "no longer uses X" → (subject, not_uses, X)
            negated = bool(_NEGATION_PREFIX.search(before[-40:]))
            final_pred = ("not_" + predicate) if negated else predicate
            triples.append((subject, final_pred, object_))

    return triples


def extract_triples_from_engine(engine, limit: int = 2000) -> int:
    """Extract triples from all facts (and note titles) into the engine.

    Incremental-safe: skips triples that already exist (UNIQUE constraint
    + upsert). Returns the count of newly written triples.
    """
    facts = engine.list_facts(limit=limit)
    written = 0
    for fact in facts:
        text = f"{fact.title or ''}. {fact.content}"
        for subject, predicate, object_ in extract_triples_from_text(text):
            engine.upsert_triple(
                subject, predicate, object_,
                valid_from=fact.created_at,
                source="extracted",
                confidence=0.7,
            )
            written += 1
    return written
