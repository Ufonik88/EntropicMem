"""EM-113: correct export/import/backups.

Acceptance contract:
- export -> wipe -> import -> recall returns equal rows
- import of a malicious tar with a '..' member is rejected (nothing written outside)
- import refuses when a lock file exists (or the provider is running)
- export archive holds memory.db + index.db + vault + manifest v2 whose
  sha256s match the exported files
- _backup() retention: last 10 backups + 1 per day for 7 days survive
"""

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import entropicmem as cli
from memory_engine import MemoryEngine

FACTS = (
    "Budget planning for Q3 targets the finance domain",
    "Team offsite venue is booked in Franschhoek",
    "VPN certificates rotate every 90 days",
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Resolved-path environment: memory.db + index.db + vault under one home."""
    home = tmp_path / "home"
    ent = home / "entropicmem"
    memory_db = ent / "memory.db"
    index_db = ent / "index.db"
    vault = ent / "vault"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("ENTROPICMEM_MEMORY_DB", str(memory_db))
    monkeypatch.setenv("ENTROPICMEM_INDEX_DB", str(index_db))
    monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", str(vault))
    vault.mkdir(parents=True)
    return SimpleNamespace(
        home=home, ent=ent, memory_db=memory_db, index_db=index_db, vault=vault
    )


def _seed(env):
    """Seed a memory DB + index DB + vault note; return the open engine."""
    eng = MemoryEngine(env.memory_db)
    for text in FACTS:
        eng.remember(text, domain="Knowledge")
    note = env.vault / "Knowledge" / "Note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Note\n\nhello vault", encoding="utf-8")
    conn = sqlite3.connect(str(env.index_db))
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    return eng


def _make_capsule(env, tmp_path, name="capsule.tar.gz"):
    eng = _seed(env)
    eng.close()
    capsule = tmp_path / name
    cli.export_capsule(capsule)
    return capsule


# ── AC1: export -> wipe -> import -> recall equal ────────────────────────────

def test_export_wipe_import_recall_equal(env, tmp_path):
    eng = _seed(env)
    before_facts = sorted((f.id, f.content, f.domain) for f in eng.list_facts())
    before_recall = sorted((f.id, f.content) for f in eng.recall_hybrid("budget", top_k=10))
    assert before_recall

    capsule = tmp_path / "capsule.tar.gz"
    cli.export_capsule(capsule)  # live-copy while the engine is still open
    eng.close()

    # wipe / destroy everything
    for base in (env.memory_db, env.index_db):
        for suffix in ("", "-wal", "-shm"):
            Path(str(base) + suffix).unlink(missing_ok=True)
    shutil.rmtree(env.vault)
    assert not env.memory_db.exists()

    cli.import_capsule(capsule)

    eng2 = MemoryEngine(env.memory_db)
    after_facts = sorted((f.id, f.content, f.domain) for f in eng2.list_facts())
    after_recall = sorted((f.id, f.content) for f in eng2.recall_hybrid("budget", top_k=10))
    eng2.close()

    assert after_facts == before_facts
    assert after_recall == before_recall
    # vault + index restored too
    assert (env.vault / "Knowledge" / "Note.md").read_text(encoding="utf-8") == (
        "# Note\n\nhello vault"
    )
    conn = sqlite3.connect(str(env.index_db))
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 1
    conn.close()


# ── AC2: malicious archive members rejected, nothing written outside ────────

def _capsule_with_member(env, tmp_path, member, data=b"pwned"):
    capsule = tmp_path / "evil.tar.gz"
    with tarfile.open(str(capsule), "w:gz") as tar:
        member.size = len(data)
        tar.addfile(member, io.BytesIO(data))
        manifest = json.dumps(
            {"version": 2, "exported_at": "2026-01-01T00:00:00", "has_vault": False}
        ).encode()
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))
    return capsule


def test_import_rejects_parent_traversal_member(env, tmp_path):
    capsule = _capsule_with_member(env, tmp_path, tarfile.TarInfo("../evil.txt"))
    with pytest.raises(ValueError, match="unsafe"):
        cli.import_capsule(capsule)
    assert not (env.ent / ".." / "evil.txt").resolve().exists()
    assert not (env.home / "evil.txt").exists()
    assert not env.memory_db.exists()


def test_import_rejects_symlink_member(env, tmp_path):
    member = tarfile.TarInfo("vault/link.txt")
    member.type = tarfile.SYMTYPE
    member.linkname = "/etc/passwd"
    capsule = _capsule_with_member(env, tmp_path, member)
    with pytest.raises(ValueError, match="unsafe"):
        cli.import_capsule(capsule)
    assert not (env.vault / "link.txt").exists()


def test_import_rejects_absolute_path_member(env, tmp_path):
    capsule = _capsule_with_member(env, tmp_path, tarfile.TarInfo("/tmp/evil-abs.txt"))
    with pytest.raises(ValueError, match="unsafe"):
        cli.import_capsule(capsule)
    assert not Path("/tmp/evil-abs.txt").exists()


# ── AC3: import refuses on lock file / running provider ─────────────────────

def test_import_refuses_when_lock_file_exists(env, tmp_path):
    capsule = _make_capsule(env, tmp_path)
    lock = env.memory_db.parent / MemoryEngine.MIGRATION_LOCK_FILENAME
    lock.write_text("pid=0\n", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="import refused"):
            cli.import_capsule(capsule)
    finally:
        lock.unlink()


def test_import_refuses_while_provider_running(env, tmp_path):
    import fcntl

    capsule = _make_capsule(env, tmp_path)
    lock_path = env.memory_db.parent / f"{env.memory_db.name}.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with pytest.raises(ValueError, match="import refused"):
            cli.import_capsule(capsule)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ── AC4: export archive contents + manifest v2 sha256s ──────────────────────

def test_export_archive_and_manifest_v2(env, tmp_path):
    eng = _seed(env)
    eng.migrate()
    eng.close()

    capsule = tmp_path / "capsule.tar.gz"
    cli.export_capsule(capsule)

    with tarfile.open(str(capsule), "r:gz") as tar:
        names = set(tar.getnames())
        assert {"memory.db", "index.db", "manifest.json", "vault/Knowledge/Note.md"} <= names
        manifest = json.loads(tar.extractfile("manifest.json").read())

        assert manifest["version"] == 2
        assert manifest["has_vault"] is True
        assert manifest["schema_versions"]["memory"]["schema_version"] == 1
        assert manifest["schema_versions"]["index"] is not None

        # per-file sha256s match the exported files in the archive
        assert set(manifest["files"]) == names - {"manifest.json"}
        for name, meta in manifest["files"].items():
            assert hashlib.sha256(tar.extractfile(name).read()).hexdigest() == meta["sha256"]


# ── AC5: _backup() retention ────────────────────────────────────────────────

def test_backup_retention_keeps_last_10_plus_daily(env):
    eng = MemoryEngine(env.memory_db)
    backup_dir = env.memory_db.parent / "backups"
    backup_dir.mkdir(exist_ok=True)

    today = datetime.now(timezone.utc).date()

    def seed(name, days_ago, hour, minute):
        ts = datetime(
            today.year, today.month, today.day, hour, minute, tzinfo=timezone.utc
        ) - timedelta(days=days_ago)
        path = backup_dir / name
        path.write_bytes(b"x")
        os.utime(path, (ts.timestamp(), ts.timestamp()))
        return path

    a = [seed(f"memory_a{i}.db", 0, 12, 5 * i) for i in range(1, 7)]  # today
    b = [seed(f"memory_b{i}.db", 1, 12, 5 * i) for i in range(1, 4)]  # 1 day ago
    c = [seed(f"memory_c{i}.db", 2, 12, 5 * i) for i in range(1, 3)]  # 2 days ago
    d = [seed(f"memory_d{i}.db", 3, 12, 5 * i) for i in range(1, 3)]  # 3 days ago
    e = [seed(f"memory_e{i}.db", 10, 12, 5 * i) for i in range(1, 3)]  # 10 days ago
    seeded = a + b + c + d + e
    assert len(seeded) > 10

    eng._backup()  # creates a fresh backup, then applies the retention policy

    survivors = {p.name for p in backup_dir.glob("memory_*.db")}
    fresh = survivors - {p.name for p in seeded}
    assert len(fresh) == 1  # the backup _backup() just created

    expected = {p.name for p in seeded} - {
        c[0].name,  # day-2: only the newest of the day survives
        d[0].name,  # day-3: only the newest of the day survives
        e[0].name,  # older than 7 days
        e[1].name,
    }
    assert survivors == expected | fresh
    # last-10 rule keeps every recent backup ...
    assert {p.name for p in a + b} <= survivors
    # ... and the daily rule keeps one per day for 7 days
    assert c[1].name in survivors and d[1].name in survivors
    eng.close()
