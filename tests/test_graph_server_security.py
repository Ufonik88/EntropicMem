"""
test_graph_server_security.py — Bind-policy, token-enforcement and
path-traversal regression tests for scripts/graph_server/server.py.

The read endpoints serve full vault content. Enforced claims:
  * startup refuses a non-loopback bind unless ENTROPICMEM_GRAPH_EXPOSE=1
  * when the process is not loopback-bound, every read endpoint requires the
    same ENTROPICMEM_GRAPH_TOKEN as /refresh (constant-time compare);
    loopback stays tokenless (local trust plane)
  * a poisoned notes_meta.path row never becomes an arbitrary file read

Uses FastAPI TestClient with monkeypatched module globals (INDEX_DB,
DEFAULT_VAULT, BASE_DIR) so tests are isolated from the shared module import.
"""

import asyncio
import inspect
import os
import sys
from pathlib import Path

import pytest

# The graph server needs fastapi; CI only installs pytest, so skip the
# whole module there rather than failing the lint/test matrix.
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

_SERVER_DIR = Path(__file__).resolve().parent.parent / "scripts" / "graph_server"
_PARENT = _SERVER_DIR.parent
_ENGINE_DIR = Path(__file__).resolve().parent.parent / "plugins" / "entropicmem" / "scripts"

SECRET_MARKER = "SECRET_MARKER_SHOULD_NOT_LEAK"
TOKEN = "sekrit-test-token"


@pytest.fixture
def mod(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPORT_DIR", str(tmp_path / "graph_export"))
    # Deterministic trust plane for every test: loopback unless a test
    # overrides ENTROPICMEM_GRAPH_BIND itself.
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "127.0.0.1")
    monkeypatch.delenv("ENTROPICMEM_GRAPH_EXPOSE", raising=False)
    monkeypatch.delenv("ENTROPICMEM_GRAPH_TOKEN", raising=False)
    sys.path.insert(0, str(_PARENT))
    sys.path.insert(0, str(_ENGINE_DIR))
    import graph_server.server as server_mod
    # Module paths are computed at import (cached across the session):
    # pin them to this test's tmp tree.
    monkeypatch.setattr(server_mod, "INDEX_DB", tmp_path / "index.db")
    monkeypatch.setattr(server_mod, "DEFAULT_VAULT", tmp_path / "vault")
    monkeypatch.setattr(server_mod, "BASE_DIR", tmp_path / "graph_export")
    return server_mod


@pytest.fixture
def client(mod, tmp_path):
    from index import VaultIndex
    from vault import Vault

    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    vault = Vault(vault_root)
    index = VaultIndex(mod.INDEX_DB)
    for domain, title, body in [
        ("Knowledge", "Alpha Note", "Body of Alpha Note."),
        ("Knowledge", "Beta Note", "Body of Beta Note."),
    ]:
        path = vault.write_note(domain, title, body, tags=["t"], domain=domain)
        note = vault.read_note(path)
        index.upsert_note(note)
        index.upsert_edges_for_note(vault, note)
    index.close()

    export_dir = tmp_path / "graph_export"
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "graph.json").write_text(
        '{"nodes": [], "edges": [], "meta": {}}', encoding="utf-8"
    )
    (export_dir / "graph.html").write_text(
        "<html><title>EntropicMem — Vault Graph</title></html>", encoding="utf-8"
    )
    # EM-114 Host allowlist: requests must name a loopback host on the
    # server's actual port (TestClient's default Host 'testserver' is refused).
    return TestClient(mod.app, base_url="http://127.0.0.1:8075")


READ_URLS = [
    "/api/note/Knowledge%2FAlpha%20Note",
    "/api/note/by-title/Alpha%20Note",
    "/api/search?q=Body",
    "/api/path?from=Knowledge/Alpha%20Note&to=Knowledge/Beta%20Note",
    "/graph.json",
    "/",
]


# ── bind policy: startup refuses non-loopback without the override ──────────

