"""Schema migration framework for the v3 storage core (EM-203).

Plan card EM-203: each migration module exposes ``VERSION: int``,
``NAME: str`` and ``def up(conn) -> None``. The runner backs the database up
first, applies each pending migration inside its own transaction, records a
``schema_migrations`` row carrying ``sha256`` of the module source, and sets
``PRAGMA user_version``. It refuses to run when the database is newer than the
code ("downgrade not supported").

**Development safety (owner rule for S2).** Migrations must never auto-run
against a database outside a temporary or test path while v3 is in development:
unreleased schema code landing on the live store would be unrecoverable. So
:func:`assert_safe_db_path` refuses by default, and :func:`migrate` calls it
*before* opening a backup or writing anything. The real 3.0 cutover opts in
explicitly with ``ENTROPICMEM_ALLOW_LIVE_MIGRATION=1``; nothing in development
or CI ever sets it.

Stdlib-only; no Hermes imports. Depends on :mod:`em.store.db` for
``write_txn`` / ``DowngradeError`` (one-way: db.py never imports this module).
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence, cast

from em.store import db as _db

__all__ = [
    "ALLOW_LIVE_ENV",
    "LATEST",
    "Migration",
    "MigrationChecksumMismatch",
    "MigrationError",
    "MigrationRefused",
    "assert_safe_db_path",
    "discover",
    "migrate",
]

#: Set to ``1`` to permit migrating a non-temp, non-test database. This is the
#: explicit opt-in for the real 3.0 cutover; development and CI never set it.
ALLOW_LIVE_ENV = "ENTROPICMEM_ALLOW_LIVE_MIGRATION"

_HERE = Path(__file__).resolve().parent


class MigrationError(RuntimeError):
    """A migration module is malformed or the registry is inconsistent."""


class MigrationRefused(MigrationError):
    """Refused to migrate this path (not a temp/test database)."""


class MigrationChecksumMismatch(MigrationError):
    """An already-applied migration's source changed since it was applied."""


@dataclass(frozen=True)
class Migration:
    """One discovered (or test-supplied) schema migration."""

    version: int
    name: str
    slug: str
    up: Callable[[sqlite3.Connection], None]
    checksum: str
    module_name: str = ""


_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


def _module_files(directory: Optional[Path] = None) -> list[Path]:
    d = _HERE if directory is None else Path(directory)
    return sorted(
        p for p in d.glob("[0-9][0-9][0-9][0-9]_*.py") if p.name != "__init__.py"
    )


def _load(path: Path) -> Migration:
    """Import one ``NNNN_slug.py`` module and validate its contract."""
    module_name = f"em_migration_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise MigrationError(f"cannot load migration module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)

    version = getattr(module, "VERSION", None)
    name = getattr(module, "NAME", None)
    up = cast("Callable[[sqlite3.Connection], None]", getattr(module, "up", None))
    if not isinstance(version, int) or isinstance(version, bool):
        raise MigrationError(f"{path.name}: VERSION must be an int, got {version!r}")
    if not isinstance(name, str) or not name:
        raise MigrationError(f"{path.name}: NAME must be a non-empty str")
    if not callable(up):
        raise MigrationError(f"{path.name}: up(conn) must be callable")
    expected_prefix = f"{version:04d}_"
    if not path.name.startswith(expected_prefix):
        raise MigrationError(
            f"{path.name}: filename must start with {expected_prefix} to match "
            f"VERSION={version}"
        )
    return Migration(
        version=version,
        name=name,
        slug=path.stem[len(expected_prefix) :],
        up=up,
        checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
        module_name=f"{__name__}.{path.stem}",
    )


def discover(directory: Optional[Path] = None) -> list[Migration]:
    """Load every ``NNNN_*.py`` migration, in version order.

    Raises :class:`MigrationError` on a malformed module, a duplicate version,
    or a gap in the numbering (migrations must be contiguous from 1 so
    ``user_version`` can be trusted as "everything up to N has been applied").
    """
    found = [_load(p) for p in _module_files(directory)]
    found.sort(key=lambda m: m.version)

    versions = [m.version for m in found]
    if len(set(versions)) != len(versions):
        dupes = sorted({v for v in versions if versions.count(v) > 1})
        raise MigrationError(f"duplicate migration versions: {dupes}")
    if versions and versions != list(range(1, len(versions) + 1)):
        raise MigrationError(
            f"migration versions must be contiguous from 1, got {versions}"
        )
    return found


#: Highest schema version this build knows how to produce.
LATEST = max((m.version for m in discover()), default=0)

# db.py's fast path reads its own module global at call time; EM-203 owns the
# registry, so the registry is the source of truth and pushes LATEST into db.
_db.LATEST_USER_VERSION = LATEST


def _db_path_of(conn: sqlite3.Connection) -> str:
    """File path of the connection's main database ("" for in-memory)."""
    row = conn.execute("PRAGMA database_list").fetchone()
    if not row:
        return ""
    return row[2] or ""


