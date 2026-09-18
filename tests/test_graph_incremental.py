"""
test_graph_incremental.py - Incremental VaultIndex.rebuild() (v2.6 graph
integration, Phase 6).

rebuild() diffs the vault against the index and rewrites only touched notes.
Hard invariants covered here:
  - untouched notes are not rewritten (sentinel rows survive)
  - triple:* edges are never wiped by a refresh (split-brain class fix)
  - added / removed / renamed notes leave the same edge set a full rebuild
    would produce (parity test)
  - a no-change rebuild is a no-op

Repo standard: these fail against the pre-fix full-wipe rebuild (RED), then
pass after (GREEN).
"""

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "entropicmem" / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

from index import VaultIndex  # noqa: E402
from vault import Vault  # noqa: E402


@pytest.fixture
def vault_and_index(tmp_path):
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    vault = Vault(root)
    index = VaultIndex(tmp_path / "index.db")
    yield vault, index, root
    index.close()


def _write(vault: Vault, title: str, body: str):
    return vault.write_note("Knowledge", title, body, tags=["t"], domain="Knowledge")


def _edges(index: VaultIndex):
    return {
        (r["source_id"], r["target_id"], r["kind"])
        for r in index.db.execute("SELECT source_id, target_id, kind FROM graph_edges")
    }


def _sentinel(index: VaultIndex, note_id: str) -> None:
    index.db.execute(
        "UPDATE notes_meta SET body_preview = 'SENTINEL' WHERE note_id = ?", (note_id,)
    )
    index.db.commit()


# ── untouched notes are not rewritten ───────────────────────────────────────

def test_only_changed_notes_are_rewritten(vault_and_index):
    vault, index, root = vault_and_index
    _write(vault, "Note A", "Body A")
    rel_b = _write(vault, "Note B", "Body B")
    index.rebuild(vault)
    _sentinel(index, "Knowledge/Note A")

    text = (root / rel_b).read_text(encoding="utf-8")
    (root / rel_b).write_text(text.replace("Body B", "Body B changed"), encoding="utf-8")

    index.rebuild(vault)

    assert index.get_note("Knowledge/Note A")["body_preview"] == "SENTINEL", \
        "untouched note was rewritten"
    preview_b = index.get_note("Knowledge/Note B")["body_preview"]
    assert "changed" in preview_b, "changed note was not reindexed"


# ── triple edges survive a rebuild ──────────────────────────────────────────

def test_triple_edges_survive_rebuild(vault_and_index):
    vault, index, root = vault_and_index
    rel = _write(vault, "Seed", "Body")
    index.rebuild(vault)
    index.db.execute(
        "INSERT INTO graph_edges (source_id, target_id, weight, kind) "
        "VALUES ('entity x', 'entity y', 1, 'triple:is')"
    )
    index.db.commit()

    index.rebuild(vault)  # no vault changes
    assert ("entity x", "entity y", "triple:is") in _edges(index), \
        "no-change rebuild wiped triple edges"

    text = (root / rel).read_text(encoding="utf-8")
    (root / rel).write_text(text + "\nmore", encoding="utf-8")
    index.rebuild(vault)  # a changed note must not wipe them either
    assert ("entity x", "entity y", "triple:is") in _edges(index), \
        "changed-note rebuild wiped triple edges"


def test_no_change_rebuild_is_noop(vault_and_index):
    vault, index, root = vault_and_index
    _write(vault, "Steady", "Body")
    index.rebuild(vault)
    _sentinel(index, "Knowledge/Steady")

    count = index.rebuild(vault)

    assert count == 1
    assert index.get_note("Knowledge/Steady")["body_preview"] == "SENTINEL"


# ── added notes ─────────────────────────────────────────────────────────────

def test_added_note_links_resolve(vault_and_index):
    vault, index, root = vault_and_index
    _write(vault, "Source", "See [[Future Note]].")
    index.rebuild(vault)
    assert not any(e[1] == "Knowledge/Future Note" for e in _edges(index))

    _write(vault, "Future Note", "Now here.")
    index.rebuild(vault)

    assert ("Knowledge/Source", "Knowledge/Future Note", "wikilink") in _edges(index), \
        "dangling link did not resolve when the target was added"


# ── removed notes ───────────────────────────────────────────────────────────