def test_bind_policy_refuses_non_loopback_without_override(mod, monkeypatch):
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "0.0.0.0")
    with pytest.raises(RuntimeError, match="ENTROPICMEM_GRAPH_EXPOSE"):
        mod._enforce_bind_policy()


def test_bind_policy_allows_non_loopback_with_expose_override(mod, monkeypatch):
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "0.0.0.0")
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPOSE", "1")
    mod._enforce_bind_policy()  # must not raise


def test_bind_policy_allows_loopback(mod):
    mod._enforce_bind_policy()  # fixture binds 127.0.0.1 — must not raise


def test_startup_hook_is_wired_to_the_bind_guard(mod, monkeypatch):
    """The refusal must fire from the ASGI startup lifecycle, not just from a
    helper nobody calls."""
    handlers = list(mod.app.router.on_startup)
    assert handlers, "no startup handler registered on the app"
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "0.0.0.0")
    with pytest.raises(RuntimeError, match="ENTROPICMEM_GRAPH_EXPOSE"):
        for handler in handlers:
            result = handler()
            if inspect.isawaitable(result):
                asyncio.run(result)


def test_bind_detection_helpers(mod):
    assert mod._is_loopback_host("127.0.0.1")
    assert mod._is_loopback_host("::1")
    assert mod._is_loopback_host("localhost")
    assert not mod._is_loopback_host("0.0.0.0")
    assert not mod._is_loopback_host("::")
    assert not mod._is_loopback_host("192.168.1.5")
    assert mod._proc_addr_to_host("0100007F:1F8B") == "127.0.0.1"
    assert mod._proc_addr_to_host("00000000:1F8B") == "0.0.0.0"
    assert mod._proc_addr_to_host("00000000000000000000000000000000:1F8B") == "::"
    assert mod._proc_addr_to_host("00000000000000000000000000000001:1F8B") == "::1"


def test_argv_bind_detection(mod, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["uvicorn", "mod:app", "--host", "0.0.0.0", "--port", "8075"])
    assert mod._argv_bind_hosts() == {"0.0.0.0"}
    monkeypatch.setattr(sys, "argv", ["uvicorn", "mod:app", "--host=127.0.0.1"])
    assert mod._argv_bind_hosts() == {"127.0.0.1"}


# ── /health reports the enforced policy ─────────────────────────────────────

def test_health_reports_loopback_policy(client):
    d = client.get("/health").json()
    assert d["ok"] is True
    assert "loopback" in d["bind_policy"]
    assert d["token_required"] is False


def test_health_reports_expose_override(client, monkeypatch):
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "0.0.0.0")
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPOSE", "1")
    d = client.get("/health").json()
    assert "ENTROPICMEM_GRAPH_EXPOSE" in d["bind_policy"], \
        "the override must be reported in bind_policy"
    assert d["token_required"] is True


# ── token enforcement on read endpoints ─────────────────────────────────────

def test_read_endpoints_tokenless_on_loopback(client):
    for url in READ_URLS:
        r = client.get(url)
        assert r.status_code not in (401, 403), f"{url} demanded a token on loopback"
    assert client.get("/api/search?q=Body").status_code == 200
    assert client.get("/graph.json").status_code == 200


def test_read_endpoints_require_token_when_not_loopback(client, monkeypatch):
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "0.0.0.0")
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPOSE", "1")
    monkeypatch.setenv("ENTROPICMEM_GRAPH_TOKEN", TOKEN)
    for url in READ_URLS:
        assert client.get(url).status_code == 401, f"{url} served without a token"
        r = client.get(url, headers={"x-entropicmem-token": "wrong"})
        assert r.status_code == 401, f"{url} accepted a wrong token"
        r = client.get(url, headers={"x-entropicmem-token": TOKEN})
        assert r.status_code not in (401, 403), f"{url} rejected the valid token"


def test_read_endpoints_403_when_exposed_without_token_configured(client, monkeypatch):
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "0.0.0.0")
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPOSE", "1")
    for url in READ_URLS:
        assert client.get(url).status_code == 403, \
            f"{url} served while exposed with no token configured"