def assert_safe_db_path(path: "os.PathLike[str] | str") -> None:
    """Refuse any database that is not in a temporary or test location.

    The live store and anything else outside a recognised scratch/test tree is
    rejected with :class:`MigrationRefused` unless ``ALLOW_LIVE_ENV`` is set.
    Relative paths are resolved first so ``.../entropicmem/../entropicmem/
    memory.db`` cannot slip past the deny list.

    In-memory databases (``:memory:`` or an empty path) are always allowed:
    they cannot be the live store.
    """
    text = os.fspath(path) if not isinstance(path, str) else path
    if not text or text == ":memory:":
        return

    if os.environ.get(ALLOW_LIVE_ENV) == "1":
        return

    # Resolve symlinks and ".." so the deny list cannot be dodged.
    try:
        resolved = Path(text).expanduser().resolve()
    except OSError as exc:  # pragma: no cover - pathological input
        raise MigrationRefused(f"cannot resolve database path {text!r}: {exc}") from exc

    home = Path.home().resolve()
    deny = (
        home / ".hermes" / "entropicmem",
        home / ".hermes" / "entropicmem-live-2.8.0",
    )
    for blocked in deny:
        if resolved == blocked or blocked in resolved.parents:
            raise MigrationRefused(
                f"refusing to migrate {resolved}: it is inside the live "
                f"EntropicMem store. Set {ALLOW_LIVE_ENV}=1 only for the "
                "real 3.0 cutover."
            )

    allowed_roots = [Path(tempfile.gettempdir()).resolve()]
    # Any path under a directory named "tests" (the repo's tests/ tree, and
    # per-repo scratch dirs) is a test fixture by construction.
    allowed_roots.extend(p for p in resolved.parents if p.name == "tests")
    for root in allowed_roots:
        if root in resolved.parents:
            return

    raise MigrationRefused(
        f"refusing to migrate {resolved}: not inside a temporary or test path. "
        f"Set {ALLOW_LIVE_ENV}=1 only for the real 3.0 cutover."
    )


def _applied_checksums(conn: sqlite3.Connection) -> dict:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not exists:
        return {}
    rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    return {int(r[0]): str(r[1]) for r in rows}


def _verify_checksums(conn: sqlite3.Connection, registry: Sequence[Migration]) -> None:
    """Fail loudly if an applied migration's source was edited afterwards.

    Without this, a changed ``up()`` would be silently treated as "already
    applied" and the database would keep a shape no module describes.
    """
    recorded = _applied_checksums(conn)
    if not recorded:
        return
    by_version = {m.version: m for m in registry}
    for version, checksum in sorted(recorded.items()):
        known = by_version.get(version)
        if known is None:
            continue  # from a newer build; the downgrade check handles that
        if known.checksum != checksum:
            raise MigrationChecksumMismatch(
                f"migration {known.version:04d} ({known.name}) was applied with "
                f"checksum {checksum[:12]}… but its source now hashes to "
                f"{known.checksum[:12]}…. Applied migrations are immutable: "
                "add a new migration instead of editing an old one."
            )


def _backup(
    conn: sqlite3.Connection, *, db_path: str, from_version: int, to_version: int,
    backup_dir: Optional[Path],
) -> Optional[Path]:
    """Online-copy the unmigrated DB to ``backups/pre-migrate-v{f}-to-v{t}-<ts>.db``.

    Delegates to :class:`em.store.backup.BackupManager` (EM-210), so the
    pre-migration copy is verified (integrity, counts, audit chain) and gets a
    sha256 manifest before any migration runs. If the copy fails verification
    the migration does not start: ``BackupVerificationError`` propagates.
    """
    if not db_path:
        return None  # in-memory: nothing to back up
    from ..backup import BackupManager  # lazy: backup imports this module's guard

    info = BackupManager(db_path, backup_dir).create(
        reason=f"pre-migrate-v{from_version}-to-v{to_version}", conn=conn
    )
    return info.path


def migrate(
    conn: sqlite3.Connection,
    *,
    registry: Optional[Sequence[Migration]] = None,
    target: Optional[int] = None,
    backup_dir: Optional[Path] = None,
) -> list[Migration]:
    """Apply every pending migration up to ``target`` (default: ``LATEST``).

    Returns the migrations actually applied, oldest first (empty when the
    database was already current). Guarantees:

    * the path guard runs first — a refused database is not opened, backed up
      or touched in any way;
    * each migration runs in its own transaction together with its
      ``schema_migrations`` row and the ``user_version`` bump, so a failure
      leaves the database exactly at the last good version (card AC);
    * a database newer than this build raises :class:`em.store.db.DowngradeError`;
    * editing an already-applied migration raises
      :class:`MigrationChecksumMismatch` instead of silently doing nothing.

    Never commits outside a migration's own transaction.
    """
    migrations = list(registry) if registry is not None else discover()

    # 1. Path guard BEFORE anything observable happens (owner rule for S2).
    db_path = _db_path_of(conn)
    assert_safe_db_path(db_path)

    if target is not None:
        ceiling = target
    elif registry is not None:
        # A caller-supplied registry (tests) defines its own ceiling; falling
        # back to LATEST would silently drop its higher-numbered migrations.
        ceiling = max((m.version for m in migrations), default=0)
    else:
        ceiling = LATEST
    from_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if from_version > ceiling:
        raise _db.DowngradeError(
            f"database schema user_version={from_version} is newer than this "
            f"build (latest={ceiling}); downgrade not supported"
        )

    _verify_checksums(conn, migrations)

    pending = [
        m for m in migrations if from_version < m.version <= ceiling
    ]
    pending.sort(key=lambda m: m.version)
    if not pending:
        return []

    # 2. Backup the pre-migration state (skipped for in-memory databases).
    _backup(
        conn,
        db_path=db_path,
        from_version=from_version,
        to_version=pending[-1].version,
        backup_dir=backup_dir,
    )

    # 3. Bookkeeping table first, in its own transaction, so a failure in the
    #    very first migration still leaves an inspectable (empty) table.
    with _db.write_txn(conn):
        conn.execute(_MIGRATIONS_DDL)

    applied: list[Migration] = []
    for migration in pending:
        with _db.write_txn(conn):
            migration.up(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, checksum, applied_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                ),
            )
            conn.execute(f"PRAGMA user_version = {int(migration.version)}")
        applied.append(migration)
    return applied
