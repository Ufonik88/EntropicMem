"""EM-210: backup manager (``em.store.backup``)."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em import clock  # noqa: E402
from em.jobs import HandlerRegistry, JobWorker  # noqa: E402
from em.store import audit as em_audit  # noqa: E402
from em.store.backup import (  # noqa: E402
    BACKUP_JOB_TYPE,
    BackupManager,
    BackupVerificationError,
    RestoreRefused,
    enqueue_daily_backup,
    make_backup_handler,
)
from em.store.db import Store, open_db  # noqa: E402
from em.store.jobs import JobQueue  # noqa: E402
from em.store.locking import FileLock  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

T0 = datetime(2026, 9, 26, 3, 0, 0, tzinfo=timezone.utc)
SCOPE = Scope(profile="default", user="")


def _v3_db(path: Path, n: int = 3) -> Path:
    s = Store(str(path))
    try:
        with s.writer() as conn:
            migrate(conn, backup_dir=path.parent / "migrate-backups")
        with s.transaction() as conn:
            ms = MemoryStore(conn)
            for i in range(n):
                ms.add(MemoryDraft(content=f"Acme widget fact number {i}."), scope=SCOPE, actor="t")
    finally:
        s.close()
    return path


def _add(path: Path, content: str) -> None:
    s = Store(str(path))
    try:
        with s.transaction() as conn:
            MemoryStore(conn).add(MemoryDraft(content=content), scope=SCOPE, actor="t")
    finally:
        s.close()


def _memories(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT count(*) FROM memories").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def db(tmp_path):
    return _v3_db(tmp_path / "memory.db")


# --- create ----------------------------------------------------------------


def test_create_writes_a_verified_backup_and_manifest(db):
    mgr = BackupManager(db)
    with clock.freeze(T0):
        info = mgr.create()
    assert info.path.parent == db.parent / "backups"
    assert info.path.name == "manual-20260926-030000-000.db"
    assert info.path.is_file() and info.manifest_path.is_file()
    assert not list(info.path.parent.glob("*.partial"))
    doc = json.loads(info.manifest_path.read_text())
    assert doc["source"] == "memory.db", "manifest must not carry the full source path"
    assert str(db.parent) not in info.manifest_path.read_text()
    assert doc["counts"]["memories"] == 3
    assert doc["audit"]["ok"] is True and doc["audit"]["checked"] >= 3
    assert doc["user_version"] >= 2
    assert mgr.verify(info).ok
    if os.name == "posix":
        assert oct(info.path.stat().st_mode & 0o777) == "0o600"
        assert oct(info.manifest_path.stat().st_mode & 0o777) == "0o600"
        assert oct(info.path.parent.stat().st_mode & 0o777) == "0o700"


def test_two_backups_in_the_same_millisecond_do_not_collide(db):
    mgr = BackupManager(db)
    with clock.freeze(T0):
        a, b = mgr.create(), mgr.create()
    assert a.path != b.path and b.path.name.endswith("-2.db")
    assert len(mgr.list()) == 2


def test_snapshot_includes_commits_still_in_the_wal(db):
    """The backup API sees WAL-resident commits; a plain file copy would not."""
    writer = open_db(db)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    try:
        _add(db, "Globex joined late.")
        assert (db.parent / "memory.db-wal").stat().st_size > 0
        info = BackupManager(db).create()
    finally:
        writer.close()
    assert info.counts["memories"] == 4


def test_a_backup_that_fails_verification_is_not_kept(db):
    conn = sqlite3.connect(db)
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute("UPDATE audit_log SET action='forged' WHERE seq=(SELECT max(seq) FROM audit_log)")
    conn.commit()
    conn.close()
    mgr = BackupManager(db)
    with pytest.raises(BackupVerificationError, match="audit chain"):
        mgr.create()
    assert list((db.parent / "backups").iterdir()) == []


@pytest.mark.parametrize("reason", ["", "Has Caps", "../x", "a" * 65, "spaces here"])
def test_reason_is_validated(db, reason):
    with pytest.raises(ValueError):
        BackupManager(db).create(reason=reason)


def test_create_without_a_database_fails(tmp_path):
    with pytest.raises(Exception, match="no database"):
        BackupManager(tmp_path / "missing.db").create()


# --- verify / list ---------------------------------------------------------


def test_verify_catches_bit_rot_and_truncation(db):
    mgr = BackupManager(db)
    info = mgr.create()
    data = bytearray(info.path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    info.path.write_bytes(bytes(data))
    report = mgr.verify(info)
    assert not report.ok and "sha256" in " ".join(report.problems)

    info2 = mgr.create()
    info2.path.write_bytes(info2.path.read_bytes()[:4096])
    assert not mgr.verify(info2).ok

    info2.path.unlink()
    assert mgr.verify(info2).problems == [f"missing file {info2.path.name}"]


def test_verify_catches_a_manifest_that_lies(db):
    mgr = BackupManager(db)
    info = mgr.create()
    doc = json.loads(info.manifest_path.read_text())
    doc["counts"]["memories"] = 999
    info.manifest_path.write_text(json.dumps(doc))
    (loaded,) = mgr.list()
    assert "row counts differ from manifest" in mgr.verify(loaded).problems


def test_list_ignores_foreign_files_and_escaping_manifests(db):
    mgr = BackupManager(db)
    real = mgr.create()
    bdir = real.path.parent
    (bdir / "handmade-copy.db").write_bytes(real.path.read_bytes())
    doc = json.loads(real.manifest_path.read_text())
    doc["file"] = "../memory.db"
    (bdir / "evil.json").write_text(json.dumps(doc))
    (bdir / "garbage.json").write_text("{not json")
    assert [i.path for i in mgr.list()] == [real.path]


# --- rotate ----------------------------------------------------------------


def test_rotation_keeps_safety_backups_on_their_own_limit(db):
    mgr = BackupManager(db)
    for i in range(3):
        with clock.freeze(T0 + timedelta(minutes=i)):
            mgr.create(reason="pre-migrate-v2-to-v3")
    for i in range(10):
        with clock.freeze(T0 + timedelta(hours=1, minutes=i)):
            mgr.create(reason="scheduled")
    foreign = mgr.backup_dir / "handmade-copy.db"
    foreign.write_bytes(b"not ours")

    removed = mgr.rotate(keep=3, keep_safety=2)
    left = mgr.list()
    assert [i.reason for i in left].count("scheduled") == 3
    assert [i.reason for i in left].count("pre-migrate-v2-to-v3") == 2
    assert min(i.created_at for i in left if i.reason == "scheduled") == clock.to_iso(
        T0 + timedelta(hours=1, minutes=7)
    )
    assert len(removed) == 2 * (7 + 1)  # .db + .json each
    assert foreign.exists(), "rotation must never delete a file it did not write"
    with pytest.raises(ValueError):
        mgr.rotate(keep=0)


# --- restore ---------------------------------------------------------------


def test_restore_round_trip_with_a_pre_restore_safety_copy(db):
    mgr = BackupManager(db)
    good = mgr.create()
    _add(db, "Initech was added after.")
    assert _memories(db) == 4

    safety = mgr.restore(good)
    assert _memories(db) == 3
    assert safety is not None and safety.reason == "pre-restore"
    assert safety.counts["memories"] == 4
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert em_audit.verify(conn).ok
    finally:
        conn.close()


def test_restore_never_replays_the_old_databases_wal(db):
    """A WAL left by the replaced database (valid frames, e.g. after a crash)
    would be replayed onto the restored file, silently reviving rows the
    restore was meant to remove. Restore must delete it before the swap."""
    mgr = BackupManager(db)
    good = mgr.create()
    writer = open_db(db)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    _add(db, "Initech was added after.")
    wal = db.parent / "memory.db-wal"
    frames = wal.read_bytes()
    assert frames, "expected un-checkpointed WAL frames"
    writer.close()
    wal.write_bytes(frames)  # as if the process had crashed before checkpointing

    mgr.restore(good)
    assert not wal.exists() or wal.stat().st_size == 0 or _memories(db) == 3
    assert _memories(db) == 3
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_restore_still_works_when_the_live_database_is_broken(db):
    """Restore exists for the day the live DB is broken. If it cannot be
    snapshotted, its raw files are kept byte for byte and restore proceeds."""
    mgr = BackupManager(db)
    good = mgr.create()
    garbage = os.urandom(8192)
    db.write_bytes(garbage)

    kept = mgr.restore(good)
    assert isinstance(kept, Path) and kept.is_dir()
    assert kept.name.startswith("pre-restore-raw-")
    assert (kept / "memory.db").read_bytes() == garbage
    assert _memories(db) == 3


def test_restore_refuses_a_non_test_path_and_touches_nothing(tmp_path, db):
    """The development guard: outside temp/test locations restore needs
    ``allow_live=True``.

    Never point this test at the real ``~/.hermes/entropicmem``: when the guard
    is mutated away (or regresses), the restore would then really run against
    the live store. Use a unique, non-existent directory under the home
    directory instead, which the guard refuses for the same reason, and clean
    up whatever a regression might create.
    """
    import shutil
    import uuid

    from em.store.migrations import MigrationRefused, assert_safe_db_path

    target_dir = Path.home() / f".em-restore-guard-{uuid.uuid4().hex}"
    target = target_dir / "memory.db"
    try:
        assert_safe_db_path(target)
    except MigrationRefused:
        pass
    else:
        pytest.skip("home directory is inside a temp/test location here")
    good = BackupManager(db).create()
    try:
        with pytest.raises(RestoreRefused, match="allow_live"):
            BackupManager(target, backup_dir=tmp_path / "b").restore(good)
        assert not target_dir.exists(), "a refused restore must not create anything"
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_restore_refuses_while_the_provider_holds_the_lock(db):
    mgr = BackupManager(db)
    good = mgr.create()
    lock = FileLock(db.parent / "memory.db.lock")
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(RestoreRefused, match="provider is running"):
            mgr.restore(good)
    finally:
        lock.close()
    assert [i.reason for i in mgr.list()] == ["manual"], "no safety copy when refused"


def test_restore_refuses_a_tampered_backup(db):
    mgr = BackupManager(db)
    good = mgr.create()
    good.path.write_bytes(good.path.read_bytes()[:-1] + b"\x00")
    with pytest.raises(RestoreRefused, match="verification"):
        mgr.restore(good)
    assert _memories(db) == 3


def test_restore_onto_a_missing_database(tmp_path, db):
    good = BackupManager(db).create()
    target = tmp_path / "fresh" / "memory.db"
    assert BackupManager(target, backup_dir=tmp_path / "b").restore(good) is None
    assert _memories(target) == 3


# --- migration + job integration --------------------------------------------


def test_migration_backups_are_verified_and_manifested(tmp_path):
    db = _v3_db(tmp_path / "memory.db", n=0)
    mgr = BackupManager(db, backup_dir=tmp_path / "migrate-backups")
    (info,) = mgr.list()
    assert info.reason.startswith("pre-migrate-v0-to-v")
    assert info.is_safety and mgr.verify(info).ok


def test_daily_backup_job_is_deduped_and_idempotent(db):
    store = Store(str(db))
    mgr = BackupManager(db)
    reg = HandlerRegistry()
    reg.register(BACKUP_JOB_TYPE, make_backup_handler(mgr, keep=3))
    try:
        with clock.freeze(T0):
            with store.transaction() as conn:
                a = enqueue_daily_backup(JobQueue(conn))
                b = enqueue_daily_backup(JobQueue(conn))
            assert a == b
            (outcome,) = JobWorker(store, reg).run_until_idle()
            assert outcome.status == "done"
            # A re-run of the same day (lost lease) must not add a second copy.
            job = JobQueue(store.reader()).get(a)
            make_backup_handler(mgr)(job, None)
        assert [i.reason for i in mgr.list()] == ["scheduled"]
        with clock.freeze(T0 + timedelta(days=1)):
            with store.transaction() as conn:
                assert enqueue_daily_backup(JobQueue(conn)) != a
    finally:
        store.close()