def test_health_stays_open_when_exposed(client, monkeypatch):
    """Probes must work without the token; /health carries no vault content."""
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "0.0.0.0")
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPOSE", "1")
    monkeypatch.setenv("ENTROPICMEM_GRAPH_TOKEN", TOKEN)
    assert client.get("/health").status_code == 200


def test_refresh_keeps_requiring_token_on_loopback(mod, client, monkeypatch):
    # /refresh always requires the token — even on the loopback trust plane.
    assert client.post("/refresh").status_code == 403  # no token configured
    monkeypatch.setenv("ENTROPICMEM_GRAPH_TOKEN", TOKEN)
    assert client.post("/refresh").status_code == 401  # no header
    assert client.post(
        "/refresh", headers={"x-entropicmem-token": "wrong"}
    ).status_code == 401
    r = client.post("/refresh", headers={"x-entropicmem-token": TOKEN})
    assert r.status_code == 200
    assert r.json()["status"] == "refreshed"


# ── poisoned notes_meta.path must not become an arbitrary file read ─────────

@pytest.mark.parametrize("poison_kind", ["absolute", "dotdot"])
def test_poisoned_note_path_is_not_read(mod, client, tmp_path, poison_kind):
    from index import VaultIndex

    secret = tmp_path / "secret.md"
    secret.write_text(SECRET_MARKER, encoding="utf-8")
    poison = str(secret) if poison_kind == "absolute" else f"../{secret.name}"

    index = VaultIndex(mod.INDEX_DB)
    # Empty the indexed bodies so the /api/note vault-read fallback fires,
    # then poison the path column.
    index.db.execute(
        "UPDATE notes_meta SET path = ?, body_preview = '' WHERE note_id = ?",
        (poison, "Knowledge/Alpha Note"),
    )
    index.db.execute(
        "DELETE FROM notes_fts WHERE note_id = ?", ("Knowledge/Alpha Note",)
    )
    index.db.commit()
    index.close()

    r = client.get("/api/note/Knowledge%2FAlpha%20Note")
    assert r.status_code == 200
    d = r.json()
    assert SECRET_MARKER not in r.text, \
        f"poisoned notes_meta.path ({poison}) leaked an outside file"
    assert d["full_body"] == ""


# ── EM-114: Host allowlist (DNS-rebinding guard) ────────────────────────────

def _get(client, url, host, **headers):
    return client.get(url, headers={"host": host, **headers})


@pytest.mark.parametrize("host", ["127.0.0.1:8075", "localhost:8075", "[::1]:8075",
                                  "LOCALHOST:8075"])
def test_host_allowlist_accepts_loopback_names_on_actual_port(client, host):
    r = _get(client, "/graph.json", host)
    assert r.status_code == 200, (host, r.text)


@pytest.mark.parametrize("host", [
    "evil.example:8075",   # DNS rebinding: attacker name resolved to 127.0.0.1
    "127.0.0.1:9999",      # right name, wrong port
    "127.0.0.1",           # no port means :80, not the listening port
    "0.0.0.0:8075",        # wildcard is never a valid Host
    "127.0.0.1:8075:1",    # malformed
    "[::1",                # malformed bracket
    "",                    # missing
])
def test_host_allowlist_rejects_other_hosts(client, host):
    r = _get(client, "/api/note/Knowledge%2FAlpha%20Note", host)
    assert r.status_code == 400, (host, r.status_code)
    assert "Body of Alpha" not in r.text
    assert r.json() == {"detail": "invalid Host header"}


def test_host_allowlist_uses_the_actual_listening_port(mod, client):
    """The port comes from the listening socket, not a constant: a server on
    :8080 accepts 127.0.0.1:8080 and refuses :8075."""
    other = TestClient(mod.app, base_url="http://127.0.0.1:8080")
    assert other.get("/graph.json").status_code == 200
    assert _get(other, "/graph.json", "127.0.0.1:8075").status_code == 400


