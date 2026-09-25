"""Connection management for the v3 storage core (EM-202).

Plan card EM-202:

* :func:`open_db` — one place that knows the pragma set every v3 connection
  runs with (WAL, synchronous=NORMAL, busy_timeout=5000, foreign_keys=ON,
  temp_store=MEMORY, mmap_size=64MiB, ``isolation_level=None`` so all
  transactions are explicit). Readonly connections use the SQLite URI
  ``mode=ro``. POSIX permissions: DB file 0600, parent dir 0700.
* :func:`write_txn` — ``BEGIN IMMEDIATE`` … ``COMMIT``/``ROLLBACK`` with up
  to 3 jittered retries on SQLITE_BUSY. **No fcntl/msvcrt here:**
  cross-process serialisation is SQLite's job (that is what BEGIN IMMEDIATE
  plus busy_timeout is for); advisory file locks (``em.store.locking``)
  only guard things SQLite cannot see (migrations, capsule imports).
* :func:`ensure_schema` — fast path on ``PRAGMA user_version``; migrations
  run under an ``O_CREAT|O_EXCL`` lock file (portable, no fcntl), stale
  after 10 minutes. EM-203 supplies the ``migrate`` callback and raises
  ``LATEST_USER_VERSION``; a DB newer than the code refuses to open
  (downgrade not supported).
* :class:`Store` — per-thread reader connections (``threading.local``) and
  ONE writer connection per process, guarded by a ``threading.Lock``.

Stdlib-only; no Hermes imports; no environment reads (paths are passed in).
"""

from __future__ import annotations

import contextlib
import os
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Iterator, Optional
from urllib.request import pathname2url

__all__ = [
    "LATEST_USER_VERSION",
    "MIGRATION_LOCK_NAME",
    "MIGRATION_LOCK_STALE_S",
    "DowngradeError",
    "MigrationLockHeld",
    "Store",
    "ensure_schema",
    "migration_lock",
    "open_db",
    "resolve_latest_user_version",
    "write_txn",
]

# Schema version this build understands. Kept in sync with the migration
# registry by :mod:`em.store.migrations` at import time, and resolved lazily
# by :func:`ensure_schema` so it is correct even when ``db`` is imported
# alone (see :func:`resolve_latest_user_version`).
LATEST_USER_VERSION = 0


def resolve_latest_user_version() -> int:
    """The registry's highest version, resolved on demand.

    ``em.store.migrations`` owns the registry and pushes ``LATEST`` into
    ``LATEST_USER_VERSION`` when it is imported. Relying on that side effect
    alone is a trap: ``import em.store.db`` by itself would leave the constant
    at 0, and a DB already at version 1 would then be rejected as a
    "downgrade". Importing lazily here avoids that without creating a circular
    import (migrations depends on db, never the reverse at module scope).
    """
    global LATEST_USER_VERSION
    try:
        from em.store import migrations as _migrations

        LATEST_USER_VERSION = _migrations.LATEST
    except Exception:  # pragma: no cover - registry missing/unimportable
        pass
    return LATEST_USER_VERSION

MIGRATION_LOCK_NAME = "migration.lock"
MIGRATION_LOCK_STALE_S = 10 * 60

_MMAP_SIZE = 64 * 1024 * 1024  # 64 MiB (plan card EM-202)


class DowngradeError(RuntimeError):
    """The database is newer than this build; downgrade is not supported."""


class MigrationLockHeld(RuntimeError):
    """Another (live) migration holds the migration lock."""


def _chmod_posix(path: Path, mode: int) -> None:
    if os.name == "nt":  # pragma: no cover - POSIX-only hardening
        return
    try:
        os.chmod(str(path), mode)
    except OSError:
        pass  # best-effort; e.g. filesystem without permission support


