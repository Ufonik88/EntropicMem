"""EntropicMem graph server — serves graph.html/graph.json + vault note APIs.

``entropicmem graph serve`` requires fastapi and uvicorn (both optional; not
part of the core EntropicMem install).
"""
from __future__ import annotations

import hmac
import json

# Canonical source for the graph server. Deployed (symlink-free) copy runs
# from ~/.hermes/entropicmem/graph_server/server.py under the systemd user
# unit entropicmem-graph-server.service. This repo file is the single source
# of truth — the deployed copy must be synced from here (the operator handles
# the deploy step and unit restart).
#
# Bind policy: the read endpoints below serve full vault content, so serving
# on a non-loopback bind is refused at startup unless
# ENTROPICMEM_GRAPH_EXPOSE=1 explicitly opts in; whenever the process is not
# loopback-bound, the body-bearing read endpoints require the same token as
# /refresh (loopback stays tokenless — the local trust plane).
#
# EM-114 request hardening (every route except /health):
#   * Host allowlist — the Host header must name a loopback host (or, with
#     ENTROPICMEM_GRAPH_EXPOSE=1, a bind host / ENTROPICMEM_GRAPH_ALLOWED_HOSTS
#     entry) on the port this server actually listens on. Defeats DNS
#     rebinding against the tokenless loopback trust plane.
#   * Content-Security-Policy + nosniff/no-referrer on every response.
#   * Token: ENTROPICMEM_GRAPH_TOKEN when set, otherwise a random per-run
#     token written (0600) to HERMES_HOME/entropicmem/graph_server.token at
#     startup, so /refresh works without a static secret yet a browser page
#     can never obtain it.
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
import secrets
import sqlite3
import sys
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

