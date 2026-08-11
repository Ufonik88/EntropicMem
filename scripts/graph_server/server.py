from __future__ import annotations

# Canonical source for the graph server. Deployed (symlink-free) copy runs
# from ~/.hermes/entropicmem/graph_server/server.py under the systemd user
# unit entropicmem-graph-server.service. Keep both copies identical; after
# editing here, sync the deployed copy and restart the unit.
#
# Path resolution (portable - no hard-coded user home paths):
#   HERMES_HOME                 default ~/.hermes; override via env
#   ENTROPICMEM_SCRIPTS_DIR     optional override for engine scripts
#   ENTROPICMEM_GRAPH_EXPORT_DIR  optional override for graph.html/json dir
# Data paths (vault/index) are pinned under HERMES_HOME/entropicmem/ so a
# poisoned ENTROPICMEM_* env cannot point refresh at a dead /tmp dataset
# (same hard-pin policy as the v2.1.8 index watchdog).
#
# Note bodies (v2.2.2):
#   Local authenticated refresh defaults include_bodies=True so the modal
#   can show markdown. Static export CLI still defaults False (security).
#   GET /api/note/{note_id} lazy-loads body when the embedded export omitted
#   it (or for notes opened after a lean export).

import os
import sys
import json
import hmac
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

HERE = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def _resolve_scripts_dir() -> Path:
    override = os.environ.get("ENTROPICMEM_SCRIPTS_DIR")
    if override:
        return Path(override)
    candidates = [
        HERMES_HOME / "skills" / "entropicmem" / "scripts",
        # Repo checkout layout: <repo>/scripts/graph_server/server.py
        HERE.parents[1] / "skills" / "entropicmem" / "scripts",
        # Public product repo when this file lives under EntropicMem-Internal
        Path.home() / "Documents" / "dev" / "EntropicMem" / "skills" / "entropicmem" / "scripts",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def _looks_like_repo_root(path: Path) -> bool:
    """True only for an EntropicMem checkout, not HERMES_HOME.

    ~/.hermes also has skills/entropicmem (often a symlink into the repo),
    so a bare skills/ check would mis-identify HERMES_HOME as the checkout
    and point BASE_DIR at ~/.hermes/graph_export.
    """
    return (
        (path / "pyproject.toml").is_file()
        and (path / "scripts" / "graph_server").is_dir()
        and (path / "skills" / "entropicmem" / "scripts").is_dir()
    )


def _resolve_export_dir() -> Path:
    override = os.environ.get("ENTROPICMEM_GRAPH_EXPORT_DIR")
    if override:
        return Path(override)

    # Repo checkout: <repo>/scripts/graph_server → <repo>/graph_export
    repo_root = HERE.parents[1]
    if _looks_like_repo_root(repo_root):
        return repo_root / "graph_export"

    # Deployed under ~/.hermes/entropicmem/graph_server - follow the skills
    # symlink (if present) back to the checkout's graph_export.
    skills_scripts = HERMES_HOME / "skills" / "entropicmem" / "scripts"
    if skills_scripts.exists():
        # <repo>/skills/entropicmem/scripts → parents[2] = <repo>
        repo_via_skills = skills_scripts.resolve().parent.parent.parent
        if _looks_like_repo_root(repo_via_skills):
            return repo_via_skills / "graph_export"

    return HERMES_HOME / "entropicmem" / "graph_export"


SCRIPTS_DIR = _resolve_scripts_dir()
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from graph_export import export_json, export_html  # noqa: E402
from index import VaultIndex  # noqa: E402
from vault import Vault, resolve_vault_path  # noqa: E402

BASE_DIR = _resolve_export_dir()
# Hard-pin data paths under HERMES_HOME (do not trust ENTROPICMEM_* env).
INDEX_DB = HERMES_HOME / "entropicmem" / "index.db"
DEFAULT_VAULT = HERMES_HOME / "entropicmem" / "vault"

app = FastAPI(title="EntropicMem Graph")


def _refresh_token() -> str:
    return (os.environ.get("ENTROPICMEM_GRAPH_TOKEN") or "").strip()


def _require_token(x_entropicmem_token: str | None) -> None:
    expected = _refresh_token()
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="Refresh disabled: set ENTROPICMEM_GRAPH_TOKEN to enable",
        )
    provided = (x_entropicmem_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing token")


def _vault_root() -> Path:
    vault_root = DEFAULT_VAULT
    if not vault_root.is_dir():
        vault_root = Path(resolve_vault_path())
    return vault_root


def _regenerate(*, include_bodies: bool = True) -> dict:
    """Rebuild index + export graph.

    include_bodies defaults True for the local authenticated viewer so node
    modals show markdown. Pass include_bodies=False for a lean/shareable
    export without vault content.
    """
    vault_root = _vault_root()
    index = VaultIndex(INDEX_DB)
    try:
        # v2.1.8: rebuild the index from the vault before exporting.
        # Notes written outside the remember() path (wiki.py, Obsidian,
        # vault auto-commit) never reach index.db on their own, so the
        # exported graph would silently go stale. rebuild() reindexes every
        # note and the wikilink graph edges.
        vault = Vault(vault_root)
        rebuilt = index.rebuild(vault)
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        # Both JSON and HTML must receive the same include_bodies flag —
        # previously export_json was always called without bodies while
        # export_html alone got the flag, so graph.json stayed empty even
        # when refresh requested bodies.
        payload = export_json(
            index,
            BASE_DIR / "graph.json",
            max_nodes=500,
            include_bodies=include_bodies,
        )
        export_html(
            index,
            BASE_DIR / "graph.html",
            max_nodes=500,
            vault_root=vault_root if include_bodies else None,
            include_bodies=include_bodies,
        )
        payload.setdefault("meta", {})["index_rebuilt_notes"] = rebuilt
        payload.setdefault("meta", {})["include_bodies"] = include_bodies
        return payload
    finally:
        index.close()


def _note_payload(note_id: str) -> dict:
    """Load one note's metadata + body for the modal (lazy fetch)."""
    note_id = unquote(note_id).strip()
    if not note_id:
        raise HTTPException(status_code=400, detail="note_id required")

    index = VaultIndex(INDEX_DB)
    try:
        row = index.db.execute(
            """SELECT m.note_id, m.title, m.domain, m.note_type, m.importance,
                      m.tags, m.path, m.body_preview, f.body AS full_body
               FROM notes_meta m
               LEFT JOIN notes_fts f ON f.note_id = m.note_id
               WHERE m.note_id = ?""",
            (note_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"note not found: {note_id}")

        d = dict(row)
        body = (d.get("full_body") or d.get("body_preview") or "").strip()

        # Fallback: read live vault file when FTS/preview empty
        if not body and d.get("path"):
            try:
                vault = Vault(_vault_root())
                note = vault.read_note(d["path"])
                body = note.body or ""
            except Exception:
                body = ""

        tags = d.get("tags") or ""
        if isinstance(tags, str) and tags:
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        elif not isinstance(tags, list):
            tags = []

        return {
            "id": d["note_id"],
            "title": d.get("title") or d["note_id"],
            "domain": d.get("domain") or "",
            "type": d.get("note_type") or "permanent",
            "importance": d.get("importance") or 0.3,
            "tags": tags,
            "path": d.get("path") or "",
            "body_preview": (d.get("body_preview") or "")[:400],
            "full_body": body,
        }
    finally:
        index.close()


@app.get("/health")
def health():
    return {"ok": True, "bind_policy": "tailscale+local"}


@app.post("/refresh")
def refresh(
    x_entropicmem_token: str | None = Header(default=None),
    include_bodies: bool = True,
):
    """Regenerate graph.html/json. Bodies ON by default for the local viewer.

    Pass ?include_bodies=false for a content-free export (shareable shell).
    """
    _require_token(x_entropicmem_token)
    payload = _regenerate(include_bodies=include_bodies)
    return JSONResponse({
        "status": "refreshed",
        "include_bodies": include_bodies,
        "generated": payload.get("meta", {}).get("generated"),
        "node_count": payload.get("meta", {}).get("node_count"),
        "edge_count": payload.get("meta", {}).get("edge_count"),
        "domains": payload.get("meta", {}).get("domains"),
    })


@app.get("/api/note/{note_id:path}")
def get_note(note_id: str):
    """Lazy-load one note's markdown for the graph modal.

    Used when the embedded graph export omitted bodies (security default)
    or when the user opens a node whose body was not inlined. No token
    required: the graph server is bind-restricted (127.0.0.1 / Tailscale)
    and this is the same trust plane as serving graph.html itself.
    """
    return JSONResponse(_note_payload(note_id))


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = BASE_DIR / "graph.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="graph.html missing - run authenticated refresh")
    html = html_path.read_text(encoding="utf-8")
    if "<title>EntropicMem" in html:
        html = html.replace(
            "<title>EntropicMem — Vault Graph</title>",
            "<title>EntropicMem Graph (local)</title>",
            1,
        )
    return HTMLResponse(html)


@app.get("/graph.json")
def graph_json():
    path = BASE_DIR / "graph.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="graph.json missing")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


# Intentionally no StaticFiles mount at "/". graph.html is self-contained
# (D3 from CDN) and both artifacts are served by the explicit routes above.
# Mounting StaticFiles at "/" risks catching requests that should hit the
# API routes depending on Starlette route-matching order.
