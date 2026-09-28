"""EM-209 CLI: ``entropicmem worker run``.

The worker core already exists. This command is the missing entry point.
It must not migrate, and it must not create or touch a non-test database.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
FIXTURES = REPO / "tests" / "fixtures" / "db"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.store.backup import BackupManager  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.jobs import JobQueue  # noqa: E402
from em.store.migrations import MigrationRefused, assert_safe_db_path, migrate  # noqa: E402


def _v3_db(path: Path) -> Path:
    store = Store(str(path))
    try:
        with store.writer() as conn:
            migrate(conn, backup_dir=path.parent / "migrate-backups")
    finally:
        store.close()
    return path


def _enqueue(path: Path, *, dedupe_key: str, day: str) -> str:
    store = Store(str(path))
    try:
        with store.transaction() as conn:
            return JobQueue(conn).enqueue(
                "backup",
                {"day": day},
                dedupe_key=dedupe_key,
            )
    finally:
        store.close()


def _statuses(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT status FROM jobs ORDER BY created_at, id")]
    finally:
        conn.close()


def _cli(db: Path, *args: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ENTROPICMEM_")}
    env["ENTROPICMEM_MEMORY_DB"] = str(db)
    env.pop("ENTROPICMEM_ALLOW_LIVE_MIGRATION", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "entropicmem.py"), "worker", "run", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_worker_run_executes_one_backup_and_reports_done(tmp_path):
    db = _v3_db(tmp_path / "memory.db")
    _enqueue(db, dedupe_key="backup:2026-09-28", day="2026-09-28")

    out = _cli(db)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"done": 1, "failed": 0, "dead": 0, "lost": 0}
    assert _statuses(db) == ["done"]
    mgr = BackupManager(db)
    (info,) = [item for item in mgr.list() if item.reason == "scheduled"]
    assert mgr.verify(info).ok


def test_once_runs_exactly_one_job_when_two_are_queued(tmp_path):
    db = _v3_db(tmp_path / "memory.db")
    _enqueue(db, dedupe_key="backup:day-a", day="2026-09-28")
    _enqueue(db, dedupe_key="backup:day-b", day="2026-09-29")

    out = _cli(db, "--once")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["done"] == 1
    assert _statuses(db).count("done") == 1
    assert _statuses(db).count("queued") == 1


def test_unknown_type_is_an_error(tmp_path):
    db = _v3_db(tmp_path / "memory.db")
    _enqueue(db, dedupe_key="backup:2026-09-28", day="2026-09-28")

    out = _cli(db, "--types", "not-a-real-job")
    assert out.returncode == 1
    assert "unknown" in out.stderr.lower()
    assert "not-a-real-job" in out.stderr
    assert _statuses(db) == ["queued"]


def test_v2_database_is_refused_and_left_byte_identical(tmp_path):
    db = tmp_path / "memory.db"
    original = (FIXTURES / "v2_7_0.db").read_bytes()
    db.write_bytes(original)

    out = _cli(db)
    assert out.returncode == 1
    assert "v3" in out.stderr.lower()
    assert db.read_bytes() == original
    assert not db.with_name(db.name + "-wal").exists()
    assert not db.with_name(db.name + "-shm").exists()


def test_non_test_path_is_refused_and_creates_nothing():
    target_dir = Path.home() / f".em-worker-guard-{uuid.uuid4().hex}"
    target = target_dir / "memory.db"
    try:
        assert_safe_db_path(target)
    except MigrationRefused:
        pass
    else:
        pytest.skip("home directory is inside a temp/test location here")
    try:
        out = _cli(target)
        assert out.returncode == 1
        assert "not inside a temporary or test path" in out.stderr
        assert not target_dir.exists()
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)
