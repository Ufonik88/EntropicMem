"""Passphrase pre-validation for security.decrypt_db / decrypt_file.

A wrong passphrase must be a complete no-op: previously an InvalidToken
mid-loop left earlier files decrypted while the .encrypted marker and .salt
persisted (half-decrypted state). decrypt_db now validates the passphrase
against a known test vector (a Fernet token over a fixed probe, stored in the
marker; legacy markers fall back to an in-memory probe of the first
ciphertext) before mutating anything.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import cryptography  # noqa: F401
    _CRYPTO = True
except ImportError:
    _CRYPTO = False

pytestmark = pytest.mark.skipif(not _CRYPTO, reason="cryptography not installed")


def _build_tree(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    db.write_text("db content")
    (tmp_path / "memory.db-wal").write_text("wal content")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("vault note a")
    (vault / "b.md").write_text("vault note b")
    return db


def _tree_state(tmp_path: Path):
    return sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())


PLAIN_STATE = ["memory.db", "memory.db-wal", "vault/a.md", "vault/b.md"]


def test_wrong_passphrase_is_a_noop(tmp_path):
    from security import decrypt_db, encrypt_db

    db = _build_tree(tmp_path)
    encrypt_db(db, "correct horse")
    before = _tree_state(tmp_path)
    with pytest.raises(ValueError, match="Wrong passphrase"):
        decrypt_db(db, "wrong battery")
    assert _tree_state(tmp_path) == before, "wrong passphrase must not decrypt anything"
    assert (tmp_path / ".encrypted").exists()
    assert (tmp_path / ".salt").exists()


def test_marker_carries_passphrase_verifier_and_roundtrip(tmp_path):
    from security import ENCRYPTED_MARKER, SALT_FILE, decrypt_db, encrypt_db

    db = _build_tree(tmp_path)
    encrypt_db(db, "correct horse")
    marker = json.loads((tmp_path / ENCRYPTED_MARKER).read_text())
    assert marker.get("verifier"), "marker must carry the passphrase verifier"
    assert (tmp_path / SALT_FILE).exists()

    result = decrypt_db(db, "correct horse")
    assert result["decrypted_files"] == 4
    assert _tree_state(tmp_path) == PLAIN_STATE


def test_legacy_marker_without_verifier(tmp_path):
    from security import ENCRYPTED_MARKER, decrypt_db, encrypt_db

    db = _build_tree(tmp_path)
    encrypt_db(db, "correct horse")
    marker_path = tmp_path / ENCRYPTED_MARKER
    marker = json.loads(marker_path.read_text())
    marker.pop("verifier")
    marker_path.write_text(json.dumps(marker))

    before = _tree_state(tmp_path)
    with pytest.raises(ValueError, match="Wrong passphrase"):
        decrypt_db(db, "wrong battery")
    assert _tree_state(tmp_path) == before, "legacy fallback must also be read-only"

    result = decrypt_db(db, "correct horse")
    assert result["decrypted_files"] == 4
    assert _tree_state(tmp_path) == PLAIN_STATE


def test_tampered_verifier_refused_before_mutation(tmp_path):
    from security import ENCRYPTED_MARKER, SALT_FILE, _get_fernet, decrypt_db, encrypt_db

    db = _build_tree(tmp_path)
    encrypt_db(db, "correct horse")
    salt = (tmp_path / SALT_FILE).read_bytes()
    fernet = _get_fernet("correct horse", salt)
    marker_path = tmp_path / ENCRYPTED_MARKER
    marker = json.loads(marker_path.read_text())
    # Right passphrase, but the token is over different plaintext.
    marker["verifier"] = fernet.encrypt(b"not the known test vector").decode("ascii")
    marker_path.write_text(json.dumps(marker))

    before = _tree_state(tmp_path)
    with pytest.raises(ValueError, match="verifier"):
        decrypt_db(db, "correct horse")
    assert _tree_state(tmp_path) == before


def test_decrypt_file_no_mutation_on_invalid_token(tmp_path):
    from cryptography.fernet import Fernet, InvalidToken

    from security import decrypt_file, encrypt_file

    fernet_a = Fernet(Fernet.generate_key())
    fernet_b = Fernet(Fernet.generate_key())
    secret = tmp_path / "note.md"
    secret.write_text("plain note")
    encrypt_file(secret, fernet_a)
    enc = tmp_path / "note.md.enc"
    assert enc.exists() and not secret.exists()

    with pytest.raises(InvalidToken):
        decrypt_file(enc, fernet_b)
    assert not secret.exists() and enc.exists(), "failed decrypt must write nothing"

    out = decrypt_file(enc, fernet_a)
    assert out.read_text() == "plain note"
    assert not enc.exists()
