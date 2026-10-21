"""EM-606 — graph server hardening, round 2.

The card's four clauses, and what each one means here:

* **read-only database opens** — every read path opens ``index.db`` with a
  ``mode=ro`` URI, so a GET can never create, migrate or WAL-write the file;
  ``/refresh`` stays the one authenticated writer because rebuilding the index
  is its job, and that exception is pinned deliberately;
* **a 10 rps token bucket on ``/api/search``** — the one endpoint that runs an
  FTS query per request;
* **sensitivity redaction** — a note whose domain tier is ``sensitive`` (the
  policy's own domain map: Finance / People / Events) is served as a summary,
  never as its full body, in the API payloads and in the export the server
  regenerates;
* **the per-run token rotating on restart** — already EM-114 behaviour, pinned
  in ``test_graph_server_security.py``; this file re-asserts the rotation only
  so the card's clause has a test beside its siblings.

The scope clause (owner-only unless ``--scope all``) is recorded as
**not applicable to this server today**: it serves vault notes, which carry no
``scope_user`` column. The memory-side scope is decided by the exporting CLI
(``graph export --entities --scope``), and the server never passes ``--entities``
— the loader's owner-only default is pinned in the EM-605 slice suite.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent
_SERVER_DIR = _REPO / "scripts" / "graph_server"
_PARENT = _SERVER_DIR.parent
_ENGINE_DIR = _REPO / "plugins" / "entropicmem" / "scripts"

TOKEN_HEADER = "X-EntropicMem-Token"
#: First line of the Finance note — the summary a redacted read may return.
FINANCE_SUMMARY = "Finance line one: the Q3 budget is being drafted."
#: Further down the same note. It must never appear in a served payload.
FINANCE_TAIL = "TAIL_MARKER_SHOULD_NOT_LEAK_q3_figures"
INTERNAL_BODY = "Body of Alpha Note, which is internal and served in full."


@pytest.fixture
def mod(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPORT_DIR", str(tmp_path / "graph_export"))
    monkeypatch.setenv("ENTROPICMEM_GRAPH_BIND", "127.0.0.1")
    monkeypatch.delenv("ENTROPICMEM_GRAPH_EXPOSE", raising=False)
    monkeypatch.delenv("ENTROPICMEM_GRAPH_TOKEN", raising=False)
    sys.path.insert(0, str(_PARENT))
    sys.path.insert(0, str(_ENGINE_DIR))
    import graph_server.server as server_mod

    monkeypatch.setattr(server_mod, "INDEX_DB", tmp_path / "index.db")
    monkeypatch.setattr(server_mod, "DEFAULT_VAULT", tmp_path / "vault")
    monkeypatch.setattr(server_mod, "BASE_DIR", tmp_path / "graph_export")
    # One fresh bucket per test: the module's is process-wide.
    monkeypatch.setattr(
        server_mod, "_SEARCH_LIMITER", server_mod.TokenBucket(server_mod.SEARCH_RATE_PER_SECOND)
    )
    return server_mod


@pytest.fixture
def seeded(mod, tmp_path):
    """A real vault + index: one internal note, one sensitive-domain note."""
    from em_internal.index import VaultIndex
    from em_internal.vault import Vault

    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    vault = Vault(root)
    notes = [
        ("Knowledge", "Alpha Note", INTERNAL_BODY),
        ("Finance", "Budget Note", FINANCE_SUMMARY + "\n\n" + FINANCE_TAIL),
    ]
    index = VaultIndex(mod.INDEX_DB)
    for domain, title, body in notes:
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
    return vault


@pytest.fixture
def client(mod, seeded):
    return TestClient(mod.app, base_url="http://127.0.0.1:8075")


# ── clause 1: read-only database opens ──────────────────────────────────────

def test_a_read_only_index_refuses_a_write(tmp_path):
    """The AC's literal check: the write attempt fails."""
    import sqlite3

    from em_internal.index import VaultIndex

    path = tmp_path / "index.db"
    VaultIndex(path).close()

    reader = VaultIndex(path, readonly=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.db.execute(
                "INSERT INTO notes_meta (note_id, path, title) VALUES ('x', 'y', 'z')"
            )
    finally:
        reader.close()


def test_a_read_only_index_does_not_create_a_missing_file(tmp_path):
    from em_internal.index import VaultIndex

    path = tmp_path / "absent.db"
    with pytest.raises(FileNotFoundError):
        VaultIndex(path, readonly=True)
    assert not path.exists()


def test_a_read_only_index_refuses_an_unmigrated_schema(tmp_path):
    """A v0 file is not silently migrated by a reader — /refresh owns that."""
    import sqlite3

    from em_internal.index import IndexRequiresMigration, VaultIndex

    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE unrelated (x INTEGER)")
    conn.commit()
    conn.close()

    with pytest.raises(IndexRequiresMigration):
        VaultIndex(path, readonly=True)

    check = sqlite3.connect(str(path))
    try:
        assert check.execute("PRAGMA user_version").fetchone()[0] == 0, (
            "the refused reader must not have migrated the file"
        )
        assert check.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='notes_meta'"
        ).fetchone()[0] == 0
    finally:
        check.close()


