"""EM-602 slice 2 — `note_id` as the vault-relative path, and the index migration.

`Note.note_id` used to drop the top directory of the path
(``path.relative_to(path.parent.parent)``), so ``A/Sub/Note`` and
``B/Sub/Note`` both read ``Sub/Note`` — the same primary key for two different
notes. The rule is now the **full vault-relative path** (POSIX separators,
extension stripped): unique by construction, and the number the card's AC asks
for ("notes in nested folders get unique ids").

Because it is the primary key of ``notes_meta``, the id is also stored in
``notes_fts`` and as the ``wikilink`` endpoints of ``graph_edges``, so an
existing ``index.db`` needs a **``user_version`` 2 migration**. The old id is
not invertible (it dropped a component) but the row's own ``path`` is, so the
migration recomputes each id from its path, remaps the wikilink edges through
that map, leaves ``kind='triple:*'`` edges alone (they carry entity/triple ids,
not note ids) and refreshes the FTS rows. The index is a cache of the vault, so
the migration is idempotent.

Rules: invented data only.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for entry in (str(REPO), str(SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from em_internal.index import SCHEMA_VERSION, VaultIndex  # noqa: E402
from em_internal.vault import Note, Vault, note_id_for_path  # noqa: E402


def _legacy_note_id(path: Path) -> str:
    """The pre-EM-602 rule, kept here as the migration's input shape."""
    try:
        rel = path.relative_to(path.parent.parent)
    except ValueError:
        rel = path
    return str(rel.with_suffix(""))


@pytest.fixture
def vault_and_index(tmp_path):
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    vault = Vault(root)
    index = VaultIndex(tmp_path / "index.db")
    yield vault, index, root
    index.close()


def _edges(index: VaultIndex) -> set:
    return {
        (r["source_id"], r["target_id"], r["kind"])
        for r in index.db.execute("SELECT source_id, target_id, kind FROM graph_edges")
    }


def _ids(index: VaultIndex) -> set:
    return {r["note_id"] for r in index.db.execute("SELECT note_id FROM notes_meta")}


def _write_note(root: Path, rel: str, title: str, body: str, domain: str = "") -> None:
    """Write a note at an arbitrary vault-relative path.

    `Vault.write_note` sanitizes the folder, so it cannot produce a nested path
    (it turns ``A/Sub`` into ``A Sub``); a real vault gets nested folders from
    the person or from Obsidian, so these fixtures write the file directly.
    """
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    front = f'---\ntitle: {title}\ntype: permanent\ncreated: "2026-01-02"\n'
    front += 'updated: "2026-01-02"\nagent: true\n'
    if domain:
        front += f"domain: {domain}\n"
    front += "---\n"
    path.write_text(front + "\n" + body + "\n", encoding="utf-8")


def _nested_vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    _write_note(root, "A/Sub/Note.md", "Note", "See [[Other]].", domain="A")
    _write_note(root, "A/Sub/Other.md", "Other", "Body.", domain="A")
    return Vault(root)


# --- the rule -----------------------------------------------------------------


def test_the_note_id_is_the_full_vault_relative_path():
    assert note_id_for_path("Knowledge/Note.md") == "Knowledge/Note"
    assert note_id_for_path("A/Sub/Note.md") == "A/Sub/Note"
    assert note_id_for_path("Knowledge/Note.v2.md") == "Knowledge/Note.v2"
    # A Windows-written path still yields POSIX separators.
    assert note_id_for_path("A\\Sub\\Note.md") == "A/Sub/Note"


def test_nested_paths_that_used_to_collide_now_differ():
    first = note_id_for_path("A/Sub/Note.md")
    second = note_id_for_path("B/Sub/Note.md")
    assert first != second
    # ... and they really did collide under the old rule.
    assert _legacy_note_id(Path("A/Sub/Note.md")) == _legacy_note_id(
        Path("B/Sub/Note.md")
    )


def test_note_note_id_uses_the_rule():
    note = Note(path=Path("A/Sub/Note.md"), title="Note", body="Body.")
    assert note.note_id == "A/Sub/Note"
    # A shallow note is unchanged by the rule, which is why the index tests
    # under Knowledge/ still read the same ids they always did.
    assert Note(path=Path("Knowledge/Note.md"), title="N", body="B").note_id == (
        "Knowledge/Note"
    )


# --- the index -----------------------------------------------------------------


def test_nested_notes_get_distinct_index_rows_and_edges(tmp_path):
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    _write_note(root, "A/Sub/Note.md", "Note", "See [[Other]].", domain="A")
    _write_note(root, "B/Sub/Note.md", "Second Note", "Body.", domain="B")
    _write_note(root, "A/Sub/Other.md", "Other", "Body.", domain="A")
    vault = Vault(root)

    index = VaultIndex(tmp_path / "index.db")
    try:
        index.rebuild(vault)
        assert _ids(index) == {"A/Sub/Note", "B/Sub/Note", "A/Sub/Other"}
        assert index.get_note("A/Sub/Note")["title"] == "Note"
        assert index.get_note("B/Sub/Note")["title"] == "Second Note"
        assert ("A/Sub/Note", "A/Sub/Other", "wikilink") in _edges(index)
    finally:
        index.close()


