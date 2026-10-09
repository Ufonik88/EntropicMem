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
    assert info.path.name == "manual-20260926-030000-000", "3.1: one directory per snapshot"
    assert info.path.is_dir() and info.manifest_path.is_file()
    assert info.manifest_path == info.path / "manifest.json"
    assert not list(info.path.parent.glob("*.partial"))
    doc = json.loads(info.manifest_path.read_text())
    assert str(db.parent) not in info.manifest_path.read_text()
    assert doc["files"][0]["source"] == "memory.db", "the manifest records names, never paths"
    assert doc["files"][0]["counts"]["memories"] == 3
    assert doc["files"][0]["audit"]["ok"] is True and doc["files"][0]["audit"]["checked"] >= 3
    assert doc["files"][0]["user_version"] >= 2
    assert info.primary_path.name == "memory.db" and info.primary_path.is_file()
    assert mgr.verify(info).ok
    if os.name == "posix":
        assert oct(info.primary_path.stat().st_mode & 0o777) == "0o600"
        assert oct(info.manifest_path.stat().st_mode & 0o777) == "0o600"
        assert oct(info.path.parent.stat().st_mode & 0o777) == "0o700"


def test_two_backups_in_the_same_millisecond_do_not_collide(db):
    mgr = BackupManager(db)
    with clock.freeze(T0):
        a, b = mgr.create(), mgr.create()
    assert a.path != b.path and b.path.name.endswith("-2"), "the suffix is on the directory now"
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
    data = bytearray(info.primary_path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    info.primary_path.write_bytes(bytes(data))
    report = mgr.verify(info)
    assert not report.ok and "sha256" in " ".join(report.problems)

    info2 = mgr.create()
    info2.primary_path.write_bytes(info2.primary_path.read_bytes()[:4096])
    assert not mgr.verify(info2).ok

    info2.primary_path.unlink()
    assert mgr.verify(info2).problems == [f"missing file {info2.primary.name}"]


def test_verify_catches_a_manifest_that_lies(db):
    mgr = BackupManager(db)
    info = mgr.create()
    doc = json.loads(info.manifest_path.read_text())
    doc["files"][0]["counts"]["memories"] = 999
    info.manifest_path.write_text(json.dumps(doc))
    (loaded,) = mgr.list()
    assert any("row counts differ from manifest" in p for p in mgr.verify(loaded).problems)


def test_list_ignores_foreign_files_and_escaping_manifests(db):
    mgr = BackupManager(db)
    where = mgr.snapshot()
    (info,) = mgr.list()
    bdir = where.parent
    (bdir / "handmade-copy.db").write_bytes(info.primary_path.read_bytes())

    # A legacy manifest whose file points out of the backup directory.
    legacy = _legacy_backup(db, reason="manualx", stamp="20260926-010000-000")
    doc = json.loads(legacy.with_suffix(".json").read_text())
    doc["file"] = "../memory.db"
    legacy.with_suffix(".json").write_text(json.dumps(doc))

    # A 3.1 snapshot whose manifest names a file outside its own directory.
    escaping = bdir / "manual-20260926-010000-000-2"
    escaping.mkdir()
    evil = json.loads(info.manifest_path.read_text())
    evil["files"][0]["name"] = "../memory.db"
    (escaping / "manifest.json").write_text(json.dumps(evil))

    (bdir / "garbage.json").write_text("{not json")
    unreadable = bdir / "manual-20260926-010000-000-3"
    unreadable.mkdir()
    (unreadable / "manifest.json").write_text("{not json")
    assert [i.path for i in mgr.list()] == [where]


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
    assert len(removed) == 7 + 1, "one directory per removed snapshot"
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
    # Flip a byte rather than overwrite the last one: writing b"\x00" over an
    # already-zero final byte is not a tamper, and that is exactly what
    # happened once migration 0005 made the file end in zero.
    raw = bytearray(good.primary_path.read_bytes())
    raw[-1] ^= 0xFF
    good.primary_path.write_bytes(bytes(raw))
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

# --- Chunk 3.1: snapshot directories, both databases ------------------------


def _index_db(path: Path, *, notes: int = 2) -> Path:
    """A minimal sibling index database: real enough to inspect."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE notes_meta (id TEXT PRIMARY KEY, title TEXT)")
        conn.executemany(
            "INSERT INTO notes_meta (id, title) VALUES (?, ?)",
            [(f"note-{i}", f"Acme note {i}") for i in range(notes)],
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _user_version(path: Path) -> int:
    """``PRAGMA user_version`` with an explicit close.

    A leaked connection holds the ``-wal`` file open, which is invisible on
    POSIX (unlink succeeds on an open file) and fails on Windows with
    ``WinError 32`` the moment a restore tries to delete that WAL.
    """
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _table_counts(path: Path) -> dict:
    """Row counts the way the manifest records them (non-FTS tables)."""
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            " AND (sql IS NULL OR sql NOT LIKE 'CREATE VIRTUAL%') ORDER BY name"
        ).fetchall()
        return {
            name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            for (name,) in rows
            if "_fts" not in name
        }
    finally:
        conn.close()


def _legacy_backup(db: Path, *, reason: str = "legacy", stamp: str = "20260926-020000-000") -> Path:
    """Write the pre-3.1 flat layout by hand: ``<reason>-<stamp>.db`` + ``.json``.

    Built from the live file so the hashes and counts are real, and with
    ``format: 1`` so the test exercises the legacy reader rather than a
    hand-written shape the code happens to accept.
    """
    import hashlib

    bdir = db.parent / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    name = f"{reason}-{stamp}"
    blob = db.read_bytes()
    doc = {
        "format": 1,
        "file": f"{name}.db",
        "source": db.name,
        "reason": reason,
        "created_at": "2026-09-26T02:00:00.000+00:00",
        "sha256": hashlib.sha256(blob).hexdigest(),
        "size": len(blob),
        "user_version": _user_version(db),
        "counts": _table_counts(db),
        "audit": None,
    }
    (bdir / f"{name}.db").write_bytes(blob)
    (bdir / f"{name}.json").write_text(json.dumps(doc))
    return bdir / f"{name}.db"


@pytest.fixture
def db_with_index(tmp_path):
    mem = _v3_db(tmp_path / "memory.db")
    _index_db(tmp_path / "index.db")
    return mem


def test_snapshot_returns_a_directory_covering_both_databases(db_with_index):
    mgr = BackupManager(db_with_index)
    with clock.freeze(T0):
        where = mgr.snapshot(reason="manual")
    (info,) = mgr.list()
    assert where == info.path, "snapshot() returns the directory it wrote"
    assert where.is_dir() and where.parent == db_with_index.parent / "backups"
    assert where.name == "manual-20260926-030000-000"
    assert sorted(p.name for p in where.iterdir()) == ["index.db", "manifest.json", "memory.db"]
    assert [f.role for f in info.files] == ["memory", "index"]
    assert info.primary.counts["memories"] == 3
    assert info.files[1].counts["notes_meta"] == 2
    assert mgr.verify(info).ok
    doc = json.loads(info.manifest_path.read_text())
    assert doc["format"] == 2
    assert [entry["role"] for entry in doc["files"]] == ["memory", "index"]
    assert all(len(entry["sha256"]) == 64 for entry in doc["files"])
    assert str(db_with_index.parent) not in info.manifest_path.read_text()
    if os.name == "posix":
        assert oct(where.stat().st_mode & 0o777) == "0o700"
        assert oct((where / "memory.db").stat().st_mode & 0o777) == "0o600"
        assert oct(info.manifest_path.stat().st_mode & 0o777) == "0o600"


def test_snapshot_without_an_index_database_covers_memory_only(db):
    mgr = BackupManager(db)
    where = mgr.snapshot()
    (info,) = mgr.list()
    assert [f.role for f in info.files] == ["memory"]
    assert not (where / "index.db").exists()
    assert mgr.verify(info).ok


def test_index_path_can_be_given_explicitly(tmp_path, db):
    elsewhere = _index_db(tmp_path / "elsewhere" / "index.db", notes=1)
    mgr = BackupManager(db, index_path=elsewhere)
    mgr.snapshot()
    (info,) = mgr.list()
    assert [f.role for f in info.files] == ["memory", "index"]
    assert (info.path / "index.db").is_file()
    assert info.files[1].counts["notes_meta"] == 1


def test_a_snapshot_through_a_connection_covers_the_index_too(db_with_index):
    """Migrations pass their own connection; the index is still covered."""
    conn = open_db(db_with_index)
    try:
        BackupManager(db_with_index).snapshot(reason="pre-migrate-v2-to-v3", conn=conn)
    finally:
        conn.close()
    (info,) = BackupManager(db_with_index).list()
    assert [f.role for f in info.files] == ["memory", "index"]
    assert info.reason == "pre-migrate-v2-to-v3"


def test_verify_re_hashes_every_file_in_the_snapshot(db_with_index):
    mgr = BackupManager(db_with_index)
    mgr.snapshot()
    (info,) = mgr.list()
    index_copy = info.path / "index.db"
    data = bytearray(index_copy.read_bytes())
    data[len(data) // 2] ^= 0xFF
    index_copy.write_bytes(bytes(data))
    report = mgr.verify(info)
    assert not report.ok and any("sha256" in p for p in report.problems)


def test_verify_fails_when_a_snapshot_file_is_missing(db_with_index):
    mgr = BackupManager(db_with_index)
    mgr.snapshot()
    (info,) = mgr.list()
    (info.path / "index.db").unlink()
    report = mgr.verify(info)
    assert not report.ok and any("index.db" in p for p in report.problems)


def test_verify_fails_on_a_truncated_index_copy(db_with_index):
    mgr = BackupManager(db_with_index)
    mgr.snapshot()
    (info,) = mgr.list()
    index_copy = info.path / "index.db"
    index_copy.write_bytes(index_copy.read_bytes()[:1024])
    assert not mgr.verify(info).ok


def test_verify_fails_when_the_manifest_lies_about_the_index(db_with_index):
    mgr = BackupManager(db_with_index)
    mgr.snapshot()
    (info,) = mgr.list()
    doc = json.loads(info.manifest_path.read_text())
    doc["files"][1]["counts"]["notes_meta"] = 999
    info.manifest_path.write_text(json.dumps(doc))
    (loaded,) = mgr.list()
    assert not mgr.verify(loaded).ok


def test_two_snapshots_in_the_same_millisecond_do_not_collide(db):
    mgr = BackupManager(db)
    with clock.freeze(T0):
        first, second = mgr.snapshot(), mgr.snapshot()
    assert first != second and second.name == "manual-20260926-030000-000-2"
    assert len(mgr.list()) == 2


def test_a_failed_snapshot_leaves_no_directory_behind(tmp_path, db):
    """A snapshot with a database it cannot copy fails whole, not partly.

    Omitting the index would produce a backup that restores without it, which is
    exactly the surprise a backup must not have. The partial directory goes too.
    """
    (tmp_path / "index.db").write_bytes(b"this is not a database at all\n" * 200)
    with pytest.raises(sqlite3.DatabaseError):
        BackupManager(db).snapshot()
    assert list((db.parent / "backups").iterdir()) == []


def test_a_legacy_flat_backup_is_still_listed_verified_and_restorable(db):
    _legacy_backup(db)
    mgr = BackupManager(db)
    (info,) = mgr.list()
    assert info.flat is True and info.path.name.endswith(".db")
    assert mgr.verify(info).ok
    _add(db, "Globex was added after the legacy backup.")
    assert _memories(db) == 4
    mgr.restore(info)
    assert _memories(db) == 3


def test_rotation_counts_both_layouts_under_one_policy(db):
    mgr = BackupManager(db)
    _legacy_backup(db, reason="manual")
    for i in range(3):
        with clock.freeze(T0 + timedelta(minutes=i)):
            mgr.snapshot(reason="scheduled")
    removed = mgr.rotate(keep=2, keep_safety=1)
    assert [i.reason for i in mgr.list()] == ["scheduled", "scheduled"]
    assert len(removed) == 3, "one directory for the snapshot, .db and .json for the legacy one"
    assert not list(mgr.backup_dir.glob("manual-*.db"))
    assert not list(mgr.backup_dir.glob("manual-*.json"))


def test_restore_round_trips_both_databases(db_with_index):
    mgr = BackupManager(db_with_index)
    mgr.snapshot()
    (good,) = mgr.list()
    _add(db_with_index, "Initech was added after the snapshot.")
    index_path = db_with_index.parent / "index.db"
    conn = sqlite3.connect(index_path)
    try:
        conn.execute("INSERT INTO notes_meta (id, title) VALUES ('late', 'added after')")
        conn.commit()
    finally:
        conn.close()

    mgr.restore(good)
    assert _memories(db_with_index) == 3
    assert _table_counts(index_path)["notes_meta"] == 2, "the index came back too"
    conn = sqlite3.connect(index_path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_restore_leaves_an_existing_index_alone_when_the_snapshot_has_none(db):
    mgr = BackupManager(db)
    mgr.snapshot()
    (good,) = mgr.list()
    index_path = db.parent / "index.db"
    _index_db(index_path, notes=4)
    before = index_path.read_bytes()
    mgr.restore(good)
    assert index_path.read_bytes() == before, "a snapshot without an index must not touch one"


# --- Chunk 3.2: the once-per-hour-per-reason throttle -----------------------

#: ``_legacy_backup`` stamps its manifest at 02:00 on ``T0``'s day.
LEGACY_AT = datetime(2026, 9, 26, 2, 0, 0, tzinfo=timezone.utc)


def test_a_hundred_calls_inside_one_hour_write_one_snapshot(db):
    """EM-210's acceptance criterion: 100 ``forget`` calls -> <= 1 snapshot/hour."""
    mgr = BackupManager(db)
    with clock.freeze(T0):
        written = [mgr.snapshot_if_due(reason="forget") for _ in range(100)]
    assert [p for p in written if p is not None] == [written[0]]
    assert written[0].is_dir() and (written[0] / "manifest.json").is_file()
    assert [i.reason for i in mgr.list()] == ["forget"]


def test_the_next_hour_writes_one_more(db):
    mgr = BackupManager(db)
    with clock.freeze(T0):
        assert mgr.snapshot_if_due(reason="forget") is not None
        assert mgr.snapshot_if_due(reason="forget") is None
    with clock.freeze(T0 + timedelta(hours=1)):
        assert mgr.snapshot_if_due(reason="forget") is not None
        assert mgr.snapshot_if_due(reason="forget") is None, "and then goes quiet again"
    assert len(mgr.list()) == 2


def test_reasons_keep_independent_windows(db):
    mgr = BackupManager(db)
    with clock.freeze(T0):
        assert mgr.snapshot_if_due(reason="forget") is not None
        assert mgr.snapshot_if_due(reason="forget") is None
        assert mgr.snapshot_if_due(reason="prune") is not None, "another reason has its own window"
        assert mgr.snapshot_if_due(reason="prune") is None
    assert sorted(i.reason for i in mgr.list()) == ["forget", "prune"]


def test_a_snapshot_older_than_the_window_is_allowed_again(db):
    mgr = BackupManager(db)
    with clock.freeze(T0):
        assert mgr.snapshot_if_due(reason="forget", window=60) is not None
    with clock.freeze(T0 + timedelta(seconds=59)):
        assert mgr.snapshot_if_due(reason="forget", window=60) is None
    with clock.freeze(T0 + timedelta(seconds=61)):
        assert mgr.snapshot_if_due(reason="forget", window=60) is not None
    assert len(mgr.list()) == 2


def test_moving_the_clock_backwards_does_not_write_a_second_snapshot(db):
    mgr = BackupManager(db)
    with clock.freeze(T0):
        assert mgr.snapshot_if_due(reason="forget") is not None
    with clock.freeze(T0 - timedelta(minutes=5)):
        assert mgr.snapshot_if_due(reason="forget") is None
    assert len(mgr.list()) == 1


def test_safety_reasons_are_never_throttled(db):
    """A migration or a restore is deliberate and rare, so it always snapshots.

    A stale ``pre-restore`` copy is a data risk, not noise: the window does not
    apply to ``SAFETY_PREFIXES``.
    """
    mgr = BackupManager(db)
    with clock.freeze(T0):
        assert mgr.snapshot_if_due(reason="pre-restore") is not None
        assert mgr.snapshot_if_due(reason="pre-restore") is not None
        assert mgr.snapshot_if_due(reason="pre-migrate-v2-to-v3") is not None
    assert sorted(i.reason for i in mgr.list()) == [
        "pre-migrate-v2-to-v3",
        "pre-restore",
        "pre-restore",
    ]


def test_a_zero_window_never_throttles(db):
    mgr = BackupManager(db)
    with clock.freeze(T0):
        for _ in range(3):
            assert mgr.snapshot_if_due(reason="forget", window=0) is not None
    with clock.freeze(T0 - timedelta(minutes=5)):
        assert mgr.snapshot_if_due(reason="forget", window=0) is not None, "even behind the clock"
    assert len(mgr.list()) == 4


def test_a_legacy_flat_snapshot_counts_toward_the_window(db):
    _legacy_backup(db, reason="forget")
    mgr = BackupManager(db)
    with clock.freeze(LEGACY_AT + timedelta(minutes=30)):
        assert mgr.snapshot_if_due(reason="forget") is None
    assert len(mgr.list()) == 1 and mgr.list()[0].flat is True


def test_an_unreadable_timestamp_does_not_block_a_real_snapshot(db):
    mgr = BackupManager(db)
    with clock.freeze(T0):
        assert mgr.snapshot_if_due(reason="forget") is not None
        (info,) = mgr.list()
        doc = json.loads(info.manifest_path.read_text())
        doc["created_at"] = "not a timestamp"
        info.manifest_path.write_text(json.dumps(doc))
        assert mgr.snapshot_if_due(reason="forget") is not None
    assert len(mgr.list()) == 2


def test_snapshot_and_create_stay_unthrottled(db):
    """The migration hook, the daily job and the tests always get a snapshot."""
    mgr = BackupManager(db)
    with clock.freeze(T0):
        assert mgr.snapshot(reason="scheduled") is not None
        assert mgr.create(reason="scheduled") is not None
        assert mgr.snapshot(reason="scheduled") is not None
    assert len(mgr.list()) == 3