def test_a_read_against_a_missing_index_creates_nothing(mod, tmp_path):
    """The class this closes: a GET that writes the database into existence."""
    broken = TestClient(mod.app, base_url="http://127.0.0.1:8075", raise_server_exceptions=False)
    response = broken.get("/api/note/by-title/Anything")
    assert response.status_code >= 500
    assert not mod.INDEX_DB.exists(), "a read endpoint created index.db"


def test_every_read_endpoint_opens_the_index_read_only(mod, client, monkeypatch):
    """Wiring, not just the class: the endpoints must ask for the ro mode."""
    from em_internal.index import VaultIndex

    calls: list = []

    class Recorder(VaultIndex):
        def __init__(self, path, **kwargs):
            calls.append(kwargs)
            super().__init__(path, **kwargs)

    monkeypatch.setattr(mod, "VaultIndex", Recorder)

    for url in (
        "/api/note/Knowledge%2FAlpha%20Note",
        "/api/note/by-title/Alpha%20Note",
        "/api/search?q=Alpha",
        "/api/path?from=Knowledge/Alpha%20Note&to=Finance/Budget%20Note",
    ):
        assert client.get(url).status_code == 200, url

    assert calls, "the read endpoints never opened the index"
    assert all(call.get("readonly") is True for call in calls), calls

    # /refresh rebuilds the index, so it is the one writer — deliberately.
    calls.clear()
    refreshed = client.post("/refresh", headers={TOKEN_HEADER: mod.RUN_TOKEN})
    assert refreshed.status_code == 200
    assert calls and all(call.get("readonly") is not True for call in calls), calls


# ── clause 2: the search token bucket ───────────────────────────────────────

def test_the_default_search_rate_is_ten_per_second(mod):
    assert mod.SEARCH_RATE_PER_SECOND == 10.0


def test_the_bucket_refills_at_the_configured_rate():
    import graph_server.server as server_mod

    now = [100.0]
    bucket = server_mod.TokenBucket(10.0, clock=lambda: now[0])

    assert all(bucket.take() == 0.0 for _ in range(10)), "the burst is 10"
    assert bucket.take() > 0.0, "the eleventh is refused"

    now[0] += 0.1  # one tenth of a second = one token at 10 rps
    assert bucket.take() == 0.0
    assert bucket.take() > 0.0


def test_an_exhausted_search_bucket_answers_429(client, mod, monkeypatch):
    # A frozen clock is the point of the test: with the real one, ten requests
    # on a slow runner take longer than a token interval, the bucket refills
    # mid-loop and the eleventh is allowed — this flaked on the 3.12 CI leg.
    frozen = [1_000.0]
    monkeypatch.setattr(
        mod,
        "_SEARCH_LIMITER",
        mod.TokenBucket(mod.SEARCH_RATE_PER_SECOND, clock=lambda: frozen[0]),
    )
    for _ in range(int(mod.SEARCH_RATE_PER_SECOND)):
        assert client.get("/api/search?q=Alpha").status_code == 200

    refused = client.get("/api/search?q=Alpha")
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) >= 1


