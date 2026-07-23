#!/usr/bin/env python3
"""
Consolidated Notion → EntropicMem ingester for cron / no_agent contexts.

Input mode:
    --mode json    : read Notion sync JSON from stdin or --input
    --mode fetch   : fetch target pages/databases directly via Notion API then ingest

Output:
    short structured summary plus verified fact counts.
    On --dry-run, only prints candidate facts without writing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    sys.path.insert(0, str(HERMES_HOME / "skills" / "entropicmem" / "scripts"))
    from memory_engine import MemoryEngine  # type: ignore
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"FATAL: cannot import MemoryEngine: {exc}") from exc

ENTROPICMEM_DB = Path(
    os.environ.get("ENTROPICMEM_MEMORY_DB", str(HERMES_HOME / "entropicmem" / "memory.db"))
)
INPUT_ENV = os.environ.get("NOTION_SYNC_INPUT", "/tmp/notion_sync_entropicmem.json")

SENSITIVE_KW = [
    "token", "api_key", "apikey", "password", "secret", "bearer ",
    "client_id", "client_secret", "sk-", "pk-", "ghp_", "nvapi-",
    "pat", "master password", "app password",
]

BLOCKLIST = {
    "ai stuffies", "x developer", "discord developer",
    "jira confluence hermes", "to-do list", "to-do list db", "untitled",
}

TARGET_PAGES = [
    "Ajax SDK",
    "Pre-Sales (General)",
    "Migrate Translator",
    "Meeting Prep",
    "Deal Pipeline",
    "Email Digests",
    "Calendar & Tasks",
]

IMPORTANCE_MAP: dict[str, float] = {
    "Ajax SDK": 0.7,
    "Pre-Sales (General)": 0.6,
    "Migrate Translator": 0.6,
    "Meeting Prep": 0.55,
    "Deal Pipeline": 0.55,
    "Email Digests": 0.5,
    "Calendar & Tasks": 0.5,
}

DATABASE_HINTS = {
    "meeting": "Meeting Prep",
    "deal": "Deal Pipeline",
    "email": "Email Digests",
    "key emails": "Email Digests",
    "task": "Calendar & Tasks",
    "calendar": "Calendar & Tasks",
}

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _looks_sensitive(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in SENSITIVE_KW)


def _api_key() -> str:
    key = os.getenv("NOTION_API_KEY")
    if key:
        return key
    env_path = HERMES_HOME / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("NOTION_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("FATAL: NOTION_API_KEY not found in env or ~/.hermes/.env")


def _notion(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"https://api.notion.com/v1{path}"
    cmd = [
        "curl", "-s", "-m", "30", "-X", method, url,
        "-H", f"Authorization: Bearer {_api_key()}",
        "-H", "Notion-Version: 2022-06-28",
        "-H", "Content-Type: application/json",
    ]
    if payload is not None:
        cmd += ["-d", json.dumps(payload)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"error": proc.stderr.strip()}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": f"Notion returned non-JSON: {proc.stdout[:300]}"}


def _get_page_title(page: dict) -> str:
    props = page.get("properties", {})
    for key in ("title", "Name", "Page", "Task name", "Event Name"):
        prop = props.get(key, {})
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    title = page.get("title")
    if isinstance(title, list):
        return "".join(t.get("plain_text", "") for t in title)
    return page.get("title") or "Untitled"


def _get_block_text(block: dict) -> str:
    btype = block.get("type")
    if not btype:
        return ""
    body = block.get(btype, {})
    for field in ("rich_text", "text", "caption"):
        items = body.get(field, [])
        if isinstance(items, list):
            return "".join(item.get("plain_text", "") for item in items if isinstance(item, dict))
    return ""


def _fetch_blocks(page_id: str, max_depth: int = 2, max_blocks: int = 120) -> list[dict]:
    blocks: list[dict] = []
    cursor = None
    for _ in range(3):
        path = f"/blocks/{page_id}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        resp = _notion("GET", path)
        for b in resp.get("results", []):
            blocks.append(b)
            if len(blocks) >= max_blocks:
                return blocks
            if b.get("has_children") and max_depth > 1:
                blocks.extend(
                    _fetch_blocks(b["id"], max_depth=max_depth - 1, max_blocks=max_blocks - len(blocks))
                )
                if len(blocks) >= max_blocks:
                    return blocks
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return blocks


def _query_database(db_id: str, max_entries: int = 10) -> list[dict]:
    entries: list[dict] = []
    cursor = None
    for _ in range(10):
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        resp = _notion("POST", f"/databases/{db_id}/query", payload)
        if "results" not in resp:
            break
        for entry in resp["results"]:
            props = entry.get("properties", {})
            item: dict[str, object] = {"id": entry["id"], "url": entry.get("url", "")}
            title = ""
            for k, v in props.items():
                if v.get("type") == "title":
                    title = "".join(t.get("plain_text", "") for t in v.get("title", []))
                    item[k] = title
                    break
            item.setdefault("title", title)
            entries.append(item)
            if len(entries) >= max_entries:
                return entries
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return entries


def _identify_db(db: dict) -> str | None:
    schema = {s.lower() for s in db.get("schema", [])}
    hint_to_db = {
        frozenset({"meeting", "prep notes", "purpose", "outcome", "agenda"}): "Meeting Prep",
        frozenset({"deal", "company", "stage", "value (zar)", "contact", "next step"}): "Deal Pipeline",
        frozenset({"task", "status", "type", "priority", "due date"}): "Calendar & Tasks",
    }
    for keys, name in hint_to_db.items():
        if keys & schema:
            return name
    extra = {
        "email": "Email Digests",
        "digest": "Email Digests",
        "calendar": "Calendar & Tasks",
        "meeting": "Meeting Prep",
        "deal": "Deal Pipeline",
    }
    candidates = [extra[k] for k in schema if k in extra]
    return candidates[0] if candidates else None


def _extract_facts(title: str, content: str, entries: list[dict] | None = None) -> list[dict]:
    facts: list[dict] = []
    norm = (title or "").strip()
    if norm in BLOCKLIST or not norm or norm.lower() == "untitled":
        return facts

    if norm == "Ajax SDK" and content:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', content) if 20 < len(s.strip()) < 700]
        for sentence in sentences[:5]:
            facts.append({"content": sentence, "importance": 0.7, "source": "notion"})

    elif norm in {"Pre-Sales (General)", "Migrate Translator"} and content:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', content) if 20 < len(s.strip()) < 700]
        for sentence in sentences[:5]:
            facts.append({"content": sentence, "importance": 0.6, "source": "notion"})

    elif norm in {"Meeting Prep", "Deal Pipeline", "Email Digests", "Calendar & Tasks"} and entries:
        importance = IMPORTANCE_MAP.get(norm, 0.5)
        for entry in entries[:5]:
            title_val = (entry.get("title") or entry.get("name") or "").strip()
            if not title_val or title_val.lower() == "untitled":
                continue
            parts = []
            for k, v in entry.items():
                if k in {"id", "url", "last_edited", "title", "name"}:
                    continue
                if isinstance(v, str) and v.strip():
                    parts.append(f"{k}: {v.strip()}")
                elif isinstance(v, list) and v:
                    parts.append(f"{k}: {', '.join(str(x) for x in v)}")
                elif isinstance(v, dict) and v:
                    parts.append(f"{k}: {v.get('start', v)}")
            if not parts:
                continue
            facts.append({
                "content": f"[{norm}] {title_val}: {'; '.join(parts)}",
                "importance": importance,
                "source": "notion",
            })

    if not facts and content:
        combined = " ".join(content.split())[:500]
        if combined and len(combined) > 50:
            facts.append({"content": combined, "importance": 0.55, "source": "notion"})
    return facts


def _store_facts(facts: list[dict], origin_filter: str, dry_run: bool) -> tuple[int, int, list[str]]:
    safe_facts = []
    for fact in facts:
        content = fact.get("content") or ""
        if not content.strip() or _looks_sensitive(content):
            continue
        safe_facts.append(fact)
    if dry_run:
        preview = [f"{f['importance']} {f['content'][:80]}" for f in safe_facts[:5]]
        return len(safe_facts), len(safe_facts), preview

    engine = MemoryEngine(ENTROPICMEM_DB)
    kept = 0
    preview: list[str] = []
    with engine:
        for fact in safe_facts:
            content = fact.get("content") or ""
            eid = engine.remember(
                content=content,
                title=content[:60],
                domain=fact.get("domain", "Projects"),
                source="notion",
                importance=float(fact.get("importance", 0.5)),
            )
            kept += 1
            if len(preview) < 5:
                preview.append(f"{fact.get('importance', 0.5)} {content[:80]}")
    return len(safe_facts), kept, preview


def _ingest_pages_and_dbs(data: dict, dry_run: bool) -> dict:
    skipped_pages: list[str] = []
    skipped_dbs: list[str] = []
    all_facts: list[dict] = []

    seen_titles: set[str] = set()
    for page in data.get("pages", []):
        title = (page.get("title") or "Untitled").strip()
        norm = title.lower()
        if norm in BLOCKLIST or not title or title.lower() == "untitled":
            skipped_pages.append(title or "<untitled>")
            continue
        if norm in seen_titles:
            continue
        seen_titles.add(norm)
        importance = IMPORTANCE_MAP.get(title, 0.55 if "Ajax" in title else 0.5)
        facts = _extract_facts(title, page.get("content", "") or "")
        for fact in facts:
            fact["importance"] = importance
        all_facts.extend(facts)

    for db in data.get("databases", []):
        title = (db.get("title") or "<untitled-db>").strip()
        norm = title.lower()
        if norm in BLOCKLIST:
            skipped_dbs.append(f"{title}: blocklisted")
            continue
        recognized = _identify_db(db)
        if not recognized:
            skipped_dbs.append(f"{title}: not a focused DB/empty")
            continue
        entries = db.get("entries", [])[:5]
        filtered = []
        seen_entries: set[str] = set()
        for entry in entries:
            et = (entry.get("title") or "").strip()
            if not et or et.lower() in {"test"} or et in seen_entries:
                continue
            seen_entries.add(et)
            filtered.append(entry)
        facts = _extract_facts(recognized, "", filtered)
        all_facts.extend(facts)

    requested, kept, preview = _store_facts(all_facts, "notion", dry_run)
    return {
        "requested_facts": requested,
        "stored_facts": kept,
        "preview": preview,
        "skipped_pages": skipped_pages,
        "skipped_databases": skipped_dbs,
        "security_scan": "OK",
    }


def _fetch_targets() -> dict:
    all_pages: dict[str, dict] = {}
    for target in TARGET_PAGES:
        resp = _notion("POST", "/search", {"query": target, "page_size": 100})
        if "error" in resp:
            continue
        for item in resp.get("results", []):
            title = _get_page_title(item)
            obj_type = item.get("object")
            item_id = item["id"]
            if target.lower() not in title.lower():
                continue
            if any(s in title.lower() for s in BLOCKLIST):
                continue
            all_pages[item_id] = {"id": item_id, "title": title, "type": obj_type, "url": item.get("url", "")}

    pages: list[dict] = []
    databases: list[dict] = []
    for info in all_pages.values():
        if info["type"] == "database":
            entries = _query_database(info["id"])[:10]
            databases.append({
                "id": info["id"],
                "title": info["title"],
                "url": info["url"],
                "schema": [],
                "entry_count": len(entries),
                "entries": entries,
            })
        else:
            blocks = _fetch_blocks(info["id"])
            lines = [f"{'# ' if b.get('type','').startswith('heading') else '- ' if b.get('type')=='bulleted_list_item' else '1. ' if b.get('type')=='numbered_list_item' else ''}{_get_block_text(b)}".strip() for b in blocks if _get_block_text(b).strip()]
            pages.append({
                "id": info["id"],
                "title": info["title"],
                "url": info["url"],
                "content": "\n".join(lines),
                "full_content_length": sum(len(l) for l in lines),
            })
    return {"pages": pages, "databases": databases}


def main() -> int:
    ap = argparse.ArgumentParser(description="Notion → EntropicMem")
    ap.add_argument("--mode", choices=["json", "fetch"], default="json")
    ap.add_argument("--input", default=INPUT_ENV)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        if args.dry_run:
            print(json.dumps({"ok": True, "dry_run": True, "would_store": "self-test probe"}))
            return 0
        _, kept, preview = _store_facts(
            [{"content": "Notion→EntropicMem ingester self-test", "importance": 0.4, "source": "notion_self_test"}],
            "notion",
            False,
        )
        print(json.dumps({"ok": True, "stored_facts": kept, "preview": preview}))
        return 0 if kept else 2

    if args.mode == "fetch":
        data = _fetch_targets()
    else:
        src = Path(args.input)
        if not src.exists():
            raise SystemExit(f"FATAL: input file missing: {src}")
        data = json.loads(src.read_text())

    summary = _ingest_pages_and_dbs(data, dry_run=args.dry_run)
    print(json.dumps({"ok": True, "synced_at": _now_iso(), **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
