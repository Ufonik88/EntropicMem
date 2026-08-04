from __future__ import annotations

# Canonical source for the graph server. Deployed (symlink-free) copy runs
# from ~/.hermes/entropicmem/graph_server/server.py under the systemd user
# unit entropicmem-graph-server.service. Keep both copies identical; after
# editing here, sync the deployed copy and restart the unit.

import os
import sys
import json
import hmac
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, "/home/ufonik/Documents/Coding Projects/EntropicMem/skills/entropicmem/scripts")

from graph_export import export_json, export_html
from index import VaultIndex
from vault import Vault, resolve_vault_path

BASE_DIR = Path("/home/ufonik/Documents/Coding Projects/EntropicMem/graph_export")
INDEX_DB = Path.home() / ".hermes" / "entropicmem" / "index.db"
DEFAULT_VAULT = Path.home() / ".hermes" / "entropicmem" / "vault"

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


def _regenerate(*, include_bodies: bool = False) -> dict:
    vault_root = Path(os.environ.get("ENTROPICMEM_VAULT_PATH") or DEFAULT_VAULT)
    if not vault_root.is_dir():
        vault_root = Path(resolve_vault_path())
    index = VaultIndex(INDEX_DB)
    try:
        # v2.1.8: rebuild the index from the vault before exporting.
        # Notes written outside the remember() path (wiki.py, Obsidian,
        # vault auto-commit) never reach index.db on their own, so the
        # exported graph would silently go stale. rebuild() reindexes every
        # note and the wikilink graph edges.
        vault = Vault(vault_root)
        rebuilt = index.rebuild(vault)
        payload = export_json(index, BASE_DIR / "graph.json", max_nodes=500)
        export_html(
            index,
            BASE_DIR / "graph.html",
            max_nodes=500,
            vault_root=vault_root if include_bodies else None,
            include_bodies=include_bodies,
        )
        payload.setdefault("meta", {})["index_rebuilt_notes"] = rebuilt
        return payload
    finally:
        index.close()


@app.get("/health")
def health():
    return {"ok": True, "bind_policy": "tailscale+local"}


@app.post("/refresh")
def refresh(
    x_entropicmem_token: str | None = Header(default=None),
    include_bodies: bool = False,
):
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


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = BASE_DIR / "graph.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="graph.html missing — run authenticated refresh")
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


app.mount("/", StaticFiles(directory=str(BASE_DIR), html=False), name="static")