def test_host_allowlist_runs_before_token_check(client, monkeypatch):
    """A rebinding page never gets as far as the token gate."""
    monkeypatch.setenv("ENTROPICMEM_GRAPH_TOKEN", TOKEN)
    r = client.post("/refresh", headers={"host": "evil.example:8075",
                                         "x-entropicmem-token": TOKEN})
    assert r.status_code == 400


def test_health_is_exempt_from_host_allowlist(client):
    r = _get(client, "/health", "evil.example:8075")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_exposed_bind_host_is_allowed_only_with_expose(client, monkeypatch):
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "192.0.2.10")
    monkeypatch.setenv("ENTROPICMEM_GRAPH_TOKEN", TOKEN)
    hdr = {"x-entropicmem-token": TOKEN}
    assert _get(client, "/graph.json", "192.0.2.10:8075", **hdr).status_code == 400
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPOSE", "1")
    assert _get(client, "/graph.json", "192.0.2.10:8075", **hdr).status_code == 200
    assert _get(client, "/graph.json", "192.0.2.10:9999", **hdr).status_code == 400
    assert _get(client, "/graph.json", "evil.example:8075", **hdr).status_code == 400


def test_wildcard_bind_needs_explicit_allowed_hosts(client, monkeypatch):
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "0.0.0.0")
    monkeypatch.setenv("ENTROPICMEM_GRAPH_TOKEN", TOKEN)
    monkeypatch.setenv("ENTROPICMEM_GRAPH_ALLOWED_HOSTS", "graph.example.org, 192.0.2.10")
    hdr = {"x-entropicmem-token": TOKEN}
    # Without the exposure opt-in the extra names are ignored.
    assert _get(client, "/graph.json", "graph.example.org:8075", **hdr).status_code == 400
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPOSE", "1")
    assert _get(client, "/graph.json", "graph.example.org:8075", **hdr).status_code == 200
    assert _get(client, "/graph.json", "192.0.2.10:8075", **hdr).status_code == 200
    assert _get(client, "/graph.json", "0.0.0.0:8075", **hdr).status_code == 400


def test_host_header_parsing(mod):
    assert mod._split_host_header("127.0.0.1:8075") == ("127.0.0.1", 8075)
    assert mod._split_host_header("[::1]:8075") == ("::1", 8075)
    assert mod._split_host_header("[::1]") == ("::1", None)
    assert mod._split_host_header("Localhost") == ("localhost", None)
    for bad in ("", "::1", "[::1]x", "host:port", "a:1:2"):
        assert mod._split_host_header(bad) is None, bad
    # Unknown listening port (unix socket): hostname-only check.
    assert mod._host_allowed("localhost:1234", None)
    assert not mod._host_allowed("evil.example", None)


# ── EM-114: CSP and security headers ────────────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("/", 200), ("/graph.json", 200), ("/api/note/Knowledge%2FAlpha%20Note", 200),
    ("/api/note/missing", 404), ("/health", 200),
])
def test_security_headers_on_every_response(client, url, expected):
    r = client.get(url)
    assert r.status_code == expected
    csp = r.headers.get("content-security-policy", "")
    for directive in ("default-src 'none'", "connect-src 'self'",
                      "frame-ancestors 'none'", "object-src 'none'", "base-uri 'none'"):
        assert directive in csp, (url, directive, csp)
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("referrer-policy") == "no-referrer"


def test_security_headers_on_rejected_host(client):
    r = _get(client, "/", "evil.example:8075")
    assert r.status_code == 400
    assert "default-src 'none'" in r.headers.get("content-security-policy", "")


