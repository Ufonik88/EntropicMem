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
3. **Manifest.** ``<name>.json`` sits next to ``<name>.db`` with the sha256,
   size, counts, schema version and reason. ``verify()`` re-hashes against it
   later, which catches bit rot and truncation. Only then is the ``.partial``
   file renamed into place.

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
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..clock import to_iso, utc_now
from .locking import FileLock

MANIFEST_FORMAT = 1

#: Reasons that are safety nets for a risky operation. Rotation keeps them
#: under their own (separate) limit so routine backups never push them out.
SAFETY_PREFIXES = ("pre-migrate", "pre-restore")

DEFAULT_KEEP = 7
DEFAULT_KEEP_SAFETY = 5

_REASON_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_NAME_RE = re.compile(r"^(?P<reason>[a-z0-9][a-z0-9-]*)-(?P<stamp>\d{8}-\d{6}-\d{3})(?:-(?P<n>\d+))?\.db$")


class BackupError(RuntimeError):
    """Base class for backup failures."""


class BackupVerificationError(BackupError):
    """A fresh snapshot failed verification. Nothing was kept."""


class RestoreRefused(BackupError):
    """Restore preconditions not met. Nothing was changed."""


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    manifest_path: Path
    reason: str
    created_at: str
    sha256: str
    size: int
    user_version: int
    counts: dict[str, int]
    audit: Optional[dict[str, Any]]

    @property
    def is_safety(self) -> bool:
        return self.reason.startswith(SAFETY_PREFIXES)


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


# --- manager ---------------------------------------------------------------