def test_a_fresh_index_is_at_the_schema_version(vault_and_index):
    vault, index, root = vault_and_index
    assert index.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert SCHEMA_VERSION == 2


# --- the migration -------------------------------------------------------------


def _build_legacy_index(db: Path, vault: Vault) -> None:
    """An index as EM-602 found it: old ids, `user_version` 0, plus triple edges.

    One triple edge is given an endpoint that is *textually* a legacy note id
    (``Sub/Note``): the migration rewrites note ids, and triple endpoints are a
    different id space, so the pin is that a non-wikilink edge is never touched
    — which only a scoped rewrite satisfies.
    """
    index = VaultIndex(db)
    try:
        index.rebuild(vault)
        legacy_deep = _legacy_note_id(Path("A/Sub/Note.md"))
        index.db.executemany(
            "INSERT INTO graph_edges (source_id, target_id, kind) VALUES (?, ?, ?)",
            [
                ("ent_acme", "ent_falcon", "triple:related"),
                (legacy_deep, "ent_falcon", "triple:related"),
            ],
        )
        mapping = {
            row["note_id"]: _legacy_note_id(Path(row["path"]))
            for row in index.db.execute("SELECT note_id, path FROM notes_meta")
        }
        for old, new in mapping.items():
            index.db.execute(
                "UPDATE notes_meta SET note_id = ? WHERE note_id = ?", (new, old)
            )
            index.db.execute(
                "UPDATE notes_fts SET note_id = ? WHERE note_id = ?", (new, old)
            )
            index.db.execute(
                "UPDATE graph_edges SET source_id = ? WHERE source_id = ? AND kind = 'wikilink'",
                (new, old),
            )
            index.db.execute(
                "UPDATE graph_edges SET target_id = ? WHERE target_id = ? AND kind = 'wikilink'",
                (new, old),
            )
        index.db.execute("PRAGMA user_version = 0")
        index.db.commit()
    finally:
        index.close()


def test_opening_a_legacy_index_migrates_the_note_ids(tmp_path):
    db = tmp_path / "index.db"
    vault = _nested_vault(tmp_path)
    _build_legacy_index(db, vault)
    # The fixture really is in the old shape: the ids dropped the top folder.
    conn = sqlite3.connect(str(db))
    try:
        old_ids = {r[0] for r in conn.execute("SELECT note_id FROM notes_meta")}
    finally:
        conn.close()
    assert old_ids == {"Sub/Note", "Sub/Other"}

    index = VaultIndex(db)
    try:
        assert _ids(index) == {"A/Sub/Note", "A/Sub/Other"}
        assert index.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        # The wikilink edge moved with its endpoints...
        assert ("A/Sub/Note", "A/Sub/Other", "wikilink") in _edges(index)
        assert not any(
            "Sub/Note" in (e[0], e[1])
            for e in _edges(index)
            if e[2] == "wikilink"
        )
        # ... the FTS rows moved too (a joined search would otherwise find nothing) ...
        hits = index.search_fts("Other")
        assert hits and hits[0].note_id == "A/Sub/Other"
        # ... and a triple edge is a different id space: the migration is scoped
        # to wikilink edges, so it is not rewritten even where its text equals a
        # legacy note id.
        assert ("ent_acme", "ent_falcon", "triple:related") in _edges(index)
        assert ("Sub/Note", "ent_falcon", "triple:related") in _edges(index)
    finally:
        index.close()


def test_the_migration_is_idempotent(tmp_path):
    db = tmp_path / "index.db"
    vault = _nested_vault(tmp_path)
    _build_legacy_index(db, vault)
    first = VaultIndex(db)
    try:
        after_first = (_ids(first), _edges(first))
    finally:
        first.close()
    second = VaultIndex(db)
    try:
        assert (_ids(second), _edges(second)) == after_first
    finally:
        second.close()


def test_the_migration_does_not_drop_triple_edges_or_rewrite_unmapped_ids(tmp_path):
    """A note whose id is already the new form must survive untouched, and the
    triple edge must survive both passes."""
    db = tmp_path / "index.db"
    vault = _nested_vault(tmp_path)
    _build_legacy_index(db, vault)
    index = VaultIndex(db)
    try:
        kinds = {
            row["kind"] for row in index.db.execute("SELECT DISTINCT kind FROM graph_edges")
        }
        assert kinds == {"wikilink", "triple:related"}
        rows = index.db.execute(
            "SELECT note_id, path FROM notes_meta ORDER BY note_id"
        ).fetchall()
        # Every stored id is exactly the rule applied to its own path.
        for row in rows:
            assert row["note_id"] == note_id_for_path(row["path"])
    finally:
        index.close()


def test_a_rebuild_after_migration_agrees_with_the_migrated_index(tmp_path):
    db = tmp_path / "index.db"
    vault = _nested_vault(tmp_path)
    _build_legacy_index(db, vault)
    index = VaultIndex(db)
    try:
        migrated = (_ids(index), _edges(index))
        index.rebuild(vault)
        assert (_ids(index), _edges(index)) == migrated
    finally:
        index.close()