def test_the_limit_covers_search_only(client, mod):
    """The card names /api/search; a broad limiter would be a different card."""
    for _ in range(int(mod.SEARCH_RATE_PER_SECOND) + 2):
        assert client.get("/api/note/Knowledge%2FAlpha%20Note").status_code == 200


# ── clause 3: sensitivity redaction ─────────────────────────────────────────

def test_a_sensitive_domain_note_is_served_as_a_summary(client):
    body = client.get("/api/note/Finance%2FBudget%20Note").json()
    assert body["full_body"].startswith("[sensitive]")
    assert FINANCE_SUMMARY.split(":")[0] in body["full_body"]
    assert FINANCE_TAIL not in json.dumps(body), "the tail of a sensitive note leaked"
    assert body["body_preview"] == body["full_body"]
    # metadata is not the secret: the modal still knows which note it opened
    assert body["domain"] == "Finance"


def test_an_internal_note_is_not_redacted(client):
    body = client.get("/api/note/Knowledge%2FAlpha%20Note").json()
    assert body["full_body"] == INTERNAL_BODY
    assert "[sensitive]" not in json.dumps(body)


def test_a_sensitive_search_snippet_is_redacted(client):
    payload = client.get("/api/search?q=budget").json()
    hits = [r for r in payload["results"] if r["note_id"] == "Finance/Budget Note"]
    assert hits, payload
    snippet = hits[0]["snippet"]
    assert snippet.startswith("[sensitive]")
    assert FINANCE_TAIL not in json.dumps(payload)


def test_the_model_redacts_sensitive_bodies_when_asked(mod, seeded):
    from em.graph.export import export_json

    index = mod.VaultIndex(mod.INDEX_DB, readonly=True)
    try:
        payload = export_json(
            index,
            mod.BASE_DIR / "redacted.json",
            max_nodes=50,
            include_bodies=True,
            redact_sensitive=True,
        )
    finally:
        index.close()

    nodes = {n["title"]: n for n in payload["nodes"]}
    assert nodes["Budget Note"]["full_body"].startswith("[sensitive]")
    assert nodes["Alpha Note"]["full_body"] == INTERNAL_BODY
    assert FINANCE_TAIL not in json.dumps(payload)


def test_the_refresh_endpoint_asks_both_renderers_to_redact(client, mod, monkeypatch):
    """Both calls must carry the flag on their own: graph.json is written by
    each, so only a wiring pin can tell the first call from the second."""
    seen: dict = {}
    real_json, real_html = mod.export_json, mod.export_html

    def json_spy(*args, **kwargs):
        seen["json"] = kwargs.get("redact_sensitive")
        return real_json(*args, **kwargs)

    def html_spy(*args, **kwargs):
        seen["html"] = kwargs.get("redact_sensitive")
        return real_html(*args, **kwargs)

    monkeypatch.setattr(mod, "export_json", json_spy)
    monkeypatch.setattr(mod, "export_html", html_spy)

    assert client.post("/refresh", headers={TOKEN_HEADER: mod.RUN_TOKEN}).status_code == 200
    assert seen == {"json": True, "html": True}, seen


def test_the_refresh_endpoint_redacts_the_export_it_writes(client, mod):
    response = client.post("/refresh", headers={TOKEN_HEADER: mod.RUN_TOKEN})
    assert response.status_code == 200, response.text

    written = json.loads((mod.BASE_DIR / "graph.json").read_text(encoding="utf-8"))
    nodes = {n["title"]: n for n in written["nodes"]}
    assert nodes["Budget Note"]["full_body"].startswith("[sensitive]")
    assert FINANCE_TAIL not in json.dumps(written)
    assert nodes["Alpha Note"]["full_body"] == INTERNAL_BODY

    html = (mod.BASE_DIR / "graph.html").read_text(encoding="utf-8")
    assert FINANCE_TAIL not in html