def open_db(
    path: "os.PathLike[str] | str",
    *,
    readonly: bool = False,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    """Open a v3 database connection with the canonical pragma set.

    ``readonly=True`` opens the SQLite URI ``file:...?mode=ro``: the file
    must exist and no write ever succeeds. Readonly connections skip the
    ``journal_mode`` write (a WAL file that is already WAL needs no change,
    and a non-WAL file must not be converted through a readonly handle);
    the remaining pragmas are connection-local and always applied.

    ``check_same_thread`` keeps SQLite's own thread-affinity guard on for
    direct users. ``Store`` passes False because it owns the discipline
    (thread-local readers, one lock-serialised writer) and must be able to
    close every connection from whichever thread calls ``close()``.
    """
    path = Path(path)
    if readonly:
        uri = f"file:{pathname2url(str(path.resolve()))}?mode=ro"
        conn = sqlite3.connect(
            uri,
            uri=True,
            isolation_level=None,
            check_same_thread=check_same_thread,
        )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        _chmod_posix(path.parent, 0o700)
        conn = sqlite3.connect(
            str(path), isolation_level=None, check_same_thread=check_same_thread
        )
        _chmod_posix(path, 0o600)
    conn.row_factory = sqlite3.Row
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute(f"PRAGMA mmap_size={_MMAP_SIZE}")
    return conn


def _is_busy(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


@contextlib.contextmanager
def write_txn(
    conn: sqlite3.Connection,
    *,
    retries: int = 3,
    base_delay: float = 0.02,
) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` … ``COMMIT`` / ``ROLLBACK`` context manager.

    SQLITE_BUSY on the BEGIN is retried up to ``retries`` times with
    exponential backoff + jitter (bounded, so a deadlocked peer surfaces as
    an OperationalError instead of hanging). Body exceptions roll back and
    propagate. Never nests: SQLite has no nested transactions and callers
    must not try (one writer per process, see ``Store``).
    """
    attempt = 0
    while True:
        try:
            conn.execute("BEGIN IMMEDIATE")
            break
        except sqlite3.OperationalError as exc:
            if not _is_busy(exc):
                raise
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay))
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _create_lock_exclusive(path: Path, stale_after: float) -> int:
    """Create ``path`` with O_CREAT|O_EXCL (portable; no fcntl/msvcrt).

    A lock file older than ``stale_after`` seconds is considered abandoned
    (crashed migrator) and is taken over. Returns the open fd.
    """
    for _attempt in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                continue  # vanished between open and stat: retry
            if age > stale_after:
                with contextlib.suppress(OSError):
                    path.unlink()
                continue  # stale: take over
            raise MigrationLockHeld(f"migration lock held: {path}") from None
        with contextlib.suppress(OSError):
            os.write(fd, f"pid={os.getpid()}\n".encode())
        return fd
    raise MigrationLockHeld(f"migration lock held: {path}")


@contextlib.contextmanager
def migration_lock(
    lock_dir: "os.PathLike[str] | str",
    *,
    stale_after: float = MIGRATION_LOCK_STALE_S,
) -> Iterator[bool]:
    """Hold ``<lock_dir>/migration.lock`` for the duration of the block.

    Creation is ``O_CREAT|O_EXCL`` — atomic on every platform, no advisory
    locking needed. A lock older than ``stale_after`` (default 10 min) is
    stale and gets taken over; a fresh lock raises ``MigrationLockHeld``.
    The file is removed on exit (also on exception).
    """
    lock_dir = Path(lock_dir)
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / MIGRATION_LOCK_NAME
    fd = _create_lock_exclusive(path, stale_after)
    try:
        yield True
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            path.unlink()


def ensure_schema(
    conn: sqlite3.Connection,
    migrate: Callable[[sqlite3.Connection], None],
    *,
    lock_dir: "os.PathLike[str] | str | None" = None,
    latest: Optional[int] = None,
) -> bool:
    """Schema check fast path: skip everything when ``user_version == LATEST``.

    Returns True when ``migrate`` ran. ``user_version > latest`` raises
    ``DowngradeError`` (a newer DB must not be opened by older code).
    ``lock_dir`` defaults to the database file's directory; in-memory
    databases migrate without a lock file (nothing cross-process to guard).
    ``migrate`` receives the connection and must leave ``user_version`` at
    the new latest itself (EM-203's runner does this per migration).
    """
    target = resolve_latest_user_version() if latest is None else latest
    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if user_version > target:
        raise DowngradeError(
            f"database schema user_version={user_version} is newer than this "
            f"build (latest={target}); downgrade not supported"
        )
    if user_version == target:
        return False
    if lock_dir is None:
        db_file = conn.execute("PRAGMA database_list").fetchone()[2]
        if db_file:
            lock_dir = Path(db_file).parent
    if lock_dir is None:  # in-memory
        migrate(conn)
        return True
    with migration_lock(lock_dir):
        migrate(conn)
    return True


class Store:
    """Per-thread readers + one process-wide writer (plan card EM-202).

    * ``reader()`` — a ``threading.local`` connection per thread; readers
      never block on the writer under WAL.
    * ``writer()`` — ONE connection per process; ``transaction()`` runs a
      ``write_txn`` on it while holding the writer lock, so threads
      serialise instead of interleaving inside a transaction.
    * ``close()`` closes the writer and every reader created through this
      Store (idempotent).
    """

    def __init__(self, path: "os.PathLike[str] | str") -> None:
        self.path = Path(path)
        self._local = threading.local()
        self._writer: Optional[sqlite3.Connection] = None
        self._writer_lock = threading.Lock()  # serialises write_txn
        self._create_lock = threading.Lock()  # guards writer creation
        self._registry_lock = threading.Lock()
        self._all_conns: list[sqlite3.Connection] = []

    def _track(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        with self._registry_lock:
            self._all_conns.append(conn)
        return conn

    def reader(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._track(open_db(self.path, check_same_thread=False))
            self._local.conn = conn
        return conn

    def writer(self) -> sqlite3.Connection:
        if self._writer is None:
            with self._create_lock:
                if self._writer is None:
                    self._writer = self._track(
                        open_db(self.path, check_same_thread=False)
                    )
        return self._writer

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._writer_lock:
            with write_txn(self.writer()) as conn:
                yield conn

    def close(self) -> None:
        with self._registry_lock:
            conns, self._all_conns = self._all_conns, []
        self._writer = None
        for conn in conns:
            with contextlib.suppress(sqlite3.Error):
                conn.close()
