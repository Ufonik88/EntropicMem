"""EM-202 acceptance: cross-process concurrency on the v3 store.

Card AC: "concurrency test: 4 writer processes × 500 writes + 1 reader →
no errors, reader p95 < 50 ms."

Cross-process serialisation is SQLite's (BEGIN IMMEDIATE + busy_timeout +
WAL), NOT an advisory file lock — this test is the proof. It runs on the
Windows CI job too, so workers are top-level functions and the start method
is forced to ``spawn`` (the Windows default) everywhere.
"""

from __future__ import annotations

import multiprocessing
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "entropicmem" / "scripts"))

WRITERS = 4
WRITES_EACH = 500


def _writer(db_path: str, tag: int, out_q) -> None:  # spawn-safe: top-level
    from em.store.db import open_db, write_txn

    try:
        conn = open_db(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS t "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, tag INT, seq INT)"
        )
        for i in range(WRITES_EACH):
            with write_txn(conn):
                conn.execute("INSERT INTO t (tag, seq) VALUES (?, ?)", (tag, i))
        conn.close()
        out_q.put(("ok", tag))
    except Exception as exc:  # noqa: BLE001 - report anything, assert in parent
        out_q.put(("err", f"{tag}: {type(exc).__name__}: {exc}"))


def _reader(db_path: str, stop_evt, lat_q) -> None:  # spawn-safe: top-level
    from em.store.db import open_db

    latencies: list = []
    try:
        conn = open_db(db_path, readonly=True)
    except sqlite3.OperationalError:
        # DB file may not exist yet; wait for the first writer to create it.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                conn = open_db(db_path, readonly=True)
                break
            except sqlite3.OperationalError:
                time.sleep(0.05)
        else:
            lat_q.put(("err", "reader: db never appeared"))
            return
    while not stop_evt.is_set():
        t0 = time.perf_counter()
        conn.execute("SELECT count(*) FROM t").fetchone()
        latencies.append((time.perf_counter() - t0) * 1000)
        time.sleep(0.001)
    conn.close()
    lat_q.put(("ok", latencies))


def test_four_writer_processes_plus_reader(tmp_path):
    db_path = tmp_path / "m.db"
    # Pre-create the schema so the readonly reader can open immediately.
    from em.store.db import open_db

    w = open_db(db_path)
    w.execute("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, tag INT, seq INT)")
    w.close()

    ctx = multiprocessing.get_context("spawn")
    out_q = ctx.Queue()
    lat_q = ctx.Queue()
    stop_evt = ctx.Event()

    reader = ctx.Process(target=_reader, args=(str(db_path), stop_evt, lat_q))
    reader.start()
    writers = [
        ctx.Process(target=_writer, args=(str(db_path), i, out_q)) for i in range(WRITERS)
    ]
    for p in writers:
        p.start()
    for p in writers:
        p.join(timeout=120)
    stop_evt.set()
    reader.join(timeout=30)

    results = [out_q.get(timeout=5) for _ in range(WRITERS)]
    errors = [r for r in results if r[0] != "ok"]
    assert not errors, f"writer errors: {errors}"
    assert all(p.exitcode == 0 for p in writers)
    assert reader.exitcode == 0

    status, latencies = lat_q.get(timeout=5)
    assert status == "ok", latencies

    # all writes landed, no lost updates
    conn = open_db(db_path, readonly=True)
    total = conn.execute("SELECT count(*) FROM t").fetchone()[0]
    per_writer = conn.execute(
        "SELECT count(DISTINCT tag) FROM t"
    ).fetchone()[0]
    conn.close()
    assert total == WRITERS * WRITES_EACH
    assert per_writer == WRITERS

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    assert p95 < 50.0, f"reader p95 {p95:.2f} ms exceeds 50 ms budget"


def test_ensure_schema_fails_fast_while_migration_lock_held(tmp_path):
    """A second migrator finds a fresh O_EXCL lock and raises
    MigrationLockHeld instead of migrating twice or corrupting state.
    Deterministic: the lock is held by this test, no thread race."""
    from em.store.db import MigrationLockHeld, ensure_schema, migration_lock, open_db

    db_path = tmp_path / "m.db"
    conn = open_db(db_path)
    calls = []

    def migrate(c):
        calls.append(1)
        c.execute("PRAGMA user_version = 1")

    with migration_lock(tmp_path):
        with pytest.raises(MigrationLockHeld):
            ensure_schema(conn, migrate, lock_dir=tmp_path, latest=1)
    assert calls == []  # never ran
    # lock released: migration now succeeds exactly once
    assert ensure_schema(conn, migrate, lock_dir=tmp_path, latest=1) is True
    assert calls == [1]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    conn.close()
