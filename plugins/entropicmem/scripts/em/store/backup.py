"""Backup manager for the memory database (card EM-210).

A backup is only useful if it restores, so every backup is verified before it
counts:

1. **Online snapshot** through the SQLite backup API, into a ``.partial`` file.
   It is consistent even while a writer is active and the WAL holds commits the
   main file doesn't yet have. A file copy would miss those or tear a page.
2. **Verification of the copy, not the source:** ``PRAGMA integrity_check``,
   ``user_version``, per-table row counts and, for a v3 database, the audit hash
   chain. If any check fails, the partial file is deleted and
   ``BackupVerificationError`` is raised. An unverified backup is never left
   where it looks like a good one.
3. **Manifest.** Every file in the snapshot is recorded inside
   ``<reason>-<stamp>/manifest.json`` with its role, source name, sha256, size,
   counts, schema version and reason. ``verify()`` re-hashes each one later,
   which catches bit rot and truncation. Only then is the ``.partial`` directory
   renamed into place.

A snapshot is a **directory** holding every database that belongs to the store:
``memory.db`` and, when the index exists, ``index.db`` (Chunk 3.1). A restore is
only trustworthy if everything it restores is consistent, so the index travels
with the memory database. Snapshots written before 3.1 (``<name>.db`` beside
``<name>.json``, manifest ``format: 1``) stay readable, verifiable and
restorable; nothing rewrites or deletes them.

Restore is the dangerous direction, so it refuses by default:

- it refuses a live path unless ``allow_live=True``, the same development guard
  migrations use;
- it refuses while the provider holds ``<db>.lock``;
- it refuses a backup that no longer verifies;
- it takes a ``pre-restore`` backup of the current database first;
- it deletes the target's ``-wal``/``-shm`` files before swapping the file in.
  A leftover WAL from the old database would be replayed on top of the restored
  one and corrupt it.

Files are 0600 and the directory is 0700 on POSIX. The manifest records the
source file's *name*, never its full path: paths contain the user's home
directory, and backups get copied to other places.

Stdlib-only (plan §3.2).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..clock import to_iso, utc_now
from .locking import FileLock

#: Written manifest format. ``2`` = a directory snapshot with a ``files`` list.
#: ``1`` = the pre-3.1 flat layout (one ``.db`` beside a ``.json``); still read
#: by ``_load_flat``, and never rewritten.
MANIFEST_FORMAT = 2

#: File names inside a snapshot directory, keyed by the database's role.
ROLE_MEMORY = "memory"
ROLE_INDEX = "index"
SNAPSHOT_FILENAMES = {ROLE_MEMORY: "memory.db", ROLE_INDEX: "index.db"}
MANIFEST_NAME = "manifest.json"

#: Reasons that are safety nets for a risky operation. Rotation keeps them
#: under their own (separate) limit so routine backups never push them out.
SAFETY_PREFIXES = ("pre-migrate", "pre-restore")

DEFAULT_KEEP = 7
DEFAULT_KEEP_SAFETY = 5

_REASON_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_NAME_RE = re.compile(r"^(?P<reason>[a-z0-9][a-z0-9-]*)-(?P<stamp>\d{8}-\d{6}-\d{3})(?:-(?P<n>\d+))?\.db$")
_DIR_RE = re.compile(r"^(?P<reason>[a-z0-9][a-z0-9-]*)-(?P<stamp>\d{8}-\d{6}-\d{3})(?:-(?P<n>\d+))?$")


class BackupError(RuntimeError):
    """Base class for backup failures."""


class BackupVerificationError(BackupError):
    """A fresh snapshot failed verification. Nothing was kept."""


class RestoreRefused(BackupError):
    """Restore preconditions not met. Nothing was changed."""


@dataclass(frozen=True)
class BackupFile:
    """One database inside a snapshot, as the manifest records it."""

    role: str
    name: str
    source: str
    sha256: str
    size: int
    user_version: int
    counts: dict[str, int]
    audit: Optional[dict[str, Any]]


@dataclass(frozen=True)
class BackupInfo:
    """One stored snapshot.

    ``path`` is the snapshot directory (3.1 layout) or the ``.db`` file of a
    pre-3.1 flat backup. ``files`` holds one :class:`BackupFile` per database in
    the snapshot, memory first. The single-file accessors (``sha256``, ``size``,
    ``user_version``, ``counts``, ``audit``) report the memory database, which is
    what every pre-3.1 caller means by them.
    """

    path: Path
    manifest_path: Path
    reason: str
    created_at: str
    files: tuple[BackupFile, ...]
    flat: bool = False

    @property
    def primary(self) -> BackupFile:
        return self.files[0]

    @property
    def sha256(self) -> str:
        return self.primary.sha256

    @property
    def size(self) -> int:
        return self.primary.size

    @property
    def user_version(self) -> int:
        return self.primary.user_version

    @property
    def counts(self) -> dict[str, int]:
        return self.primary.counts

    @property
    def audit(self) -> Optional[dict[str, Any]]:
        return self.primary.audit

    @property
    def is_safety(self) -> bool:
        return self.reason.startswith(SAFETY_PREFIXES)

    def file_path(self, stored: "BackupFile") -> Path:
        """Where ``stored`` lives on disk, in either layout."""
        return self.path if self.flat else self.path / stored.name

    @property
    def primary_path(self) -> Path:
        return self.file_path(self.primary)


@dataclass
class VerifyReport:
    ok: bool
    problems: list[str] = field(default_factory=list)


# --- helpers ---------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _chmod(path: Path, mode: int) -> None:
    if os.name != "posix":
        return
    with contextlib.suppress(OSError):
        os.chmod(path, mode)


def _open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _inspect(conn: sqlite3.Connection) -> tuple[list[str], int, dict[str, int], Optional[dict[str, Any]]]:
    """Checks shared by create() and verify(). Returns (problems, user_version,
    counts, audit)."""
    problems: list[str] = []
    rows = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
    if rows != ["ok"]:
        problems.append("integrity_check: " + "; ".join(str(r) for r in rows[:5]))
    user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    counts: dict[str, int] = {}
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%'"
        " AND (sql IS NULL OR sql NOT LIKE 'CREATE VIRTUAL%')"
        " ORDER BY name"
    ).fetchall()
    for (name,) in tables:
        if "_fts" in name:  # FTS shadow tables: derived, not data
            continue
        counts[name] = int(conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])
    audit: Optional[dict[str, Any]] = None
    chained = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='audit_log'"
        " AND sql LIKE '%prev_hash%'"
    ).fetchone()[0]
    if chained:
        from . import audit as em_audit

        result = em_audit.verify(conn)
        audit = {"ok": bool(result.ok), "checked": int(result.checked)}
        if not result.ok:
            problems.append(f"audit chain broken at seq {result.first_bad_seq}")
    return problems, user_version, counts, audit


def _copy_standalone(source: sqlite3.Connection, dest: Path) -> None:
    """Backup-API copy of ``source`` into ``dest`` as one self-contained file.

    The copy inherits the source's WAL flag, which would leave ``-wal``/``-shm``
    sidecars next to every backup and make the file depend on them. Switching
    the copy to ``DELETE`` journaling folds everything into the main file. The
    provider's ``open_db`` turns WAL back on when a restored file is next opened.
    """
    target = sqlite3.connect(str(dest))
    try:
        source.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")
    finally:
        target.close()
    for suffix in ("-wal", "-shm", "-journal"):
        with contextlib.suppress(FileNotFoundError):
            dest.with_name(dest.name + suffix).unlink()


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S-") + f"{now.microsecond // 1000:03d}"


def _rmtree(path: Path) -> None:
    """Remove a directory or a file if it is there, following no symlink."""
    with contextlib.suppress(FileNotFoundError):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def _inspect_stored(path: Path) -> tuple[list[str], int, dict[str, int], Optional[dict[str, Any]]]:
    """``_inspect`` on a snapshot file, so an unreadable one is a finding.

    A snapshot may be taken of a database that is already damaged; that has to
    fail the snapshot cleanly instead of raising out of the middle of it.
    """
    conn = _open_ro(path)
    try:
        return _inspect(conn)
    except sqlite3.DatabaseError as exc:
        return [f"unreadable: {exc}"], 0, {}, None
    finally:
        conn.close()


# --- manager ---------------------------------------------------------------


class BackupManager:
    """Backups of one database file, kept in one directory.

    ``backup_dir`` defaults to ``<db dir>/backups``, the directory migrations
    have always used.
    """

    def __init__(
        self,
        db_path: "os.PathLike[str] | str",
        backup_dir: "os.PathLike[str] | str | None" = None,
        index_path: "os.PathLike[str] | str | None" = None,
    ) -> None:
        """``index_path`` defaults to the ``index.db`` beside the memory
        database, and is snapshotted only while that file exists. Nothing here
        reads ``HERMES_HOME``: the caller supplies the paths.
        """
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir) if backup_dir is not None else self.db_path.parent / "backups"
        self.index_path = Path(index_path) if index_path is not None else self.db_path.parent / "index.db"

    # --- create ---------------------------------------------------------

    def snapshot(self, *, reason: str = "manual", conn: sqlite3.Connection | None = None) -> Path:
        """Snapshot every database of the store; return the directory written.

        ``conn``: back up ``memory.db`` through an existing connection
        (migrations pass theirs, so the snapshot is exactly what they are about
        to change). Every other database is opened read-only for its copy.
        """
        return self._snapshot(reason=reason, conn=conn).path

    def create(self, *, reason: str = "manual", conn: sqlite3.Connection | None = None) -> BackupInfo:
        """The pre-3.1 name for :meth:`snapshot`, returning the details.

        Kept because callers still use it: the migration hook, the daily job and
        the tests. Both names write the same snapshot.
        """
        return self._snapshot(reason=reason, conn=conn)

    def _snapshot(self, *, reason: str, conn: sqlite3.Connection | None) -> BackupInfo:
        if not _REASON_RE.match(reason):
            raise ValueError(f"reason must be lowercase letters, digits and dashes: {reason!r}")
        if conn is None and not self.db_path.is_file():
            raise BackupError(f"no database at {self.db_path}")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        _chmod(self.backup_dir, 0o700)

        now = utc_now()
        dest = self._free_name(reason, now)
        partial = dest.with_name(dest.name + ".partial")
        _rmtree(partial)
        partial.mkdir(parents=True)
        _chmod(partial, 0o700)

        files: list[BackupFile] = []
        try:
            files.append(self._snapshot_one(partial, ROLE_MEMORY, self.db_path, conn))
            if self.index_path.is_file():
                files.append(self._snapshot_one(partial, ROLE_INDEX, self.index_path, None))
            info = BackupInfo(
                path=dest,
                manifest_path=dest / MANIFEST_NAME,
                reason=reason,
                created_at=to_iso(now),
                files=tuple(files),
            )
            self._write_manifest(partial / MANIFEST_NAME, info)
        except BaseException:
            _rmtree(partial)  # never leave something that looks like a backup
            raise
        os.replace(partial, dest)
        return info

    def _snapshot_one(
        self, partial: Path, role: str, source_path: Path, conn: sqlite3.Connection | None
    ) -> BackupFile:
        """Copy, verify and describe one database inside the partial directory."""
        target = partial / SNAPSHOT_FILENAMES[role]
        source = conn if conn is not None else _open_ro(source_path)
        try:
            _copy_standalone(source, target)
        finally:
            if conn is None:
                source.close()
        _chmod(target, 0o600)
        problems, user_version, counts, audit = _inspect_stored(target)
        if problems:
            raise BackupVerificationError(f"{role}: " + "; ".join(problems))
        return BackupFile(
            role=role,
            name=target.name,
            source=source_path.name,
            sha256=_sha256_file(target),
            size=target.stat().st_size,
            user_version=user_version,
            counts=counts,
            audit=audit,
        )

    def _free_name(self, reason: str, now: datetime) -> Path:
        """A directory name nothing else uses, in either layout."""
        base = f"{reason}-{_stamp(now)}"
        dest = self.backup_dir / base
        n = 1
        while (
            dest.exists()
            or (self.backup_dir / f"{base}.db").exists()
            or (self.backup_dir / f"{base}.json").exists()
        ):
            n += 1
            dest = self.backup_dir / f"{base}-{n}"
        return dest

    def _write_manifest(self, path: Path, info: BackupInfo) -> None:
        from .. import __version__

        doc = {
            "format": MANIFEST_FORMAT,
            "reason": info.reason,
            "created_at": info.created_at,
            "files": [
                {
                    "role": stored.role,
                    "name": stored.name,
                    "source": stored.source,
                    "sha256": stored.sha256,
                    "size": stored.size,
                    "user_version": stored.user_version,
                    "counts": stored.counts,
                    "audit": stored.audit,
                }
                for stored in info.files
            ],
            "em_version": __version__,
        }
        tmp = path.with_name(path.name + ".partial")
        tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _chmod(tmp, 0o600)
        os.replace(tmp, path)

    # --- read -----------------------------------------------------------

    def list(self) -> list[BackupInfo]:
        """Snapshots that have a manifest, newest first, in either layout.

        A ``.db`` file without a manifest (a pre-EM-210 migration backup, a
        hand-made copy) is not listed and never rotated away; a directory
        without a valid manifest is ignored the same way, and no symlink is
        followed.
        """
        out: list[BackupInfo] = []
        if not self.backup_dir.is_dir():
            return out
        for manifest in self.backup_dir.glob("*.json"):
            info = self._load_flat(manifest)
            if info is not None:
                out.append(info)
        for entry in self.backup_dir.iterdir():
            if entry.is_symlink() or not entry.is_dir() or not _DIR_RE.match(entry.name):
                continue
            info = self._load_directory(entry)
            if info is not None:
                out.append(info)
        out.sort(key=lambda i: (i.created_at, i.path.name), reverse=True)
        return out

    def latest(self, *, reason: str | None = None) -> BackupInfo | None:
        for info in self.list():
            if reason is None or info.reason == reason:
                return info
        return None

    def _load_flat(self, manifest: Path) -> BackupInfo | None:
        """A pre-3.1 backup: ``<name>.db`` beside ``<name>.json``, format 1."""
        try:
            doc = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(doc, dict) or doc.get("format") != 1:
            return None
        name = str(doc.get("file", ""))
        if not _NAME_RE.match(name) or Path(name).name != name:
            return None  # never follow a manifest out of the backup dir
        try:
            stored = BackupFile(
                role=ROLE_MEMORY,
                name=name,
                source=str(doc.get("source", "")),
                sha256=str(doc["sha256"]),
                size=int(doc["size"]),
                user_version=int(doc["user_version"]),
                counts={str(k): int(v) for k, v in dict(doc.get("counts") or {}).items()},
                audit=doc.get("audit"),
            )
            return BackupInfo(
                path=self.backup_dir / name,
                manifest_path=manifest,
                reason=str(doc["reason"]),
                created_at=str(doc["created_at"]),
                files=(stored,),
                flat=True,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _load_directory(self, directory: Path) -> BackupInfo | None:
        """A 3.1 snapshot: ``<reason>-<stamp>/`` with a ``files`` manifest."""
        manifest = directory / MANIFEST_NAME
        try:
            doc = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(doc, dict) or doc.get("format") != MANIFEST_FORMAT:
            return None
        entries = doc.get("files")
        if not isinstance(entries, list) or not entries:
            return None
        files: list[BackupFile] = []
        for entry in entries:
            if not isinstance(entry, dict):
                return None
            name = str(entry.get("name", ""))
            if not name or name == MANIFEST_NAME or Path(name).name != name:
                return None  # a snapshot file is a plain name, never a path
            try:
                files.append(
                    BackupFile(
                        role=str(entry["role"]),
                        name=name,
                        source=str(entry.get("source", "")),
                        sha256=str(entry["sha256"]),
                        size=int(entry["size"]),
                        user_version=int(entry["user_version"]),
                        counts={str(k): int(v) for k, v in dict(entry.get("counts") or {}).items()},
                        audit=entry.get("audit"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                return None
        try:
            return BackupInfo(
                path=directory,
                manifest_path=manifest,
                reason=str(doc["reason"]),
                created_at=str(doc["created_at"]),
                files=tuple(files),
            )
        except KeyError:
            return None

    def verify(self, info: BackupInfo) -> VerifyReport:
        """Re-check every file in a stored snapshot against its manifest."""
        problems: list[str] = []
        for stored in info.files:
            path = info.file_path(stored)
            if not path.is_file():
                problems.append(f"missing file {stored.name}")
                continue
            size = path.stat().st_size
            if size != stored.size:
                problems.append(f"{stored.name}: size {size} != manifest {stored.size}")
            digest = _sha256_file(path)
            if digest != stored.sha256:
                problems.append(f"{stored.name}: sha256 does not match manifest")
                continue  # don't open a file we know is altered
            more, user_version, counts, _ = _inspect_stored(path)
            problems.extend(f"{stored.name}: {p}" for p in more)
            if user_version != stored.user_version:
                problems.append(
                    f"{stored.name}: user_version {user_version} != manifest {stored.user_version}"
                )
            if counts != stored.counts:
                problems.append(f"{stored.name}: row counts differ from manifest")
        return VerifyReport(not problems, problems)

    # --- rotate ---------------------------------------------------------

    def rotate(self, *, keep: int = DEFAULT_KEEP, keep_safety: int = DEFAULT_KEEP_SAFETY) -> list[Path]:
        """Delete the oldest snapshots beyond the limits. Returns what went.

        One path per 3.1 snapshot (its directory); a legacy backup reports its
        ``.db`` and its ``.json``. Routine and safety backups have separate
        limits, so a burst of routine backups can never push out the backup
        taken before a migration. Only backups this manager wrote are touched.
        """
        if keep < 1 or keep_safety < 1:
            raise ValueError("rotation must keep at least one backup of each class")
        stored = self.list()
        routine = [i for i in stored if not i.is_safety]
        safety = [i for i in stored if i.is_safety]
        removed: list[Path] = []
        for info in routine[keep:] + safety[keep_safety:]:
            removed.extend(self._remove(info))
        return removed

    def _remove(self, info: BackupInfo) -> list[Path]:
        """Delete one stored snapshot: its directory, or the legacy pair."""
        paths = [info.path, info.manifest_path] if info.flat else [info.path]
        removed: list[Path] = []
        for path in paths:
            if path.parent != self.backup_dir or path.name in ("", ".", ".."):
                continue  # never delete anything outside the backup directory
            _rmtree(path)
            removed.append(path)
        return removed

    # --- restore --------------------------------------------------------

    def _safety_copy(self) -> BackupInfo | Path:
        """Keep what is about to be overwritten.

        Normally a verified ``pre-restore`` backup. But restore exists for the
        day the live database is broken, and a broken database may not snapshot
        (corrupt pages, a damaged WAL). Then the raw files (``.db``, ``-wal``,
        ``-shm``) are copied byte for byte into
        ``backups/pre-restore-raw-<stamp>/`` and restore goes ahead. Nothing is
        lost either way.
        """
        try:
            return self.create(reason="pre-restore")
        except (sqlite3.DatabaseError, BackupVerificationError):
            raw = self.backup_dir / f"pre-restore-raw-{_stamp(utc_now())}"
            n = 1
            while raw.exists():
                n += 1
                raw = raw.with_name(f"{raw.name.rsplit('~', 1)[0]}~{n}")
            raw.mkdir(parents=True)
            _chmod(raw, 0o700)
            for source in (self.db_path, self.index_path):
                for suffix in ("", "-wal", "-shm"):
                    src = source.with_name(source.name + suffix)
                    if src.is_file():
                        shutil.copyfile(src, raw / src.name)
                        _chmod(raw / src.name, 0o600)
            return raw

    def restore(self, info: BackupInfo, *, allow_live: bool = False) -> BackupInfo | Path | None:
        """Replace ``db_path`` with a verified copy of ``info``.

        Returns what was kept of the previous database: a ``pre-restore``
        ``BackupInfo``, or the directory of raw copies if the old database
        could not be snapshotted (see ``_safety_copy``), or None if there was
        no database. Stop the provider first: a running provider holds
        ``<db>.lock`` and the restore refuses.
        """
        if not allow_live:
            from .migrations import MigrationRefused, assert_safe_db_path

            try:
                assert_safe_db_path(self.db_path)
            except MigrationRefused as exc:
                raise RestoreRefused(f"{exc} (pass allow_live=True for a real restore)") from exc
        lock = self.db_path.with_name(self.db_path.name + ".lock")
        if FileLock.probe(lock):
            raise RestoreRefused("the provider is running (database lock is held); stop it first")
        report = self.verify(info)
        if not report.ok:
            raise RestoreRefused("backup failed verification: " + "; ".join(report.problems))

        safety = self._safety_copy() if self.db_path.is_file() else None

        # Stage every database of the snapshot first, and only swap when all of
        # them verify: a half-restored store would be worse than none.
        staged: list[tuple[Path, Path]] = []
        try:
            for stored in info.files:
                target = self._target_for(stored)
                target.parent.mkdir(parents=True, exist_ok=True)
                staging = target.with_name(target.name + ".restoring")
                _rmtree(staging)
                src = _open_ro(info.file_path(stored))
                try:
                    _copy_standalone(src, staging)
                finally:
                    src.close()
                problems, _, counts, _ = _inspect_stored(staging)
                if problems:
                    raise BackupError(
                        f"{stored.name}: restored copy failed verification "
                        f"({'; '.join(problems)}); live database untouched"
                    )
                if counts != stored.counts:
                    raise BackupError(
                        f"{stored.name}: restored copy failed verification "
                        "(row counts differ); live database untouched"
                    )
                _chmod(staging, 0o600)
                staged.append((staging, target))
        except BaseException:
            for staging, _ in staged:
                _rmtree(staging)
            raise

        for staging, target in staged:
            # A stale WAL from the old database would be replayed over the
            # restored file. The pre-restore backup above already captured it.
            for suffix in ("-wal", "-shm"):
                with contextlib.suppress(FileNotFoundError):
                    target.with_name(target.name + suffix).unlink()
            os.replace(staging, target)
        return safety

    def _target_for(self, stored: BackupFile) -> Path:
        """Where one snapshot file belongs in the live store."""
        if stored.role == ROLE_INDEX:
            return self.index_path
        if stored.role == ROLE_MEMORY:
            return self.db_path
        raise BackupError(f"snapshot file {stored.name} has an unknown role {stored.role!r}")


# --- scheduled backups as a job (EM-209 integration) -----------------------

BACKUP_JOB_TYPE = "backup"


def backup_dedupe_key(day: datetime) -> str:
    """One scheduled backup per UTC day."""
    return f"backup:{day.strftime('%Y-%m-%d')}"


def make_backup_handler(manager: BackupManager, *, keep: int = DEFAULT_KEEP):
    """Handler for ``backup`` jobs: create a scheduled backup, then rotate.

    Idempotent per day: if a ``scheduled`` backup already exists for the
    job's day (a re-run after a lost lease), it does nothing.
    """

    def handle(job, ctx) -> None:
        day = str(job.payload.get("day", ""))
        for info in manager.list():
            if info.reason == "scheduled" and info.created_at.startswith(day) and day:
                return
        manager.snapshot(reason="scheduled")
        manager.rotate(keep=keep)

    return handle


def enqueue_daily_backup(queue, *, now: datetime | None = None) -> str:
    """Queue today's scheduled backup (a no-op if it is already queued/done)."""
    when = now or utc_now()
    return queue.enqueue(
        BACKUP_JOB_TYPE,
        {"day": when.strftime("%Y-%m-%d")},
        dedupe_key=backup_dedupe_key(when),
        priority=8,
    )


__all__ = [
    "BACKUP_JOB_TYPE",
    "BackupError",
    "BackupFile",
    "BackupInfo",
    "BackupManager",
    "BackupVerificationError",
    "RestoreRefused",
    "VerifyReport",
    "backup_dedupe_key",
    "enqueue_daily_backup",
    "make_backup_handler",
]