HERE = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def _resolve_scripts_dir() -> Path:
    override = os.environ.get("ENTROPICMEM_SCRIPTS_DIR")
    if override:
        return Path(override)
    candidates = [
        HERMES_HOME / "plugins" / "entropicmem" / "scripts",
        # Repo checkout layout: <repo>/scripts/graph_server/server.py
        HERE.parents[1] / "plugins" / "entropicmem" / "scripts",
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
        and (path / "plugins" / "entropicmem" / "scripts").is_dir()
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
    skills_scripts = HERMES_HOME / "plugins" / "entropicmem" / "scripts"
    if skills_scripts.exists():
        # <repo>/plugins/entropicmem/scripts → parents[2] = <repo>
        repo_via_skills = skills_scripts.resolve().parent.parent.parent
        if _looks_like_repo_root(repo_via_skills):
            return repo_via_skills / "graph_export"

    return HERMES_HOME / "entropicmem" / "graph_export"


SCRIPTS_DIR = _resolve_scripts_dir()
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from graph_export import export_html, export_json, resolve_note_path  # noqa: E402
from index import VaultIndex, build_fts_query  # noqa: E402
from vault import Vault, resolve_vault_path  # noqa: E402

BASE_DIR = _resolve_export_dir()
# Hard-pin data paths under HERMES_HOME (do not trust ENTROPICMEM_* env).
INDEX_DB = HERMES_HOME / "entropicmem" / "index.db"
DEFAULT_VAULT = HERMES_HOME / "entropicmem" / "vault"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup/shutdown lifecycle (replaces the deprecated @app.on_event).

    Startup refuses a non-loopback bind without the explicit override and
    publishes the per-run token file; shutdown removes that file. Behaviour
    is identical to the former on_event hooks (pinned by
    tests/test_graph_server_security.py).
    """
    _enforce_bind_policy()
    _write_run_token_file()
    try:
        yield
    finally:
        _remove_run_token_file()


app = FastAPI(title="EntropicMem Graph", lifespan=_lifespan)

# Random per-run token (EM-114): the credential whenever no static
# ENTROPICMEM_GRAPH_TOKEN is configured. New on every process start.
RUN_TOKEN = secrets.token_urlsafe(32)
RUN_TOKEN_FILE = HERMES_HOME / "entropicmem" / "graph_server.token"


def _env_token() -> str:
    return (os.environ.get("ENTROPICMEM_GRAPH_TOKEN") or "").strip()


def _refresh_token() -> str:
    """The one accepted token: the configured static one, else the per-run one."""
    return _env_token() or RUN_TOKEN


def _require_token(x_entropicmem_token: str | None) -> None:
    provided = (x_entropicmem_token or "").strip()
    if not provided and not _env_token():
        # No static token configured: only the per-run token opens this.
        raise HTTPException(
            status_code=403,
            detail=(
                "Token required: send X-EntropicMem-Token with the per-run token "
                "from HERMES_HOME/entropicmem/graph_server.token, or set "
                "ENTROPICMEM_GRAPH_TOKEN"
            ),
        )
    if not provided or not hmac.compare_digest(
        provided.encode(), _refresh_token().encode()
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing token")


def _write_run_token_file() -> None:
    """Publish the per-run token to its owner-only file (only when it is the
    active credential); drop a stale file when a static token is configured."""
    if _env_token():
        _remove_run_token_file(force=True)
        return
    RUN_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUN_TOKEN_FILE.with_name(RUN_TOKEN_FILE.name + ".tmp")
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(RUN_TOKEN + "\n")
    os.replace(tmp, RUN_TOKEN_FILE)


def _remove_run_token_file(*, force: bool = False) -> None:
    """Remove the token file if it still holds this run's token (or always)."""
    try:
        if force or RUN_TOKEN_FILE.read_text(encoding="ascii").strip() == RUN_TOKEN:
            RUN_TOKEN_FILE.unlink()
    except (FileNotFoundError, OSError):
        pass


# ── bind policy (enforces the loopback-only claim) ──────────────────────────

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    return h in _LOOPBACK_HOSTS or h.startswith("127.")


def _proc_addr_to_host(addr: str) -> str:
    """Map a /proc/net/tcp{,6} local_address field to a host string."""
    ip_hex = addr.split(":", 1)[0]
    if len(ip_hex) == 8:  # IPv4 (little-endian 32-bit word in /proc)
        return ".".join(str(b) for b in bytes.fromhex(ip_hex)[::-1])
    if ip_hex == "0" * 32:
        return "::"          # IPv6 wildcard (dual-stack when v6only=0)
    if ip_hex == "0" * 31 + "1":
        return "::1"
    if ip_hex[-8:] == "0100007F" and set(ip_hex[:-8]) <= {"0", "F"}:
        return "127.0.0.1"   # v4-mapped 127.0.0.1
    return "ipv6:" + ip_hex  # anything else counts as non-loopback


def _proc_listen_hosts() -> set | None:
    """Local addresses of this process's LISTEN sockets, via /proc (Linux).

    None when /proc is unavailable (non-Linux); an empty set means the
    process currently holds no listening sockets.
    """
    try:
        fds = os.listdir("/proc/self/fd")
    except OSError:
        return None
    inodes = set()
    for fd in fds:
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inodes.add(target[len("socket:["): -1])
    hosts: set = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            # 4th field is the socket state (0A = LISTEN), 10th the inode.
            if len(fields) < 10 or fields[3] != "0A" or fields[9] not in inodes:
                continue
            hosts.add(_proc_addr_to_host(fields[1]))
    return hosts


def _argv_bind_hosts() -> set:
    """uvicorn's --host value(s) from the command line (portable fallback)."""
    hosts = set()
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg.startswith("--host="):
            hosts.add(arg.split("=", 1)[1].strip())
        elif arg == "--host" and i + 1 < len(argv):
            hosts.add(argv[i + 1].strip())
    return {h for h in hosts if h}


def _bind_hosts() -> set | None:
    """Best-effort bind addresses for this server process.

    Precedence: ENTROPICMEM_GRAPH_BIND (explicit override, authoritative —
    for setups where /proc and argv give no signal), then this process's
    /proc LISTEN sockets, then uvicorn's --host argument. None means no
    signal at all.
    """
    env = (os.environ.get("ENTROPICMEM_GRAPH_BIND") or "").strip()
    if env:
        return {h.strip() for h in env.split(",") if h.strip()}
    hosts: set = set()
    seen = False
    proc = _proc_listen_hosts()
    if proc is not None:
        hosts |= proc
        seen = True
    argv_hosts = _argv_bind_hosts()
    if argv_hosts:
        hosts |= argv_hosts
        seen = True
    return hosts if seen else None


def _bind_is_loopback() -> bool:
    """True while every detected bind address is loopback.

    Nothing detected counts as loopback (the local trust plane): the process
    holds no serving socket yet (tests, pre-bind import).
    """
    hosts = _bind_hosts()
    if not hosts:
        return True
    return all(_is_loopback_host(h) for h in hosts)


def _expose_override() -> bool:
    """Explicit opt-in to serve on a non-loopback bind."""
    return os.environ.get("ENTROPICMEM_GRAPH_EXPOSE", "").strip() == "1"


def _token_required() -> bool:
    """Read endpoints need the token whenever the bind is not loopback-only."""
    return not _bind_is_loopback()


def _require_token_if_exposed(x_entropicmem_token: str | None) -> None:
    """Gate a read endpoint: tokenless on the loopback trust plane, the same
    constant-time ENTROPICMEM_GRAPH_TOKEN check as /refresh otherwise."""
    if _token_required():
        _require_token(x_entropicmem_token)


# ── Host allowlist (DNS-rebinding guard) ────────────────────────────────────

_WILDCARD_HOSTS = {"0.0.0.0", "::", "*", ""}


def _norm_host(host: str) -> str:
    return (host or "").strip().lower().strip("[]")


def _allowed_host_names() -> set:
    """Host-header names this server answers to.

    Loopback names always (plus any loopback bind address). Non-loopback
    names only when ENTROPICMEM_GRAPH_EXPOSE=1: the concrete bind hosts and
    ENTROPICMEM_GRAPH_ALLOWED_HOSTS (comma-separated; needed for a wildcard
    bind, whose address no client sends). Wildcards are never allowed.
    """
    names = {"127.0.0.1", "localhost", "::1"}
    binds = {_norm_host(h) for h in (_bind_hosts() or set())}
    names |= {h for h in binds if _is_loopback_host(h)}
    if _expose_override():
        names |= binds
        extra = os.environ.get("ENTROPICMEM_GRAPH_ALLOWED_HOSTS") or ""
        names |= {_norm_host(h) for h in extra.split(",")}
    return names - _WILDCARD_HOSTS


def _split_host_header(value: str) -> tuple[str, int | None] | None:
    """(hostname, port) from a Host header; None if malformed."""
    value = (value or "").strip()
    if not value:
        return None
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            return None
        host, rest = value[1:end], value[end + 1:]
        if rest and not rest.startswith(":"):
            return None
        port_s = rest[1:] if rest else ""
    elif value.count(":") == 1:
        host, port_s = value.split(":", 1)
    elif ":" in value:
        return None  # bare IPv6 must be bracketed
    else:
        host, port_s = value, ""
    if port_s and not port_s.isdigit():
        return None
    return _norm_host(host), (int(port_s) if port_s else None)


def _host_allowed(host_header: str, server: tuple | None) -> bool:
    """True if the Host header names an allowed host on the actual port.

    ``server`` is the ASGI scope's (host, port) of the listening socket. A
    Host without a port means :80. When the listening port is unknown (e.g. a
    unix socket) only the hostname is checked.
    """
    parsed = _split_host_header(host_header)
    if parsed is None:
        return False
    name, port = parsed
    if name not in _allowed_host_names():
        return False
    actual_port = server[1] if server and len(server) > 1 else None
    if actual_port is None:
        return True
    return (port if port is not None else 80) == actual_port


# ── security headers ────────────────────────────────────────────────────────

# graph.html loads D3 (d3js.org), marked (jsdelivr) and Google Fonts, runs
# inline script/style, and fetches only its own origin. connect-src 'self'
# keeps vault content from being sent anywhere else; img-src excludes remote
# images so rendered markdown cannot beacon out.
CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://d3js.org https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@app.middleware("http")
async def _request_hardening(request: Request, call_next):
    """Host allowlist on every route but /health, then security headers on
    every response (errors included).

    The path and Host are read from the raw ASGI scope: ``request.url`` parses
    the Host header, and Starlette < 1.7 raises ``ValueError("Invalid IPv6
    URL")`` there for a malformed bracketed host (``[::1``) before the
    allowlist ever runs, turning a client error into a 500. Scope reads never
    parse, so the allowlist sees every malformed header and answers 400; the
    ``call_next`` guard keeps the same fail-closed answer if any downstream
    layer still parses the header.
    """
    try:
        host_ok = request.scope.get("path") == "/health" or _host_allowed(
            request.headers.get("host", ""), request.scope.get("server")
        )
    except ValueError:
        host_ok = False
    if not host_ok:
        response = JSONResponse({"detail": "invalid Host header"}, status_code=400)
    else:
        try:
            response = await call_next(request)
        except ValueError:
            response = JSONResponse({"detail": "invalid Host header"}, status_code=400)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


def _enforce_bind_policy() -> None:
    """Startup gate: refuse a non-loopback bind without the explicit override.

    Every read endpoint serves full vault content, so the loopback-only claim
    is enforced here, not just documented. Raises RuntimeError so uvicorn
    aborts startup.
    """
    if _bind_is_loopback() or _expose_override():
        return
    hosts = ", ".join(sorted(_bind_hosts() or [])) or "unknown"
    raise RuntimeError(
        "EntropicMem graph server refuses a non-loopback bind (" + hosts +
        "): the read endpoints expose full vault content. Bind 127.0.0.1, or "
        "set ENTROPICMEM_GRAPH_EXPOSE=1 to accept the exposure (read endpoints "
        "then require ENTROPICMEM_GRAPH_TOKEN)."
    )


def _vault_root() -> Path:
    vault_root = DEFAULT_VAULT
    if not vault_root.is_dir():
        vault_root = Path(resolve_vault_path())
    return vault_root


def _lean_mode() -> bool:
    """True only when ENTROPICMEM_GRAPH_LEAN explicitly enables body-less exports.

    Local viewer bodies are hard-pinned ON. The only way to drop them is
    setting ENTROPICMEM_GRAPH_LEAN=1|true|yes — a deliberate ops choice, not
    a query-param footgun that can silently empty every modal again.
    """
    return os.environ.get("ENTROPICMEM_GRAPH_LEAN", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _resolve_include_bodies(requested: bool) -> bool:
    """Bodies are always on unless lean mode is explicitly enabled."""
    if _lean_mode():
        return requested
    return True  # hard pin — ignore include_bodies=false from callers


def _regenerate(*, include_bodies: bool = True) -> dict:
    """Rebuild index + export graph.

    Bodies are hard-pinned ON for the local authenticated viewer so node
    modals always show markdown. Lean (body-less) exports require
    ENTROPICMEM_GRAPH_LEAN=1 in the server environment.
    """
    include_bodies = _resolve_include_bodies(include_bodies)
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
        from graph_export import assert_bodies_present  # local import ok

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
        payload.setdefault("meta", {})["lean_mode"] = _lean_mode()
        # Second gate after HTML write (export_json already asserts).
        if include_bodies:
            assert_bodies_present(payload, context="graph-server /refresh")
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
                vault_root = _vault_root()
                vault = Vault(vault_root)
                # resolve_note_path rejects absolute/dot-dot DB rows: a
                # poisoned notes_meta.path must not become an arbitrary read.
                note = vault.read_note(resolve_note_path(vault_root, d["path"]))
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
    """Liveness plus the enforced bind policy (see _enforce_bind_policy)."""
    loopback = _bind_is_loopback()
    if loopback:
        policy = "loopback (tokenless local trust plane)"
    elif _expose_override():
        policy = "non-loopback via ENTROPICMEM_GRAPH_EXPOSE=1 override"
    else:
        policy = "non-loopback without ENTROPICMEM_GRAPH_EXPOSE=1 (refused at startup)"
    if _expose_override() and "ENTROPICMEM_GRAPH_EXPOSE" not in policy:
        policy += "; ENTROPICMEM_GRAPH_EXPOSE=1 set"
    return {
        "ok": True,
        "bind_policy": policy,
        "token_required": not loopback,
        "token_source": "env" if _env_token() else "per-run",
    }


@app.post("/refresh")
def refresh(
    x_entropicmem_token: str | None = Header(default=None),
    include_bodies: bool = True,
):
    """Regenerate graph.html/json.

    Bodies are hard-pinned ON. Query param include_bodies=false is ignored
    unless the server process has ENTROPICMEM_GRAPH_LEAN=1.
    """
    _require_token(x_entropicmem_token)
    effective = _resolve_include_bodies(include_bodies)
    payload = _regenerate(include_bodies=effective)
    cov = (payload.get("meta") or {}).get("body_coverage") or {}
    return JSONResponse({
        "status": "refreshed",
        "include_bodies": effective,
        "requested_include_bodies": include_bodies,
        "lean_mode": _lean_mode(),
        "body_coverage": cov,
        "generated": payload.get("meta", {}).get("generated"),
        "node_count": payload.get("meta", {}).get("node_count"),
        "edge_count": payload.get("meta", {}).get("edge_count"),
        "domains": payload.get("meta", {}).get("domains"),
    })


@app.get("/api/note/by-title/{title:path}")
def get_note_by_title(title: str, x_entropicmem_token: str | None = Header(default=None)):
    """Resolve a wikilink target by title, against the FULL index.

    Graph modals render [[wikilinks]] to notes that are not in the current
    export (the 500-node cap) as dead red links. This endpoint lets the
    client resolve those titles lazily: exact match first (case-
    insensitive), then shortest containing match. Same trust plane and
    response shape as /api/note/{id} (plus a note_id field).

    NOTE: must be registered BEFORE /api/note/{note_id:path} — a path
    converter would otherwise swallow "by-title/..." as a note id.
    """
    _require_token_if_exposed(x_entropicmem_token)
    title = unquote(title).strip()
    if not title:
        raise HTTPException(status_code=400, detail="title required")

    index = VaultIndex(INDEX_DB)
    try:
        row = index.db.execute(
            """SELECT note_id FROM notes_meta WHERE lower(title) = lower(?) LIMIT 1""",
            (title,),
        ).fetchone()
        if not row:
            row = index.db.execute(
                """SELECT note_id FROM notes_meta
                   WHERE instr(lower(title), lower(?)) > 0
                   ORDER BY length(title) ASC LIMIT 1""",
                (title,),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"no note with title: {title}")
        payload = _note_payload(row["note_id"])
        payload["note_id"] = row["note_id"]
        return JSONResponse(payload)
    finally:
        index.close()


@app.get("/api/note/{note_id:path}")
def get_note(note_id: str, x_entropicmem_token: str | None = Header(default=None)):
    """Lazy-load one note's markdown for the graph modal.

    Used when the embedded graph export omitted bodies (security default)
    or when the user opens a node whose body was not inlined. Tokenless only
    on the loopback trust plane: when the process is not loopback-bound the
    same ENTROPICMEM_GRAPH_TOKEN as /refresh is required (body-bearing
    endpoint).
    """
    _require_token_if_exposed(x_entropicmem_token)
    return JSONResponse(_note_payload(note_id))


@app.get("/api/search")
def search_notes(
    q: str = "",
    limit: int = 20,
    x_entropicmem_token: str | None = Header(default=None),
):
    """Full-text search over vault notes (the in-graph search box).

    Vault FTS (notes_fts) is the mandatory path and the contract: the
    embedding runtime is optional, lives outside this process, and is never
    imported here. Result rows carry everything the note modal needs, so
    hits outside the 500-node export open through the existing lazy
    /api/note/{id} fetch. Tokenless only on the loopback trust plane (snippets
    are vault content): a non-loopback bind requires ENTROPICMEM_GRAPH_TOKEN.
    A query that sanitizes to an empty FTS expression is a clean 400.
    """
    _require_token_if_exposed(x_entropicmem_token)
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="q required")
    if not build_fts_query(query, fields=("title", "tags", "body")):
        # The query sanitizes to an empty MATCH expression (e.g. a lone NUL
        # byte or quote): a clean 400, never a 500 and never a silent
        # 200-empty that looks like "no matches".
        raise HTTPException(status_code=400, detail="invalid search query")
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 20

    index = VaultIndex(INDEX_DB)
    try:
        try:
            hits = index.search_fts(query, top_k=limit)
        except sqlite3.OperationalError:
            # FTS5 rejected the sanitized query (e.g. a lone quote collapses
            # to an empty phrase): a clean 400, never a 500.
            raise HTTPException(status_code=400, detail="invalid search query")
        return JSONResponse({
            "query": query,
            "mode": "fts",
            "results": [
                {
                    "note_id": h.note_id,
                    "title": h.title,
                    "domain": h.domain,
                    "type": h.note_type,
                    "importance": h.importance,
                    "tags": h.tags,
                    "snippet": h.snippet,
                }
                for h in hits
            ],
        })
    finally:
        index.close()


@app.get("/api/path")
def shortest_path(
    from_: str = Query(default="", alias="from"),
    to: str = Query(default=""),
    max_depth: int = Query(default=10),
    x_entropicmem_token: str | None = Header(default=None),
):
    """Shortest path between two notes over the undirected graph_edges set.

    BFS with the established triple_path pattern: collections.deque +
    popleft(), and the depth check happens BEFORE a neighbor is enqueued so
    the search is genuinely bounded (the two Sourcery-caught bugs there must
    not be reintroduced here). Tokenless only on the loopback trust plane:
    the response echoes vault note ids, so a non-loopback bind requires the
    same ENTROPICMEM_GRAPH_TOKEN as the body-bearing reads.
    """
    _require_token_if_exposed(x_entropicmem_token)
    start = (from_ or "").strip()
    goal = (to or "").strip()
    if not start or not goal:
        raise HTTPException(status_code=400, detail="from and to required")
    try:
        max_depth = max(1, min(int(max_depth), 30))
    except (TypeError, ValueError):
        max_depth = 10

    index = VaultIndex(INDEX_DB)
    try:
        adjacency: dict[str, list[str]] = {}
        for source, target in index.db.execute(
            "SELECT source_id, target_id FROM graph_edges ORDER BY id"
        ).fetchall():
            adjacency.setdefault(source, []).append(target)
            adjacency.setdefault(target, []).append(source)

        found_path: list[str] | None = None
        if start == goal:
            found_path = [start] if start in adjacency else None
        else:
            seen = {start}
            queue: deque = deque([(start, [start])])
            while queue:
                node, path = queue.popleft()
                for neighbor in adjacency.get(node, ()):
                    new_path = path + [neighbor]
                    if len(new_path) - 1 > max_depth:
                        continue  # depth check BEFORE enqueueing
                    if neighbor == goal:
                        found_path = new_path
                        break
                    if neighbor not in seen:
                        seen.add(neighbor)
                        queue.append((neighbor, new_path))
                if found_path:
                    break

        return JSONResponse({
            "from": start,
            "to": goal,
            "found": found_path is not None,
            "path": found_path or [],
            "hops": (len(found_path) - 1) if found_path else None,
            "max_depth": max_depth,
        })
    finally:
        index.close()


@app.get("/", response_class=HTMLResponse)
def index(x_entropicmem_token: str | None = Header(default=None)):
    """Serve graph.html — body-bearing (embeds note bodies), so it is
    tokenless only on the loopback trust plane."""
    _require_token_if_exposed(x_entropicmem_token)
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
def graph_json(x_entropicmem_token: str | None = Header(default=None)):
    """Serve graph.json — body-bearing when the export included bodies, so it
    is tokenless only on the loopback trust plane."""
    _require_token_if_exposed(x_entropicmem_token)
    path = BASE_DIR / "graph.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="graph.json missing")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


# Intentionally no StaticFiles mount at "/". graph.html is self-contained
# (D3 from CDN) and both artifacts are served by the explicit routes above.
# Mounting StaticFiles at "/" risks catching requests that should hit the
# API routes depending on Starlette route-matching order.
