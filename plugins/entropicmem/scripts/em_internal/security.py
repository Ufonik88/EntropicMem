"""
security.py — Encryption at rest for EntropicMem (Phase 11.1).

Uses Fernet symmetric encryption with PBKDF2-derived keys.
No key material is stored on disk; the passphrase is required
to encrypt/decrypt. While encrypted, the engine cannot open the DB.

Plaintext-remnant caveat (write-then-unlink): encrypt_file and decrypt_file
replace files write-then-unlink (the new .enc or plaintext copy is written and
the counterpart removed with unlink). On journaling, copy-on-write or
SSD wear-leveling filesystems the unlinked plaintext (or the decrypted copy)
may remain recoverable until its blocks are overwritten. Removal is logical,
not forensic — use full-disk encryption when the threat model requires it.

Requires: cryptography (install via `pip install entropicmem[security]`)
"""

import contextlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from em.util.fsperm import chmod_posix

try:
    import base64

    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# Marker file placed next to the DB when encryption is active
ENCRYPTED_MARKER = ".encrypted"
SALT_FILE = ".salt"
VAULT_ENCRYPTED_EXT = ".md.enc"

# Known plaintext probe: encrypt_db stores a Fernet token over this constant in
# the marker so decrypt_db can validate the passphrase against a known test
# vector before mutating anything.
_VERIFIER_PLAINTEXT = b"entropicmem-encryption-verifier-v1"
_VERIFIER_KEY = "verifier"


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

def _ciphertext_files(db_path: Path) -> list:
    """All ciphertext files for this DB directory, in decrypt order.

    Order: the DB itself, then WAL/SHM companions, then vault ``*.md.enc``.
    """
    files = []
    enc_db = db_path.with_suffix(db_path.suffix + ".enc")
    if enc_db.exists():
        files.append(enc_db)
    for suffix in ["-wal", "-shm"]:
        enc_wal = db_path.parent / (db_path.name + suffix + ".enc")
        if enc_wal.exists():
            files.append(enc_wal)
    vault_dir = db_path.parent / "vault"
    if vault_dir.exists():
        files.extend(sorted(vault_dir.rglob("*.md.enc")))
    return files

def _validate_passphrase(fernet: "Fernet", db_path: Path) -> None:
    """Raise ValueError unless ``fernet`` matches the stored test vector.

    encrypt_db embeds a Fernet token over the known ``_VERIFIER_PLAINTEXT`` in
    the marker file. Markers written by older versions carry no verifier; for
    those, the first ciphertext file is decrypted in memory as the check. Both
    paths are read-only: nothing on disk is modified before the passphrase is
    proven correct.
    """
    verifier = None
    try:
        marker = json.loads((db_path.parent / ENCRYPTED_MARKER).read_text())
        if isinstance(marker, dict):
            verifier = marker.get(_VERIFIER_KEY)
    except Exception:
        verifier = None
    if verifier:
        token = verifier.encode("ascii") if isinstance(verifier, str) else bytes(verifier)
        try:
            plain = fernet.decrypt(token)
        except InvalidToken:
            raise ValueError("Wrong passphrase — cannot decrypt")
        if plain != _VERIFIER_PLAINTEXT:
            raise ValueError("Encryption verifier mismatch — cannot decrypt")
        return
    probe = next(iter(_ciphertext_files(db_path)), None)
    if probe is not None:
        try:
            fernet.decrypt(probe.read_bytes())
        except InvalidToken:
            raise ValueError("Wrong passphrase — cannot decrypt")


def is_encrypted(db_path: Path) -> bool:
    """Check whether the DB directory has an active encryption marker."""
    return (db_path.parent / ENCRYPTED_MARKER).exists()


