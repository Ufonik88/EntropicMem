"""
test_graph_community.py - Structure-layer tests for community detection and
degree export (v2.6 graph integration, Phase 1 + Phase 5 degree field).

Covers: community ids on linked nodes, null for isolated nodes, determinism
across exports and across index rebuilds, distinct disjoint clusters,
palette determinism, degree fields, and meta.community_count.

Repo standard: prove the new assertions fail against pre-fix code before
trusting them (RED/GREEN pairs reported in the PR).
"""

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "plugins" / "entropicmem" / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

from graph_export import (  # noqa: E402
    COMMUNITY_PALETTE,
    detect_communities,
    export_json,
    get_community_color,
)
from index import VaultIndex  # noqa: E402
from vault import Vault  # noqa: E402


def _build_vault(root: Path):
    """Two disjoint fully-linked clusters (A, B) plus two isolated notes."""
    root.mkdir(parents=True, exist_ok=True)
    vault = Vault(root)
    for cluster in ("A", "B"):
        titles = [f"{cluster}{i}" for i in range(1, 5)]
        for title in titles:
            others = [t for t in titles if t != title]
            body = "Links: " + " ".join(f"[[{t}]]" for t in others)
            vault.write_note("Knowledge", title, body, tags=["t"], domain="Knowledge")
    for title in ("Lone1", "Lone2"):
        vault.write_note("Knowledge", title, "No links here.", tags=["t"], domain="Knowledge")
    return vault


@pytest.fixture
def populated(tmp_path):
    vault = _build_vault(tmp_path / "vault")
    index = VaultIndex(tmp_path / "index.db")
    for rel in vault.list_notes():
        index.upsert_note(vault.read_note(rel))
    index._rebuild_edges(vault)
    yield vault, index, tmp_path
    index.close()


def _export(index, tmp_path, name="graph.json"):
    return export_json(index, tmp_path / name, max_nodes=500)


# ── detect_communities unit behavior ────────────────────────────────────────

def test_detect_communities_two_disjoint_clusters():
    pairs = []
    for cluster in ("A", "B"):
        nodes = [f"{cluster}{i}" for i in range(1, 5)]
        for i, n in enumerate(nodes):
            for m in nodes[i + 1:]:
                pairs.append((n, m))
    community_of = detect_communities(pairs)
    a_ids = {community_of[f"A{i}"] for i in range(1, 5)}
    b_ids = {community_of[f"B{i}"] for i in range(1, 5)}
    assert len(a_ids) == 1, f"cluster A fragmented: {a_ids}"
    assert len(b_ids) == 1, f"cluster B fragmented: {b_ids}"
    assert a_ids != b_ids, "disjoint clusters must get distinct community ids"


def test_detect_communities_deterministic_on_shuffled_input():
    pairs = [("x", "y"), ("y", "z"), ("p", "q"), ("a", "b"), ("b", "c"), ("c", "a")]
    first = detect_communities(pairs)
    second = detect_communities(list(reversed(pairs)))
    assert first == second, "community assignment must not depend on input order"


def test_detect_communities_empty():
    assert detect_communities([]) == {}


# ── exported node fields ────────────────────────────────────────────────────

def test_linked_nodes_have_community_and_isolated_are_null(populated):
    vault, index, tmp_path = populated
    data = _export(index, tmp_path)
    by_id = {n["id"]: n for n in data["nodes"]}

    linked = [n for nid, n in by_id.items() if not nid.endswith(("Lone1", "Lone2"))]
    isolated = [n for nid, n in by_id.items() if nid.endswith(("Lone1", "Lone2"))]
    assert linked and isolated
    for n in linked:
        assert isinstance(n.get("community"), int), f"{n['id']} missing community id"
        assert n.get("community_color")
    for n in isolated:
        assert n.get("community") is None
        assert "community" in n, "community key must exist (null) on isolated nodes"
        assert n.get("degree") == 0


def test_clusters_do_not_share_a_community(populated):
    vault, index, tmp_path = populated
    data = _export(index, tmp_path)
    by_title = {n["title"]: n for n in data["nodes"]}
    a_ids = {by_title[f"A{i}"]["community"] for i in range(1, 5)}
    b_ids = {by_title[f"B{i}"]["community"] for i in range(1, 5)}
    assert len(a_ids) == 1 and len(b_ids) == 1
    assert a_ids != b_ids


def test_degree_counts_all_incident_edges(populated):
    vault, index, tmp_path = populated
    data = _export(index, tmp_path)
    by_title = {n["title"]: n for n in data["nodes"]}
    # Each A note links to the other three and is linked back: 6 incident edges.
    assert by_title["A1"]["degree"] == 6
    assert by_title["Lone1"]["degree"] == 0


def test_meta_community_count(populated):
    vault, index, tmp_path = populated
    data = _export(index, tmp_path)
    assert data["meta"]["community_count"] == 2


# ── determinism across exports and rebuilds ─────────────────────────────────

def test_community_stable_across_two_exports(populated):
    vault, index, tmp_path = populated
    first = {n["id"]: n["community"] for n in _export(index, tmp_path, "g1.json")["nodes"]}
    second = {n["id"]: n["community"] for n in _export(index, tmp_path, "g2.json")["nodes"]}
    assert first == second


def test_community_stable_across_two_rebuilds(populated):
    vault, index, tmp_path = populated
    index.rebuild(vault)
    first = {n["id"]: n["community"] for n in _export(index, tmp_path, "g1.json")["nodes"]}
    index.rebuild(vault)
    second = {n["id"]: n["community"] for n in _export(index, tmp_path, "g2.json")["nodes"]}
    assert first == second, "same vault state must produce identical community ids"


# ── palette ────────────────────────────────────────────────────────────────

def test_community_palette_deterministic_and_cycling():
    assert get_community_color(0) == COMMUNITY_PALETTE[0]
    assert get_community_color(1) == COMMUNITY_PALETTE[1]
    assert get_community_color(len(COMMUNITY_PALETTE)) == get_community_color(0)
    assert get_community_color(7) == get_community_color(7)
    assert get_community_color(0) != get_community_color(1)


def test_community_palette_is_colorblind_safe_set():
    # Okabe-Ito core set must be present; every entry a valid hex color.
    for okabe in ("#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7"):
        assert okabe in COMMUNITY_PALETTE
    for color in COMMUNITY_PALETTE:
        assert len(color) == 7 and color.startswith("#")