def test_removed_note_edges_gone(vault_and_index):
    vault, index, root = vault_and_index
    _write(vault, "Alpha", "See [[Beta]].")
    rel_b = _write(vault, "Beta", "Body.")
    index.rebuild(vault)
    assert ("Knowledge/Alpha", "Knowledge/Beta", "wikilink") in _edges(index)

    (root / rel_b).unlink()
    index.rebuild(vault)

    edges = _edges(index)
    assert index.get_note("Knowledge/Beta") is None
    assert index.db.execute(
        "SELECT COUNT(*) FROM notes_fts WHERE note_id = 'Knowledge/Beta'"
    ).fetchone()[0] == 0
    assert not any("Knowledge/Beta" in (e[0], e[1]) for e in edges), \
        "deleted note still has graph edges"


# ── renamed titles ──────────────────────────────────────────────────────────

def test_renamed_title_updates_edges(vault_and_index):
    vault, index, root = vault_and_index
    _write(vault, "Linker", "See [[Old Name]].")
    rel_old = _write(vault, "Old Name", "Body.")
    index.rebuild(vault)
    assert ("Knowledge/Linker", "Knowledge/Old Name", "wikilink") in _edges(index)

    # In-place title change (same path, same note_id).
    text = (root / rel_old).read_text(encoding="utf-8")
    (root / rel_old).write_text(
        text.replace('title: "Old Name"', 'title: "New Name"'), encoding="utf-8"
    )

    index.rebuild(vault)

    assert index.get_note("Knowledge/Old Name")["title"] == "New Name"
    edges = _edges(index)
    assert ("Knowledge/Linker", "Knowledge/Old Name", "wikilink") not in edges, \
        "stale edge to the old title survived the rename"


def test_rename_lets_dangling_links_resolve(vault_and_index):
    vault, index, root = vault_and_index
    _write(vault, "Linker", "See [[New Name]].")
    rel = _write(vault, "Placeholder", "Body.")
    index.rebuild(vault)
    assert ("Knowledge/Linker", "Knowledge/Placeholder", "wikilink") not in _edges(index)

    text = (root / rel).read_text(encoding="utf-8")
    (root / rel).write_text(
        text.replace('title: "Placeholder"', 'title: "New Name"'), encoding="utf-8"
    )

    index.rebuild(vault)

    assert ("Knowledge/Linker", "Knowledge/Placeholder", "wikilink") in _edges(index), \
        "link did not resolve after the target's title changed to match"


# ── parity: incremental result == full rebuild result ───────────────────────

def test_incremental_matches_full_rebuild(vault_and_index):
    vault, index, root = vault_and_index
    rel_a = _write(vault, "Alpha", "See [[Beta]]. And [[Gamma]].")
    rel_b = _write(vault, "Beta", "See [[Alpha]].")
    _write(vault, "Gamma", "Links [[Delta]].")
    _write(vault, "Delta", "Leaf.")
    _write(vault, "Doomed", "See [[Alpha]].")
    index.rebuild(vault)

    # A series of mutations: body edit, removal, addition, rename.
    text_a = (root / rel_a).read_text(encoding="utf-8")
    (root / rel_a).write_text(
        text_a.replace("And [[Gamma]].", "Now nothing else."), encoding="utf-8"
    )
    (root / "Knowledge" / "Doomed.md").unlink()
    _write(vault, "Fresh", "See [[Beta]] and [[Delta]].")
    text_b = (root / rel_b).read_text(encoding="utf-8")
    (root / rel_b).write_text(
        text_b.replace('title: "Beta"', 'title: "Beta Renamed"'), encoding="utf-8"
    )

    index.rebuild(vault)  # incremental
    incremental_edges = _edges(index)
    incremental_meta = {
        r["note_id"]: (r["title"], r["content_hash"])
        for r in index.db.execute("SELECT note_id, title, content_hash FROM notes_meta")
    }

    index.rebuild_full(vault)  # clean slate
    full_edges = _edges(index)
    full_meta = {
        r["note_id"]: (r["title"], r["content_hash"])
        for r in index.db.execute("SELECT note_id, title, content_hash FROM notes_meta")
    }

    assert incremental_edges == full_edges, "incremental edge set diverged from full rebuild"
    assert incremental_meta == full_meta, "incremental metadata diverged from full rebuild"
