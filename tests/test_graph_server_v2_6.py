"""
test_graph_server_v2_6.py - Tests for the v2.6 graph server endpoints:
/api/search (vault FTS in-graph search) and /api/path (shortest path).

Uses FastAPI TestClient with a temp HERMES_HOME so INDEX_DB is isolated,
matching tests/test_graph_server_titles.py.
"""

from pathlib import Path

import pytest

# The graph server needs fastapi; CI only installs pytest, so skip the
# whole module there rather than failing the lint/test matrix.
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

_SERVER_DIR = Path(__file__).resolve().parent.parent / "scripts" / "graph_server"
_PARENT = _SERVER_DIR.parent
_ENGINE_DIR = Path(__file__).resolve().parent.parent / "skills" / "entropicmem" / "scripts"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPORT_DIR", str(tmp_path / "graph_export"))
    import sys
    sys.path.insert(0, str(_PARENT))
    sys.path.insert(0, str(_ENGINE_DIR))
    import graph_server.server as mod
    mod.INDEX_DB.parent.mkdir(parents=True, exist_ok=True)

    from index import VaultIndex
    from vault import Vault

    vault = Vault(tmp_path / "vault")
    (tmp_path / "vault").mkdir(parents=True, exist_ok=True)
    index = VaultIndex(mod.INDEX_DB)
    for domain, title, body in [
        ("Knowledge", "Alpha Note", "Body of Alpha Note. See [[Beta Note]]"),
        ("Knowledge", "Beta Note", "Body of Beta Note. See [[Alpha Note]]"),
        ("Finance", "Alpha Finance Note", "Body of Alpha Finance Note."),
        ("Knowledge", "Chain 1", "See [[Chain 2]]"),
        ("Knowledge", "Chain 2", "See [[Chain 3]]"),
        ("Knowledge", "Chain 3", "See [[Chain 4]]"),
        ("Knowledge", "Chain 4", "End of chain."),
    ]:
        path = vault.write_note(domain, title, body, tags=["alpha-tag"], domain=domain)
        note = vault.read_note(path)
        index.upsert_note(note)
        index.upsert_edges_for_note(vault, note)
    index.close()

    return TestClient(mod.app)


# ── /api/search ─────────────────────────────────────────────────────────────

def test_search_requires_query(client):
    assert client.get("/api/search").status_code == 400
    assert client.get("/api/search?q=").status_code == 400
    assert client.get("/api/search?q=%20%20").status_code == 400


def test_search_by_title(client):
    r = client.get("/api/search?q=Alpha")
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "fts"
    titles = {hit["title"] for hit in d["results"]}
    assert "Alpha Note" in titles
    assert "Alpha Finance Note" in titles


def test_search_result_shape(client):
    hit = client.get("/api/search?q=Alpha%20Note").json()["results"][0]
    for field in ("note_id", "title", "domain", "type", "importance", "tags", "snippet"):
        assert field in hit, f"missing field {field}"
    assert hit["note_id"]


def test_search_by_body_text(client):
    r = client.get("/api/search?q=Body")
    assert r.status_code == 200
    assert len(r.json()["results"]) >= 3


def test_search_no_matches_is_empty_list(client):
    r = client.get("/api/search?q=zzzznothingmatchesthis")
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_search_invalid_fts_query_is_400_not_500(client):
    # A NUL byte makes SQLite's parser fail ("unterminated string"): the
    # endpoint must convert that into a clean 400, never a 500.
    r = client.get("/api/search?q=%00")
    assert r.status_code == 400


def test_search_special_chars_never_500(client):
    # Quotes/operators sanitize into valid FTS phrases: some hit, some don't,
    # but none may crash the endpoint.
    for q in ('"', '""', "*", "(", ")", "^", "a AND b", "a OR", "-", ":"):
        r = client.get("/api/search", params={"q": q})
        assert r.status_code in (200, 400), f"q={q!r} -> {r.status_code}"


def test_search_limit_param(client):
    r = client.get("/api/search?q=Body&limit=1")
    assert r.status_code == 200
    assert len(r.json()["results"]) == 1


# ── /api/path ───────────────────────────────────────────────────────────────

def test_path_between_neighbors(client):
    r = client.get("/api/path", params={
        "from": "Knowledge/Alpha Note", "to": "Knowledge/Beta Note",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["found"] is True
    assert d["path"] == ["Knowledge/Alpha Note", "Knowledge/Beta Note"]
    assert d["hops"] == 1


def test_path_same_node_zero_hops(client):
    d = client.get("/api/path", params={
        "from": "Knowledge/Alpha Note", "to": "Knowledge/Alpha Note",
    }).json()
    assert d["found"] is True
    assert d["hops"] == 0


def test_path_unreachable_component(client):
    d = client.get("/api/path", params={
        "from": "Knowledge/Alpha Note", "to": "Finance/Alpha Finance Note",
    }).json()
    assert d["found"] is False
    assert d["path"] == []


def test_path_unknown_node_not_found(client):
    d = client.get("/api/path", params={
        "from": "No/Such Note", "to": "Knowledge/Beta Note",
    }).json()
    assert d["found"] is False


def test_path_requires_both_endpoints(client):
    assert client.get("/api/path").status_code == 400
    assert client.get("/api/path", params={"from": "Knowledge/Alpha Note"}).status_code == 400


def test_path_depth_bound_before_enqueue(client):
    """Sourcery-caught triple_path bug class: with the depth check AFTER
    enqueueing, the search expands past the limit. The bound must be exact:
    a 3-hop chain is unreachable at max_depth=2 and found at max_depth=3."""
    short = client.get("/api/path", params={
        "from": "Knowledge/Chain 1", "to": "Knowledge/Chain 4", "max_depth": 2,
    }).json()
    assert short["found"] is False, "3-hop path must not be found with max_depth=2"
    exact = client.get("/api/path", params={
        "from": "Knowledge/Chain 1", "to": "Knowledge/Chain 4", "max_depth": 3,
    }).json()
    assert exact["found"] is True
    assert exact["hops"] == 3
    assert exact["path"] == [
        "Knowledge/Chain 1", "Knowledge/Chain 2", "Knowledge/Chain 3", "Knowledge/Chain 4",
    ]
