"""Private file modes and all-or-nothing encryption for memory-bearing files.

These are behavioural checks on the write paths, not a migration: an existing
vault is left alone until something rewrites it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from em_internal.index import VaultIndex
from em_internal.vault import Vault


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


@pytest.fixture
def umask_022():
    if os.name == "nt":
        pytest.skip("POSIX permission modes")
    old = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(old)


def test_new_vault_content_is_private(tmp_path, umask_022):
    vault = Vault(tmp_path / "vault")
    vault.root.mkdir()

    note = vault.write_note("Knowledge", "Private note", "body", domain="Knowledge")
    note_path = vault.root / note
    assert _mode(note_path) == 0o600
    assert _mode(note_path.parent) == 0o700

    index = VaultIndex(tmp_path / "index.db")
    try:
        index.upsert_note(vault.read_note(note))
    finally:
        index.close()
    assert _mode(tmp_path / "index.db") == 0o600


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def _build_tree(root: Path) -> Path:
    db = root / "memory.db"
    db.write_text("db content", encoding="utf-8")
    (root / "memory.db-wal").write_text("wal content", encoding="utf-8")
    vault = root / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("note a", encoding="utf-8")
    (vault / "b.md").write_text("note b", encoding="utf-8")
    return db


def test_fix_permissions_migrates_an_existing_tree(tmp_path, umask_022):
    from em_internal.security import ENCRYPTED_MARKER, SALT_FILE, fix_permissions

    vault = tmp_path / "vault"
    (vault / "Knowledge").mkdir(parents=True)
    note = vault / "Knowledge" / "Old.md"
    note.write_text("old note", encoding="utf-8")
    index_db = tmp_path / "index.db"
    index_db.write_text("index", encoding="utf-8")
    db = tmp_path / "memory.db"
    db.write_text("db", encoding="utf-8")
    salt = tmp_path / SALT_FILE
    marker = tmp_path / ENCRYPTED_MARKER
    salt.write_text("salt", encoding="utf-8")
    marker.write_text("marker", encoding="utf-8")

    assert _mode(note) == 0o644
    result = fix_permissions(db, vault, index_db)
    assert result["changed"] >= 5
    assert _mode(note) == 0o600
    assert _mode(note.parent) == 0o700
    assert _mode(index_db) == 0o600
    assert _mode(salt) == 0o600 and _mode(marker) == 0o600


def test_encryption_artefacts_and_plaintext_are_private(tmp_path, umask_022):
    pytest.importorskip("cryptography")
    from em_internal.security import ENCRYPTED_MARKER, SALT_FILE, decrypt_db, encrypt_db

    db = _build_tree(tmp_path)
    encrypt_db(db, "correct horse")

    assert _mode(tmp_path / "memory.db.enc") == 0o600
    assert _mode(tmp_path / "vault" / "a.md.enc") == 0o600
    assert _mode(tmp_path / SALT_FILE) == 0o600
    assert _mode(tmp_path / ENCRYPTED_MARKER) == 0o600

    decrypt_db(db, "correct horse")
    for name in ("memory.db", "memory.db-wal", "vault/a.md", "vault/b.md"):
        assert _mode(tmp_path / name) == 0o600, name


def test_encrypt_failure_leaves_the_originals_untouched(tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    from em_internal import security

    db = _build_tree(tmp_path)
    before = _tree(tmp_path)
    real = security._write_private_bytes
    calls = {"n": 0}

    def flaky(path, data):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real(path, data)

    monkeypatch.setattr(security, "_write_private_bytes", flaky)
    with pytest.raises(OSError):
        security.encrypt_db(db, "correct horse")

    assert _tree(tmp_path) == before
    assert not (tmp_path / ".encrypted").exists()
    assert not (tmp_path / ".salt").exists()
    assert not list(tmp_path.glob(".entropicmem-encrypt-*"))


def test_decrypt_failure_leaves_the_ciphertexts_untouched(tmp_path):
    pytest.importorskip("cryptography")
    from em_internal.security import decrypt_db, encrypt_db

    db = _build_tree(tmp_path)
    encrypt_db(db, "correct horse")
    before = _tree(tmp_path)
    (tmp_path / "vault" / "b.md.enc").write_bytes(b"not a fernet token")

    with pytest.raises(ValueError, match="Ciphertext verification failed"):
        decrypt_db(db, "correct horse")

    assert _tree(tmp_path) == before
    assert (tmp_path / ".encrypted").exists()
    assert not list(tmp_path.glob(".entropicmem-encrypt-*"))
