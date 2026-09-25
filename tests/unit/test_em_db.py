"""EM-202 unit tests for ``em.store.db`` — v3 connection management.

Covers the card spec: pragma set, readonly URI, POSIX perms, write_txn
commit/rollback/BUSY-retry, the user_version schema fast path, the portable
(O_CREAT|O_EXCL) migration lock with 10-minute staleness, and the
thread-local reader / single-writer connection caches.

The multiprocessing concurrency AC (4 writers x 500 + reader p95 < 50 ms)
lives in ``tests/unit/test_em_store_concurrency.py`` (spawn-safe, runs on
the Windows CI job too).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "entropicmem" / "scripts"))

from em.store import db as emdb  # noqa: E402

# ── open_db: pragmas, modes, perms ──────────────────────────────────────────


def test_open_db_pragmas(tmp_path):
    conn = emdb.open_db(tmp_path / "m.db")
    try:
        def pragma(name):
            return conn.execute(f"PRAGMA {name}").fetchone()[0]

        assert pragma("journal_mode") == "wal"
        assert pragma("synchronous") == 1  # NORMAL
        assert pragma("busy_timeout") == 5000
        assert pragma("foreign_keys") == 1
        assert pragma("temp_store") == 2  # MEMORY
        assert pragma("mmap_size") == 64 * 1024 * 1024
        # explicit transactions only
        assert conn.isolation_level is None
    finally:
        conn.close()


def test_open_db_creates_parent_dirs(tmp_path):
    deep = tmp_path / "a" / "b" / "m.db"
    conn = emdb.open_db(deep)
    conn.close()
    assert deep.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_open_db_posix_perms(tmp_path):
    path = tmp_path / "sub" / "m.db"
    conn = emdb.open_db(path)
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.close()
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_open_db_readonly(tmp_path):
    path = tmp_path / "m.db"
    w = emdb.open_db(path)
    w.execute("CREATE TABLE t (x)")
    w.execute("INSERT INTO t VALUES (42)")
    w.close()

    ro = emdb.open_db(path, readonly=True)
    try:
        assert ro.execute("SELECT x FROM t").fetchone()[0] == 42
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO t VALUES (1)")
    finally:
        ro.close()


def test_open_db_readonly_missing_file_raises(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        emdb.open_db(tmp_path / "nope.db", readonly=True)


def test_open_db_readonly_after_clean_close(tmp_path):
    """A cleanly closed WAL DB (checkpointed, no -wal/-shm left) is still
    readable through a readonly handle."""
    path = tmp_path / "m.db"
    w = emdb.open_db(path)
    w.execute("CREATE TABLE t (x)")
    w.execute("INSERT INTO t VALUES (7)")
    w.close()
    assert not (tmp_path / "m.db-wal").exists()
    assert not (tmp_path / "m.db-shm").exists()
    ro = emdb.open_db(path, readonly=True)
    assert ro.execute("SELECT x FROM t").fetchone()[0] == 7
    ro.close()


# ── write_txn ───────────────────────────────────────────────────────────────


def test_write_txn_commits(tmp_path):
    conn = emdb.open_db(tmp_path / "m.db")
    conn.execute("CREATE TABLE t (x)")
    with emdb.write_txn(conn):
        conn.execute("INSERT INTO t VALUES (1)")
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    conn.close()


def test_write_txn_rolls_back_on_exception(tmp_path):
    conn = emdb.open_db(tmp_path / "m.db")
    conn.execute("CREATE TABLE t (x)")
    with pytest.raises(RuntimeError):
        with emdb.write_txn(conn):
            conn.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 0
    # connection still usable afterwards
    with emdb.write_txn(conn):
        conn.execute("INSERT INTO t VALUES (2)")
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 2
    conn.close()


class _TxnProxy:
    """Duck-typed connection proxy: lets tests fail specific ``execute``
    calls (sqlite3.Connection is a C type and cannot be monkeypatched)."""

    def __init__(self, conn, fail_first_n=0, fail_all=False, match="BEGIN"):
        self._conn = conn
        self._fail_first_n = fail_first_n
        self._fail_all = fail_all
        self._match = match
        self._n = 0

    def execute(self, sql, *a, **kw):
        if self._match in sql.strip().upper() and (
            self._fail_all or self._n < self._fail_first_n
        ):
            self._n += 1
            raise sqlite3.OperationalError("database is locked")
        return self._conn.execute(sql, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_write_txn_retries_busy_then_succeeds(tmp_path, monkeypatch):
    """SQLITE_BUSY on BEGIN IMMEDIATE is retried up to 3x with jitter."""
    conn = emdb.open_db(tmp_path / "m.db")
    conn.execute("CREATE TABLE t (x)")
    proxy = _TxnProxy(conn, fail_first_n=2)
    monkeypatch.setattr(time, "sleep", lambda s: None)  # no real jitter wait
    with emdb.write_txn(proxy):
        proxy.execute("INSERT INTO t VALUES (1)")
    assert proxy._n == 2
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    conn.close()


def test_write_txn_gives_up_after_three_busy(tmp_path, monkeypatch):
    conn = emdb.open_db(tmp_path / "m.db")
    conn.execute("CREATE TABLE t (x)")
    proxy = _TxnProxy(conn, fail_all=True)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        with emdb.write_txn(proxy):
            pass
    assert proxy._n == 4  # 1 initial attempt + 3 retries
    conn.close()


def test_write_txn_does_not_retry_non_busy_errors(tmp_path):
    conn = emdb.open_db(tmp_path / "m.db")
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        with emdb.write_txn(conn):
            conn.execute("INSERT INTO missing VALUES (1)")
    conn.close()


# ── schema fast path (user_version) ─────────────────────────────────────────


def test_ensure_schema_fast_path_skips_migrate(tmp_path):
    conn = emdb.open_db(tmp_path / "m.db")
    conn.execute(f"PRAGMA user_version = {emdb.LATEST_USER_VERSION}")
    called = []
    assert emdb.ensure_schema(conn, migrate=lambda c: called.append(c)) is False
    assert called == []
    conn.close()


def test_ensure_schema_runs_migrate_under_lock(tmp_path):
    conn = emdb.open_db(tmp_path / "m.db")
    lock_dir = tmp_path

    def migrate(c):
        # the migration lock file exists while migrate() runs
        assert (lock_dir / emdb.MIGRATION_LOCK_NAME).exists()
        c.execute("PRAGMA user_version = 1")

    assert emdb.ensure_schema(conn, migrate=migrate, lock_dir=lock_dir, latest=1) is True
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    # lock released after migration
    assert not (lock_dir / emdb.MIGRATION_LOCK_NAME).exists()
    conn.close()


def test_ensure_schema_refuses_downgrade(tmp_path):
    conn = emdb.open_db(tmp_path / "m.db")
    conn.execute("PRAGMA user_version = 2")
    with pytest.raises(emdb.DowngradeError, match="downgrade"):
        emdb.ensure_schema(conn, migrate=lambda c: None, latest=1)
    conn.close()


def test_ensure_schema_migrates_only_once(tmp_path):
    """Second call sees user_version == latest and skips (fast path)."""
    conn = emdb.open_db(tmp_path / "m.db")
    calls = []

    def migrate(c):
        calls.append(1)
        c.execute("PRAGMA user_version = 1")

    assert emdb.ensure_schema(conn, migrate=migrate, lock_dir=tmp_path, latest=1) is True
    assert emdb.ensure_schema(conn, migrate=migrate, lock_dir=tmp_path, latest=1) is False
    assert len(calls) == 1
    conn.close()


def test_ensure_schema_in_memory_needs_no_lock_dir(tmp_path):
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA user_version = 0")
    ran = []

    def migrate(c):
        ran.append(True)
        c.execute("PRAGMA user_version = 1")

    assert emdb.ensure_schema(conn, migrate=migrate, latest=1) is True
    assert ran == [True]
    assert not (tmp_path / emdb.MIGRATION_LOCK_NAME).exists()
    conn.close()


# ── migration lock file: O_CREAT|O_EXCL + staleness ─────────────────────────


def test_migration_lock_is_exclusive(tmp_path):
    with emdb.migration_lock(tmp_path) as first:
        assert first is True
        with pytest.raises(emdb.MigrationLockHeld):
            with emdb.migration_lock(tmp_path):
                pass
    assert not (tmp_path / emdb.MIGRATION_LOCK_NAME).exists()


def test_migration_lock_stale_after_ten_minutes(tmp_path):
    lock_path = tmp_path / emdb.MIGRATION_LOCK_NAME
    lock_path.write_text("pid=999999\n", encoding="utf-8")
    old = time.time() - (10 * 60 + 60)
    os.utime(lock_path, (old, old))
    # stale lock is taken over, not refused
    with emdb.migration_lock(tmp_path) as got:
        assert got is True
    assert not lock_path.exists()


def test_migration_lock_fresh_is_held(tmp_path):
    lock_path = tmp_path / emdb.MIGRATION_LOCK_NAME
    lock_path.write_text("pid=999999\n", encoding="utf-8")
    with pytest.raises(emdb.MigrationLockHeld):
        with emdb.migration_lock(tmp_path):
            pass
    assert lock_path.exists()  # not stolen


# ── Store: thread-local readers, one writer per process ────────────────────


def test_store_reader_is_thread_local(tmp_path):
    store = emdb.Store(tmp_path / "m.db")
    try:
        main_conn = store.reader()
        other: list = []

        def _in_thread():
            other.append(store.reader())

        t = threading.Thread(target=_in_thread)
        t.start()
        t.join()
        assert other[0] is not main_conn
        assert store.reader() is main_conn  # stable within a thread
    finally:
        store.close()


def test_store_writer_is_single_per_process(tmp_path):
    store = emdb.Store(tmp_path / "m.db")
    try:
        w1 = store.writer()
        w2 = store.writer()
        assert w1 is w2
        seen: list = []

        def _in_thread():
            seen.append(store.writer())

        t = threading.Thread(target=_in_thread)
        t.start()
        t.join()
        assert seen[0] is w1  # same writer across threads
    finally:
        store.close()


def test_store_writer_lock_serialises_threads(tmp_path):
    """The writer lock is held for the duration of a write_txn done through
    Store.transaction() — two threads never interleave inside a txn."""
    store = emdb.Store(tmp_path / "m.db")
    store.writer().execute("CREATE TABLE t (x)")
    order: list = []
    barrier = threading.Barrier(2, timeout=5)

    def _work(tag):
        barrier.wait()
        with store.transaction():
            order.append(f"{tag}:begin")
            time.sleep(0.05)
            order.append(f"{tag}:end")

    threads = [threading.Thread(target=_work, args=(i,)) for i in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # no interleaving: begin/end pairs are adjacent
    assert order[0].endswith(":begin") and order[1].endswith(":end")
    assert order[0][0] == order[1][0]
    assert order[2].endswith(":begin") and order[3].endswith(":end")
    store.close()


def test_store_close_is_idempotent(tmp_path):
    store = emdb.Store(tmp_path / "m.db")
    store.reader()
    store.writer()
    store.close()
    store.close()  # must not raise
