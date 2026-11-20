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

from em.jobs.cli import run_worker  # noqa: E402
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


# --- in-process (W45 coverage): the run_worker contract, pinned directly -----
#
# The tests above drive ``entropicmem.py worker run`` as a subprocess: they
# prove the CLI wiring end to end, but a subprocess is invisible to the
# suite's own ``--cov=em`` measurement, and three shipped contracts had no
# test at all — the ``--max-seconds`` budget loop, the dead-job exit code,
# and the missing-file refusal. These call ``run_worker`` in-process (the
# way ``tests/unit/test_em405_retract.py`` already runs the happy path) so
# the refusals, the run modes and the exit codes are pinned against the
# function itself. No production line changes; every behaviour asserted
# below is behaviour the module already ships.


def _enqueue_retract(path: Path, payload: dict) -> str:
    """One ``retract_turns`` job — the cheapest handler that needs no files."""
    store = Store(str(path))
    try:
        with store.transaction() as conn:
            return JobQueue(conn).enqueue("retract_turns", payload)
    finally:
        store.close()


def test_unknown_type_is_refused_in_process(tmp_path, capsys):
    db = _v3_db(tmp_path / "memory.db")
    _enqueue(db, dedupe_key="backup:2026-09-28", day="2026-09-28")

    rc = run_worker(db, once=True, types=["not-a-real-job"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "unknown job type" in captured.err
    assert "not-a-real-job" in captured.err
    assert _statuses(db) == ["queued"]  # refused before any handle is opened


def test_non_test_path_refusal_is_returned_not_raised(capsys):
    """The cron entry converts MigrationRefused into exit 1 — never a crash."""
    target_dir = Path.home() / f".em-worker-guard-{uuid.uuid4().hex}"
    target = target_dir / "memory.db"
    try:
        assert_safe_db_path(target)
    except MigrationRefused:
        pass
    else:
        pytest.skip("home directory is inside a temp/test location here")
    try:
        rc = run_worker(target, once=True)  # must not raise
        captured = capsys.readouterr()
        assert rc == 1
        assert "not inside a temporary or test path" in captured.err
        assert not target_dir.exists()
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_missing_store_is_refused_and_not_created(tmp_path, capsys):
    """A store that does not exist is not v3 — and the probe creates nothing."""
    missing = tmp_path / "memory.db"

    rc = run_worker(missing, once=True)

    captured = capsys.readouterr()
    assert rc == 1
    assert "not a v3 database" in captured.err
    assert not missing.exists()


def test_a_database_without_the_jobs_table_is_refused(tmp_path, capsys):
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()  # a real sqlite file with no tables

    rc = run_worker(empty, once=True)

    captured = capsys.readouterr()
    assert rc == 1
    assert "not a v3 database" in captured.err


def test_a_wrong_shaped_jobs_table_is_not_v3(tmp_path, capsys):
    """The module's own rule: a ``jobs`` table with another shape is refused."""
    odd = tmp_path / "odd.db"
    conn = sqlite3.connect(odd)
    try:
        conn.execute("CREATE TABLE jobs (id TEXT, status TEXT)")
        conn.commit()
    finally:
        conn.close()

    rc = run_worker(odd, once=True)

    captured = capsys.readouterr()
    assert rc == 1
    assert "not a v3 database" in captured.err


def test_run_until_idle_drains_every_queued_job_in_process(tmp_path, capsys):
    db = _v3_db(tmp_path / "memory.db")
    _enqueue_retract(db, {"session_id": "s-1", "from_turn": 1})
    _enqueue_retract(db, {"session_id": "s-2", "from_turn": 2})

    rc = run_worker(db)  # neither --once nor a budget: run until idle

    captured = capsys.readouterr()
    assert rc == 0
    assert json.loads(captured.out) == {"done": 2, "failed": 0, "dead": 0, "lost": 0}
    assert _statuses(db) == ["done", "done"]


def test_max_seconds_budget_stops_the_loop_leaving_the_rest_queued(
    tmp_path, monkeypatch, capsys
):
    """``--max-seconds`` (a shipped CLI flag, previously untested anywhere)."""
    db = _v3_db(tmp_path / "memory.db")
    _enqueue_retract(db, {"session_id": "s-1", "from_turn": 1})
    _enqueue_retract(db, {"session_id": "s-2", "from_turn": 2})

    # Only the CLI module's clock is stubbed: tick 1 sets the deadline, tick 2
    # admits the first job, tick 3 has passed it — the loop stops after one.
    ticks = iter([0.0, 0.0, 1_000_000.0])

    class _Clock:
        @staticmethod
        def monotonic():
            return next(ticks)

    import em.jobs.cli as jobs_cli

    monkeypatch.setattr(jobs_cli, "time", _Clock)

    rc = run_worker(db, max_seconds=10.0)

    captured = capsys.readouterr()
    assert rc == 0  # a budget stop is not a failure
    assert json.loads(captured.out) == {"done": 1, "failed": 0, "dead": 0, "lost": 0}
    assert _statuses(db) == ["done", "queued"]


def test_max_seconds_budget_with_no_work_exits_cleanly(tmp_path, monkeypatch, capsys):
    """A budget window over an empty queue breaks out — it does not spin.

    The clock carries exactly the two ticks the exit path consumes (one to
    set the deadline, one to enter the loop). A regression that drops the
    ``break`` demands a third tick and raises instead of exiting cleanly.
    """
    db = _v3_db(tmp_path / "memory.db")  # v3, but nothing queued

    ticks = iter([0.0, 0.0])

    class _Clock:
        @staticmethod
        def monotonic():
            return next(ticks)

    import em.jobs.cli as jobs_cli

    monkeypatch.setattr(jobs_cli, "time", _Clock)

    rc = run_worker(db, max_seconds=10.0)

    captured = capsys.readouterr()
    assert rc == 0
    assert json.loads(captured.out) == {"done": 0, "failed": 0, "dead": 0, "lost": 0}


def test_a_dead_job_makes_the_exit_code_one(tmp_path, capsys):
    """The module docstring's contract: "Exit 1 if any job is dead."

    A malformed ``retract_turns`` payload is a permanent failure, and a
    permanent failure goes straight to ``dead`` — the one exit-code branch
    no other test pins.
    """
    db = _v3_db(tmp_path / "memory.db")
    _enqueue_retract(db, {"session_id": "", "from_turn": 1})

    rc = run_worker(db, once=True, types=["retract_turns"])

    captured = capsys.readouterr()
    assert rc == 1
    assert json.loads(captured.out) == {"done": 0, "failed": 0, "dead": 1, "lost": 0}
    assert _statuses(db) == ["dead"]
