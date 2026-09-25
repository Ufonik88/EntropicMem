"""EM-202 unit tests for ``em.store.locking`` — portable advisory file lock.

POSIX (``fcntl.flock``) and Windows (``msvcrt.locking``) must show the same
semantics: exclusive, advisory, cross-process, released on close or process
exit. These tests run on Linux locally and on the (now blocking) Windows CI
job, so anything platform-specific is explicitly guarded.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "entropicmem" / "scripts"))

from em.store.locking import FileLock  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── basic semantics ─────────────────────────────────────────────────────────


def test_acquire_release_roundtrip(tmp_path):
    lock = FileLock(tmp_path / "x.lock")
    assert not lock.held
    assert lock.acquire(blocking=False) is True
    assert lock.held
    lock.release()
    assert not lock.held
    lock.close()


def test_acquire_creates_lock_file_eagerly(tmp_path):
    """Parity with the v2 engine: the ``<db>.lock`` file exists as soon as
    the engine (and thus its FileLock) is constructed."""
    path = tmp_path / "memory.db.lock"
    lock = FileLock(path)
    assert path.exists()
    lock.close()


def test_second_lock_in_same_process_is_excluded(tmp_path):
    """flock (POSIX) and msvcrt (Windows) both treat separate open handles
    in the same process as separate owners — pin that shared semantics."""
    a = FileLock(tmp_path / "x.lock")
    b = FileLock(tmp_path / "x.lock")
    assert a.acquire(blocking=False) is True
    assert b.acquire(blocking=False) is False
    a.release()
    assert b.acquire(blocking=False) is True
    b.release()
    a.close()
    b.close()


def test_blocking_acquire_waits_for_release(tmp_path):
    a = FileLock(tmp_path / "x.lock")
    assert a.acquire(blocking=False) is True
    result: list = []

    def _grab():
        b = FileLock(tmp_path / "x.lock")
        got = b.acquire(blocking=True, poll=0.02)
        result.append(got)
        b.close()

    t = threading.Thread(target=_grab)
    t.start()
    time.sleep(0.15)
    assert result == []  # still blocked
    a.release()
    t.join(timeout=5)
    assert result == [True]
    a.close()


def test_blocking_acquire_honours_timeout(tmp_path):
    a = FileLock(tmp_path / "x.lock")
    assert a.acquire(blocking=False) is True
    b = FileLock(tmp_path / "x.lock")
    started = time.monotonic()
    assert b.acquire(blocking=True, poll=0.02, timeout=0.2) is False
    assert time.monotonic() - started >= 0.15
    a.release()
    a.close()
    b.close()


def test_close_releases_the_lock(tmp_path):
    a = FileLock(tmp_path / "x.lock")
    assert a.acquire(blocking=False) is True
    a.close()
    b = FileLock(tmp_path / "x.lock")
    assert b.acquire(blocking=False) is True
    b.close()


def test_release_without_acquire_is_a_noop(tmp_path):
    lock = FileLock(tmp_path / "x.lock")
    lock.release()  # must not raise
    lock.close()


# ── probe (used by the CLI's "is the provider running?" check) ─────────────


def test_probe_missing_file_is_false_and_not_created(tmp_path):
    path = tmp_path / "never.lock"
    assert FileLock.probe(path) is False
    assert not path.exists()  # a probe must never create the file


def test_probe_unlocked_existing_file_is_false(tmp_path):
    path = tmp_path / "x.lock"
    path.write_text("", encoding="utf-8")
    assert FileLock.probe(path) is False


def test_probe_held_lock_is_true(tmp_path):
    path = tmp_path / "x.lock"
    holder = FileLock(path)
    assert holder.acquire(blocking=False) is True
    assert FileLock.probe(path) is True
    holder.release()
    assert FileLock.probe(path) is False
    holder.close()


def test_probe_detects_foreign_flock(tmp_path):
    """The v2 export/import tests hold the lock with a raw fcntl.flock; the
    probe must see that (same mechanism, different handle)."""
    import os

    try:
        import fcntl
    except ImportError:
        import pytest

        pytest.skip("POSIX-only check")
    path = tmp_path / "x.lock"
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        assert FileLock.probe(path) is True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert FileLock.probe(path) is False


# ── drift guard: v2 modules must not import platform lock modules directly ──


def test_no_direct_platform_lock_imports_outside_locking_module():
    """EM-202 moved locking into ``em.store.locking``; the v2 engine and CLI
    must not grow back direct fcntl/msvcrt imports (that is exactly what
    broke ``import memory_engine`` on Windows)."""
    for rel in (
        "plugins/entropicmem/scripts/memory_engine.py",
        "plugins/entropicmem/scripts/entropicmem.py",
    ):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for banned in ("import fcntl", "import msvcrt", "fcntl.", "msvcrt."):
            assert banned not in src, f"{rel} must use em.store.locking, found {banned!r}"


def test_locking_module_is_the_only_platform_importer():
    locking_src = (
        REPO_ROOT / "plugins" / "entropicmem" / "scripts" / "em" / "store" / "locking.py"
    ).read_text(encoding="utf-8")
    assert "import fcntl" in locking_src and "import msvcrt" in locking_src