class BackupManager:
    """Backups of one database file, kept in one directory.

    ``backup_dir`` defaults to ``<db dir>/backups``, the directory migrations
    have always used.
    """

    def __init__(self, db_path: "os.PathLike[str] | str", backup_dir: "os.PathLike[str] | str | None" = None) -> None:
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir) if backup_dir is not None else self.db_path.parent / "backups"

    # --- create ---------------------------------------------------------

    def create(self, *, reason: str = "manual", conn: sqlite3.Connection | None = None) -> BackupInfo:
        """Snapshot, verify and record one backup.

        ``conn``: back up through an existing connection (migrations pass
        theirs, so the snapshot is exactly what they are about to change).
        Otherwise the database is opened read-only for the copy.
        """
        if not _REASON_RE.match(reason):
            raise ValueError(f"reason must be lowercase letters, digits and dashes: {reason!r}")
        if conn is None and not self.db_path.is_file():
            raise BackupError(f"no database at {self.db_path}")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        _chmod(self.backup_dir, 0o700)

        now = utc_now()
        dest = self._free_name(reason, now)
        partial = dest.with_name(dest.name + ".partial")
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()

        source = conn if conn is not None else _open_ro(self.db_path)
        try:
            _copy_standalone(source, partial)
        finally:
            if conn is None:
                source.close()
        _chmod(partial, 0o600)

        check = _open_ro(partial)
        try:
            problems, user_version, counts, audit = _inspect(check)
        finally:
            check.close()
        if problems:
            with contextlib.suppress(FileNotFoundError):
                partial.unlink()
            raise BackupVerificationError("; ".join(problems))

        info = BackupInfo(
            path=dest,
            manifest_path=dest.with_suffix(".json"),
            reason=reason,
            created_at=to_iso(now),
            sha256=_sha256_file(partial),
            size=partial.stat().st_size,
            user_version=user_version,
            counts=counts,
            audit=audit,
        )
        self._write_manifest(info)
        os.replace(partial, dest)
        return info

    def _free_name(self, reason: str, now: datetime) -> Path:
        base = f"{reason}-{_stamp(now)}"
        dest = self.backup_dir / f"{base}.db"
        n = 1
        while dest.exists() or dest.with_suffix(".json").exists():
            n += 1
            dest = self.backup_dir / f"{base}-{n}.db"
        return dest

    def _write_manifest(self, info: BackupInfo) -> None:
        from .. import __version__

        doc = {
            "format": MANIFEST_FORMAT,
            "file": info.path.name,
            "source": self.db_path.name,
            "reason": info.reason,
            "created_at": info.created_at,
            "sha256": info.sha256,
            "size": info.size,
            "user_version": info.user_version,
            "counts": info.counts,
            "audit": info.audit,
            "em_version": __version__,
        }
        tmp = info.manifest_path.with_name(info.manifest_path.name + ".partial")
        tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _chmod(tmp, 0o600)
        os.replace(tmp, info.manifest_path)

    # --- read -----------------------------------------------------------

    def list(self) -> list[BackupInfo]:
        """Backups that have a manifest, newest first.

        A ``.db`` file without a manifest (a pre-EM-210 migration backup, a
        hand-made copy) is not listed and never rotated away.
        """
        out: list[BackupInfo] = []
        if not self.backup_dir.is_dir():
            return out
        for manifest in self.backup_dir.glob("*.json"):
            info = self._load(manifest)
            if info is not None:
                out.append(info)
        out.sort(key=lambda i: (i.created_at, i.path.name), reverse=True)
        return out

    def latest(self, *, reason: str | None = None) -> BackupInfo | None:
        for info in self.list():
            if reason is None or info.reason == reason:
                return info
        return None

    def _load(self, manifest: Path) -> BackupInfo | None:
        try:
            doc = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(doc, dict) or doc.get("format") != MANIFEST_FORMAT:
            return None
        name = str(doc.get("file", ""))
        if not _NAME_RE.match(name) or Path(name).name != name:
            return None  # never follow a manifest out of the backup dir
        return BackupInfo(
            path=self.backup_dir / name,
            manifest_path=manifest,
            reason=str(doc["reason"]),
            created_at=str(doc["created_at"]),
            sha256=str(doc["sha256"]),
            size=int(doc["size"]),
            user_version=int(doc["user_version"]),
            counts={str(k): int(v) for k, v in dict(doc.get("counts") or {}).items()},
            audit=doc.get("audit"),
        )

    def verify(self, info: BackupInfo) -> VerifyReport:
        """Re-check a stored backup against its manifest and itself."""
        problems: list[str] = []
        if not info.path.is_file():
            return VerifyReport(False, [f"missing file {info.path.name}"])
        size = info.path.stat().st_size
        if size != info.size:
            problems.append(f"size {size} != manifest {info.size}")
        digest = _sha256_file(info.path)
        if digest != info.sha256:
            problems.append("sha256 does not match manifest")
            return VerifyReport(False, problems)  # don't open a file we know is altered
        conn = _open_ro(info.path)
        try:
            more, user_version, counts, _ = _inspect(conn)
        except sqlite3.DatabaseError as exc:
            return VerifyReport(False, problems + [f"unreadable: {exc}"])
        finally:
            conn.close()
        problems.extend(more)
        if user_version != info.user_version:
            problems.append(f"user_version {user_version} != manifest {info.user_version}")
        if counts != info.counts:
            problems.append("row counts differ from manifest")
        return VerifyReport(not problems, problems)

    # --- rotate ---------------------------------------------------------

    def rotate(self, *, keep: int = DEFAULT_KEEP, keep_safety: int = DEFAULT_KEEP_SAFETY) -> list[Path]:
        """Delete the oldest backups beyond the limits. Returns removed files.

        Routine and safety backups have separate limits, so a burst of routine
        backups can never push out the backup taken before a migration.
        """
        if keep < 1 or keep_safety < 1:
            raise ValueError("rotation must keep at least one backup of each class")
        routine = [i for i in self.list() if not i.is_safety]
        safety = [i for i in self.list() if i.is_safety]
        removed: list[Path] = []
        for info in routine[keep:] + safety[keep_safety:]:
            for p in (info.path, info.manifest_path):
                with contextlib.suppress(FileNotFoundError):
                    p.unlink()
                    removed.append(p)
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
            import shutil

            raw = self.backup_dir / f"pre-restore-raw-{_stamp(utc_now())}"
            n = 1
            while raw.exists():
                n += 1
                raw = raw.with_name(f"{raw.name.rsplit('~', 1)[0]}~{n}")
            raw.mkdir(parents=True)
            _chmod(raw, 0o700)
            for suffix in ("", "-wal", "-shm"):
                src = self.db_path.with_name(self.db_path.name + suffix)
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

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.db_path.with_name(self.db_path.name + ".restoring")
        with contextlib.suppress(FileNotFoundError):
            staging.unlink()
        src = _open_ro(info.path)
        try:
            _copy_standalone(src, staging)
        finally:
            src.close()
        check = _open_ro(staging)
        try:
            problems, _, counts, _ = _inspect(check)
        finally:
            check.close()
        if problems or counts != info.counts:
            with contextlib.suppress(FileNotFoundError):
                staging.unlink()
            raise BackupError("restored copy failed verification; live database untouched")
        _chmod(staging, 0o600)
        # A stale WAL from the old database would be replayed over the
        # restored file. The pre-restore backup above already captured it.
        for suffix in ("-wal", "-shm"):
            with contextlib.suppress(FileNotFoundError):
                self.db_path.with_name(self.db_path.name + suffix).unlink()
        os.replace(staging, self.db_path)
        return safety


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
        manager.create(reason="scheduled")
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
    "BackupInfo",
    "BackupManager",
    "BackupVerificationError",
    "RestoreRefused",
    "VerifyReport",
    "backup_dedupe_key",
    "enqueue_daily_backup",
    "make_backup_handler",
]
