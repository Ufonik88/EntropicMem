"""``entropicmem worker run`` (EM-209).

Thin entry point over ``JobWorker``. It never migrates, and it refuses a
database that is not already v3 before any write handle is opened.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from em.formation.entity_linker import make_link_handler
from em.jobs.worker import HandlerRegistry, JobWorker
from em.store.backup import BackupManager, make_backup_handler
from em.store.db import Store, open_db
from em.store.migrations import MigrationRefused, assert_safe_db_path

# Columns from migration 0002. A table named ``jobs`` with a different shape
# is not v3, and this command will not migrate it into one.
_V3_JOB_COLUMNS = frozenset({
    "id", "type", "payload", "dedupe_key", "status", "priority", "attempts",
    "max_attempts", "run_after", "locked_by", "locked_until", "last_error",
    "created_at", "updated_at",
})

_KNOWN_TYPES = ("backup", "link", "embed", "embed_backfill")


def run_worker(
    db_path: Path,
    *,
    once: bool = False,
    types: list[str] | None = None,
    max_seconds: float | None = None,
) -> int:
    """Run queued jobs. Prints one JSON line. Exit 1 if any job is dead."""
    unknown = [name for name in (types or []) if name not in _KNOWN_TYPES]
    if unknown:
        print("unknown job type: " + ", ".join(unknown), file=sys.stderr)
        return 1

    try:
        assert_safe_db_path(db_path)
    except MigrationRefused as exc:
        print(exc, file=sys.stderr)
        return 1

    if not _is_v3(db_path):
        print(
            f"refusing to run: {db_path} is not a v3 database "
            "(no jobs table with the v3 shape). This command never migrates.",
            file=sys.stderr,
        )
        return 1

    selected = list(types) if types else list(_KNOWN_TYPES)
    registry = HandlerRegistry()
    if "backup" in selected:
        registry.register("backup", make_backup_handler(BackupManager(db_path)))
    if "link" in selected:
        registry.register("link", make_link_handler())
    if "embed" in selected or "embed_backfill" in selected:
        from ..embeddings.jobs import make_embed_backfill_handler, make_embed_handler
        from ..embeddings.service import EmbeddingService

        service = EmbeddingService(str(db_path))
        if "embed" in selected:
            registry.register("embed", make_embed_handler(service))
        if "embed_backfill" in selected:
            registry.register("embed_backfill", make_embed_backfill_handler(service))

    store = Store(str(db_path))
    try:
        outcomes = _run(JobWorker(store, registry), once=once, max_seconds=max_seconds)
    finally:
        store.close()

    counts = {"done": 0, "failed": 0, "dead": 0, "lost": 0}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    print(json.dumps(counts))
    return 1 if counts["dead"] else 0


def _is_v3(path: Path) -> bool:
    """Read-only shape check. A missing file is not v3, and is not created."""
    if not path.is_file():
        return False
    conn = open_db(path, readonly=True)
    try:
        found = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        if found is None:
            return False
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        return _V3_JOB_COLUMNS <= columns
    finally:
        conn.close()


def _run(worker: JobWorker, *, once: bool, max_seconds: float | None):
    if once:
        outcome = worker.run_once()
        return [] if outcome is None else [outcome]
    if max_seconds is None:
        return worker.run_until_idle()
    deadline = time.monotonic() + max_seconds
    outcomes = []
    while time.monotonic() < deadline:
        outcome = worker.run_once()
        if outcome is None:
            break
        outcomes.append(outcome)
    return outcomes