def _write_private_bytes(path: Path, data: bytes) -> None:
    """Atomically write *data* to *path* with a private POSIX mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        chmod_posix(temp_name, 0o600)
        os.replace(temp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":  # pragma: no cover - POSIX durability only
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _staging_dir(db_path: Path) -> Path:
    """A private directory on the same filesystem, so ``os.replace`` is atomic."""
    parent = db_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=".entropicmem-encrypt-", dir=str(parent)))
    chmod_posix(path, 0o700)
    return path


def _plaintext_files(db_path: Path) -> list:
    """Every plaintext file that belongs to this DB directory, in encrypt order."""
    files = []
    if db_path.exists():
        files.append(db_path)
    for suffix in ("-wal", "-shm"):
        companion = db_path.with_suffix(db_path.suffix + suffix)
        if companion.exists():
            files.append(companion)
    vault_dir = db_path.parent / "vault"
    if vault_dir.exists():
        files.extend(sorted(vault_dir.rglob("*.md")))
    return files


def _remove_plaintext_remnants(db_path: Path) -> None:
    """Drop plaintext left beside a ciphertext by an interrupted encrypt run.

    A completed marker means the ``.enc`` file is authoritative; a plaintext
    counterpart can only be a remnant of the crash window between writing the
    marker and unlinking the originals.
    """
    for enc_path in _ciphertext_files(db_path):
        with contextlib.suppress(FileNotFoundError):
            enc_path.with_suffix("").unlink()


def encrypt_file(path: Path, fernet: "Fernet") -> None:
    """Encrypt a file in-place, replacing it with a private .enc version."""
    data = path.read_bytes()
    encrypted = fernet.encrypt(data)
    enc_path = path.with_suffix(path.suffix + ".enc")
    _write_private_bytes(enc_path, encrypted)
    path.unlink()  # remove plaintext


def decrypt_file(enc_path: Path, fernet: "Fernet") -> Path:
    """Decrypt a .enc file back to its original path.

    The ciphertext is decrypted in memory first and only then written, so an
    InvalidToken (wrong passphrase / corrupt token) never modifies the
    filesystem. The plaintext is written atomically with mode 0600. See the
    module docstring for the plaintext-remnant caveat.
    """
    data = enc_path.read_bytes()
    decrypted = fernet.decrypt(data)
    original_path = enc_path.with_suffix("")  # strip .enc
    _write_private_bytes(original_path, decrypted)
    enc_path.unlink()
    return original_path


def encrypt_db(db_path: Path, passphrase: str) -> dict:
    """
    Encrypt the memory DB and all vault .md files.

    All ciphertexts are staged first; the originals are only unlinked after
    the salt and marker are durable. A failure before that point leaves the
    directory exactly as it was.

    Returns {"encrypted_files": int, "salt": hex}.
    Raises RuntimeError if cryptography is unavailable.
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package not installed. Run: pip install entropicmem[security]")

    if is_encrypted(db_path):
        _remove_plaintext_remnants(db_path)
        return {"encrypted_files": 0, "message": "Already encrypted"}

    salt = os.urandom(16)
    fernet = _get_fernet(passphrase, salt)
    sources = _plaintext_files(db_path)

    staging = _staging_dir(db_path)
    try:
        staged = []
        for source in sources:
            destination = source.with_suffix(source.suffix + ".enc")
            relative = source.relative_to(db_path.parent)
            staged_path = staging / relative.with_suffix(relative.suffix + ".enc")
            _write_private_bytes(staged_path, fernet.encrypt(source.read_bytes()))
            staged.append((staged_path, destination))

        verifier = fernet.encrypt(_VERIFIER_PLAINTEXT).decode("ascii")
        marker_data = json.dumps(
            {"version": 1, "files": len(sources), _VERIFIER_KEY: verifier}
        )
        staged_salt = staging / "salt.bin"
        staged_marker = staging / "marker.json"
        _write_private_bytes(staged_salt, salt)
        _write_private_bytes(staged_marker, marker_data.encode("utf-8"))

        # Commit ciphertexts first, then salt, then the marker. Until the
        # marker lands, every plaintext original is still in place.
        for staged_path, destination in staged:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, destination)
        os.replace(staged_salt, db_path.parent / SALT_FILE)
        os.replace(staged_marker, db_path.parent / ENCRYPTED_MARKER)
        _fsync_dir(db_path.parent)

        for source in sources:
            with contextlib.suppress(FileNotFoundError):
                source.unlink()
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return {"encrypted_files": len(sources), "salt": salt.hex()}


def decrypt_db(db_path: Path, passphrase: str) -> dict:
    """
    Decrypt the memory DB and all vault .md.enc files.

    The passphrase is validated against the stored test vector BEFORE any file
    is touched, and every plaintext is staged before any is moved into place,
    so a wrong passphrase or a corrupt member is a complete no-op — never a
    half-decrypted directory with the marker still in place.

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

    # Validate the passphrase against the known test vector BEFORE mutating
    # anything; only then decrypt all files.
    _validate_passphrase(fernet, db_path)
    ciphertexts = _ciphertext_files(db_path)

    staging = _staging_dir(db_path)
    try:
        staged = []
        for enc_path in ciphertexts:
            target = enc_path.with_suffix("")
            relative = target.relative_to(db_path.parent)
            staged_path = staging / relative
            try:
                plaintext = fernet.decrypt(enc_path.read_bytes())
            except InvalidToken:
                raise ValueError(
                    f"Ciphertext verification failed for {enc_path.name} — cannot decrypt"
                )
            _write_private_bytes(staged_path, plaintext)
            staged.append((staged_path, target))

        for staged_path, target in staged:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, target)

        (db_path.parent / ENCRYPTED_MARKER).unlink(missing_ok=True)
        salt_path.unlink(missing_ok=True)
        _fsync_dir(db_path.parent)

        for enc_path in ciphertexts:
            with contextlib.suppress(FileNotFoundError):
                enc_path.unlink()
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return {"decrypted_files": len(ciphertexts)}


def fix_permissions(
    db_path: Path,
    vault_path: "Path | None" = None,
    index_db: "Path | None" = None,
) -> dict:
    """Apply the private-mode policy to an existing store (explicit opt-in).

    New writes are already private; this is the one-shot migration for a vault
    created before that policy existed. Returns the number of paths changed.
    """
    changed = 0

    def _tighten(path: Path, mode: int) -> None:
        nonlocal changed
        try:
            if path.exists() and (path.stat().st_mode & 0o777) != mode:
                chmod_posix(path, mode)
                changed += 1
        except OSError:
            pass

    if vault_path is not None and Path(vault_path).is_dir():
        for dirpath, _dirnames, filenames in os.walk(str(vault_path)):
            _tighten(Path(dirpath), 0o700)
            for name in filenames:
                if name.endswith((".md", ".md.enc")):
                    _tighten(Path(dirpath) / name, 0o600)

    if index_db is not None:
        _tighten(Path(index_db), 0o600)
    _tighten(db_path.parent / SALT_FILE, 0o600)
    _tighten(db_path.parent / ENCRYPTED_MARKER, 0o600)
    for enc_path in db_path.parent.glob("*.enc"):
        _tighten(enc_path, 0o600)
    if vault_path is not None and Path(vault_path).is_dir():
        for enc_path in Path(vault_path).rglob("*.enc"):
            _tighten(enc_path, 0o600)
    return {"changed": changed}


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