def test_csp_allows_the_graph_page_dependencies(mod):
    """The CSP must not break graph.html: every external origin the page
    loads is allowed for its resource type, and nothing else."""
    src = (_ENGINE_DIR / "graph_export.py").read_text(encoding="utf-8")
    csp = {d.split()[0]: d.split()[1:] for d in mod.CSP.split("; ")}
    assert 'src="https://d3js.org/' in src and "https://d3js.org" in csp["script-src"]
    assert 'src="https://cdn.jsdelivr.net/' in src and "https://cdn.jsdelivr.net" in csp["script-src"]
    assert "https://fonts.googleapis.com/css2" in src and "https://fonts.googleapis.com" in csp["style-src"]
    assert "https://fonts.gstatic.com" in csp["font-src"]
    assert "data:image/svg+xml" in src and "data:" in csp["img-src"]  # PNG export
    assert csp["connect-src"] == ["'self'"]


# ── EM-114: random per-run token ────────────────────────────────────────────

def test_run_token_is_random_per_process():
    import subprocess

    code = (
        "import sys; sys.path[:0] = [%r, %r]; "
        "import graph_server.server as m; print(m.RUN_TOKEN)"
    ) % (str(_PARENT), str(_ENGINE_DIR))
    tokens = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       check=True).stdout.strip()
        for _ in range(2)
    }
    assert len(tokens) == 2, "RUN_TOKEN repeated across process starts"
    assert all(len(t) >= 43 for t in tokens), tokens  # >= 256 bits, urlsafe


def test_refresh_accepts_run_token_on_loopback_without_static_token(mod, client):
    assert client.post("/refresh").status_code == 403
    assert client.post("/refresh", headers={"x-entropicmem-token": "wrong"}).status_code == 401
    r = client.post("/refresh", headers={"x-entropicmem-token": mod.RUN_TOKEN})
    assert r.status_code == 200 and r.json()["status"] == "refreshed"


def test_static_token_replaces_run_token(mod, client, monkeypatch):
    monkeypatch.setenv("ENTROPICMEM_GRAPH_TOKEN", TOKEN)
    assert client.post("/refresh", headers={"x-entropicmem-token": mod.RUN_TOKEN}).status_code == 401
    assert client.post("/refresh", headers={"x-entropicmem-token": TOKEN}).status_code == 200


def test_exposed_reads_accept_run_token(mod, client, monkeypatch):
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "0.0.0.0")
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPOSE", "1")
    for url in READ_URLS:
        assert client.get(url).status_code == 403, url
        assert client.get(url, headers={"x-entropicmem-token": "wrong"}).status_code == 401, url
        r = client.get(url, headers={"x-entropicmem-token": mod.RUN_TOKEN})
        assert r.status_code not in (401, 403), url


def test_health_reports_token_source(client, monkeypatch):
    assert client.get("/health").json()["token_source"] == "per-run"
    monkeypatch.setenv("ENTROPICMEM_GRAPH_TOKEN", TOKEN)
    assert client.get("/health").json()["token_source"] == "env"


def _run_lifecycle(mod, event):
    for handler in getattr(mod.app.router, f"on_{event}"):
        result = handler()
        if inspect.isawaitable(result):
            asyncio.run(result)


def test_startup_publishes_run_token_owner_only(mod, tmp_path, monkeypatch):
    import stat

    token_file = tmp_path / "entropicmem" / "graph_server.token"
    monkeypatch.setattr(mod, "RUN_TOKEN_FILE", token_file)
    _run_lifecycle(mod, "startup")
    assert token_file.read_text(encoding="ascii").strip() == mod.RUN_TOKEN
    if os.name == "posix":
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    _run_lifecycle(mod, "shutdown")
    assert not token_file.exists(), "per-run token file left behind after shutdown"


def test_startup_drops_run_token_file_when_static_token_set(mod, tmp_path, monkeypatch):
    token_file = tmp_path / "entropicmem" / "graph_server.token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("stale\n", encoding="ascii")
    monkeypatch.setattr(mod, "RUN_TOKEN_FILE", token_file)
    monkeypatch.setenv("ENTROPICMEM_GRAPH_TOKEN", TOKEN)
    _run_lifecycle(mod, "startup")
    assert not token_file.exists()
