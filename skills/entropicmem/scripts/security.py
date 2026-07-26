"""
security.py — Encryption at rest for EntropicMem (Phase 11.1).

Uses Fernet symmetric encryption with PBKDF2-derived keys.
No key material is stored on disk; the passphrase is required
to encrypt/decrypt. While encrypted, the engine cannot open the DB.

Requires: cryptography (install via `pip install entropicmem[security]`)
"""

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# Marker file placed next to the DB when encryption is active
ENCRYPTED_MARKER = ".encrypted"
SALT_FILE = ".salt"
VAULT_ENCRYPTED_EXT = ".md.enc"


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from passphrase + salt via PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    return key


def _get_fernet(passphrase: str, salt: bytes) -> "Fernet":
    return Fernet(_derive_key(passphrase, salt))


def is_encrypted(db_path: Path) -> bool:
    """Check whether the DB directory has an active encryption marker."""
    return (db_path.parent / ENCRYPTED_MARKER).exists()


def encrypt_file(path: Path, fernet: "Fernet") -> None:
    """Encrypt a file in-place, replacing it with .enc version."""
    data = path.read_bytes()
    encrypted = fernet.encrypt(data)
    enc_path = path.with_suffix(path.suffix + ".enc")
    enc_path.write_bytes(encrypted)
    path.unlink()  # remove plaintext


def decrypt_file(enc_path: Path, fernet: "Fernet") -> Path:
    """Decrypt a .enc file back to its original path."""
    data = enc_path.read_bytes()
    decrypted = fernet.decrypt(data)
    original_path = enc_path.with_suffix("")  # strip .enc
    original_path.write_bytes(decrypted)
    enc_path.unlink()
    return original_path


def encrypt_db(db_path: Path, passphrase: str) -> dict:
    """
    Encrypt the memory DB and all vault .md files.

    Returns {"encrypted_files": int, "salt": hex}.
    Raises RuntimeError if cryptography is unavailable.
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package not installed. Run: pip install entropicmem[security]")

    if is_encrypted(db_path):
        return {"encrypted_files": 0, "message": "Already encrypted"}

    salt = os.urandom(16)
    fernet = _get_fernet(passphrase, salt)

    encrypted_count = 0

    # Encrypt the DB file
    if db_path.exists():
        encrypt_file(db_path, fernet)
        encrypted_count += 1

    # Encrypt WAL/SHM if present
    for suffix in ["-wal", "-shm"]:
        wal = db_path.with_suffix(db_path.suffix + suffix)
        if wal.exists():
            encrypt_file(wal, fernet)
            encrypted_count += 1

    # Encrypt vault .md files
    vault_dir = db_path.parent / "vault"
    if vault_dir.exists():
        for md_file in vault_dir.rglob("*.md"):
            encrypt_file(md_file, fernet)
            encrypted_count += 1

    # Write salt + marker
    (db_path.parent / SALT_FILE).write_bytes(salt)
    marker_data = json.dumps({"version": 1, "files": encrypted_count})
    (db_path.parent / ENCRYPTED_MARKER).write_text(marker_data)

    return {"encrypted_files": encrypted_count, "salt": salt.hex()}


def decrypt_db(db_path: Path, passphrase: str) -> dict:
    """
    Decrypt the memory DB and all vault .md.enc files.

    Returns {"decrypted_files": int}.
    Raises ValueError if passphrase is wrong.
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package not installed. Run: pip install entropicmem[security]")

    if not is_encrypted(db_path):
        return {"decrypted_files": 0, "message": "Not encrypted"}

    salt_path = db_path.parent / SALT_FILE
    if not salt_path.exists():
        raise RuntimeError("Salt file missing — cannot decrypt")

    salt = salt_path.read_bytes()
    fernet = _get_fernet(passphrase, salt)

    decrypted_count = 0

    # Decrypt DB
    enc_db = db_path.with_suffix(db_path.suffix + ".enc")
    if enc_db.exists():
        try:
            decrypt_file(enc_db, fernet)
            decrypted_count += 1
        except InvalidToken:
            raise ValueError("Wrong passphrase — cannot decrypt")

    # Decrypt WAL/SHM
    for suffix in ["-wal", "-shm"]:
        enc_wal = db_path.parent / (db_path.name + suffix + ".enc")
        if enc_wal.exists():
            try:
                decrypt_file(enc_wal, fernet)
                decrypted_count += 1
            except InvalidToken:
                raise ValueError("Wrong passphrase — cannot decrypt")

    # Decrypt vault files
    vault_dir = db_path.parent / "vault"
    if vault_dir.exists():
        for enc_file in vault_dir.rglob("*.md.enc"):
            try:
                decrypt_file(enc_file, fernet)
                decrypted_count += 1
            except InvalidToken:
                raise ValueError("Wrong passphrase — cannot decrypt")

    # Remove marker + salt
    (db_path.parent / ENCRYPTED_MARKER).unlink(missing_ok=True)
    salt_path.unlink(missing_ok=True)

    return {"decrypted_files": decrypted_count}


def security_status(db_path: Path) -> dict:
    """Report encryption status."""
    encrypted = is_encrypted(db_path)
    result: dict = {
        "encrypted": encrypted,
        "crypto_available": CRYPTO_AVAILABLE,
    }
    if encrypted:
        marker_path = db_path.parent / ENCRYPTED_MARKER
        try:
            marker = json.loads(marker_path.read_text())
            result["encrypted_files"] = marker.get("files", "unknown")
        except Exception:
            result["encrypted_files"] = "unknown"
    return result
