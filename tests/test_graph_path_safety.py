"""
test_graph_path_safety.py — Path-traversal regression tests for vault reads.

The graph export and the graph server read vault notes via paths that come
from the notes_meta table (DB-supplied). A poisoned row (absolute path,
dot-dot traversal) must never turn those reads into arbitrary file access.
Covers the shared resolve_note_path() guard plus both call sites (the export
body-fallback read and, indirectly via tests/test_graph_server_security.py,
the server's lazy body read).
"""

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "plugins" / "entropicmem" / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

from graph_export import export_html, resolve_note_path  # noqa: E402
from index import VaultIndex  # noqa: E402
from vault import Vault  # noqa: E402

SECRET_MARKER = "SECRET_MARKER_SHOULD_NOT_LEAK"


# ── resolve_note_path unit behavior ─────────────────────────────────────────

def test_resolve_note_path_accepts_inner_relative_path(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    resolved = resolve_note_path(root, "Knowledge/Note.md")
    assert resolved == (root / "Knowledge" / "Note.md").resolve()
    assert resolved.is_relative_to(root.resolve())


@pytest.mark.parametrize("bad", [
    "/etc/passwd",
    str(Path.home() / ".ssh" / "id_rsa"),
    "../secret.md",
    "a/../../secret.md",
    "..",
    "",
    "   ",
])
def test_resolve_note_path_rejects_escapes(tmp_path, bad):
    root = tmp_path / "vault"
    root.mkdir()
    with pytest.raises(ValueError):
        resolve_note_path(root, bad)


def test_resolve_note_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text(SECRET_MARKER, encoding="utf-8")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        resolve_note_path(root, "linked/secret.md")


# ── export body-fallback read is guarded ────────────────────────────────────

def _poisoned_export(tmp_path, poison_path: str):
    """Vault with one good note and one whose notes_meta.path is poisoned and
    whose index bodies are empty (so the export's vault-read fallback fires)."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    vault = Vault(vault_root)
    good = vault.write_note("Knowledge", "Good Note", "Good body content.",
                            tags=["t"], domain="Knowledge")
    poisoned = vault.write_note("Knowledge", "Poisoned Note", "",
                                tags=["t"], domain="Knowledge")
    index = VaultIndex(tmp_path / "index.db")
    index.upsert_note(vault.read_note(good))
    index.upsert_note(vault.read_note(poisoned))
    index.db.execute(
        "UPDATE notes_meta SET path = ?, body_preview = '' WHERE note_id = ?",
        (poison_path, "Knowledge/Poisoned Note"),
    )
    index.db.execute(
        "DELETE FROM notes_fts WHERE note_id = ?", ("Knowledge/Poisoned Note",)
    )
    index.db.commit()
    return vault_root, index


@pytest.mark.parametrize("poison_kind", ["absolute", "dotdot"])
def test_export_does_not_read_outside_vault(tmp_path, poison_kind):
    secret = tmp_path / "secret.md"
    secret.write_text(SECRET_MARKER, encoding="utf-8")
    poison = str(secret) if poison_kind == "absolute" else f"../{secret.name}"
    vault_root, index = _poisoned_export(tmp_path, poison)
    try:
        out = tmp_path / "graph.html"
        html = export_html(index, out, max_nodes=50, vault_root=vault_root,
                           include_bodies=True)
    finally:
        index.close()
    assert SECRET_MARKER not in html, \
        f"poisoned notes_meta.path ({poison}) leaked an outside file into the export"
    graph_json = (out.parent / "graph.json").read_text(encoding="utf-8")
    assert SECRET_MARKER not in graph_json


def test_export_still_reads_legit_vault_notes(tmp_path):
    vault_root, index = _poisoned_export(tmp_path, "/etc/passwd")
    try:
        out = tmp_path / "graph.html"
        html = export_html(index, out, max_nodes=50, vault_root=vault_root,
                           include_bodies=True)
    finally:
        index.close()
    assert "Good body content." in html, "legit vault body read regressed"
