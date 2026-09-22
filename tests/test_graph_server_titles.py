"""
test_graph_server_titles.py — Tests for the graph server's wikilink
title-resolution endpoint (/api/note/by-title/{title}).

The modal renders [[wikilinks]] to notes outside the 500-node export as
dead links; the client resolves them lazily through this endpoint. Tests
use FastAPI TestClient with a temp HERMES_HOME so INDEX_DB is isolated.
"""

from pathlib import Path

import pytest

# The graph server needs fastapi; CI only installs pytest, so skip the
# whole module there rather than failing the lint/test matrix.
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

_SERVER_DIR = Path(__file__).resolve().parent.parent / "scripts" / "graph_server"
_PARENT = _SERVER_DIR.parent  # scripts/ — so `import graph_server.server` resolves
_ENGINE_DIR = Path(__file__).resolve().parent.parent / "plugins" / "entropicmem" / "scripts"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPORT_DIR", str(tmp_path / "graph_export"))
    import sys
    sys.path.insert(0, str(_PARENT))
    sys.path.insert(0, str(_ENGINE_DIR))
    import graph_server.server as mod
    mod.INDEX_DB.parent.mkdir(parents=True, exist_ok=True)

    # Build a small real index with a couple of notes
    from index import VaultIndex
    from vault import Vault

    vault = Vault(tmp_path / "vault")
    (tmp_path / "vault").mkdir(parents=True, exist_ok=True)
    index = VaultIndex(mod.INDEX_DB)
    for i, (domain, title) in enumerate(
        [("Knowledge", "Alpha Note"), ("Knowledge", "Beta Note"),
         ("Finance", "Alpha Finance Note")]
    ):
        path = vault.write_note(domain, title, f"Body of {title}. See [[Alpha Note]]",
                                tags=[], domain=domain)
        note = vault.read_note(path)
        index.upsert_note(note)
        index.upsert_edges_for_note(vault, note)
    index.close()

    return TestClient(mod.app)


def test_by_title_exact_match(client):
    r = client.get("/api/note/by-title/Alpha%20Note")
    assert r.status_code == 200
    d = r.json()
    assert d["title"] == "Alpha Note"
    assert d["note_id"]
    assert "Body of Alpha Note" in d["full_body"]


def test_by_title_case_insensitive(client):
    r = client.get("/api/note/by-title/alpha%20note")
    assert r.status_code == 200
    assert r.json()["title"] == "Alpha Note"


def test_by_title_contains_fallback(client):
    # No exact "Alpha Finance" — must resolve via contains, shortest title first
    r = client.get("/api/note/by-title/Alpha%20Finance")
    assert r.status_code == 200
    assert r.json()["title"] == "Alpha Finance Note"


def test_by_title_missing_404(client):
    r = client.get("/api/note/by-title/No%20Such%20Note")
    assert r.status_code == 404


def test_plain_note_route_still_works(client):
    """/api/note/{id} must not be shadowed by the by-title route."""
    r1 = client.get("/api/note/by-title/Alpha%20Note")
    nid = r1.json()["note_id"]
    r2 = client.get(f"/api/note/{nid}")
    assert r2.status_code == 200
    assert r2.json()["title"] == "Alpha Note"
