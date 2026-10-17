"""The ``prune`` job handler — EM-303's orphaned promise, its own card.

Deletes ``embeddings`` rows for models that are neither the recorded current
model nor the immediately previous one, and only once the last completed
backfill's grace window has passed. Worker thread only, under the EM-209
contract (heartbeats; transient-permanent error split; never a dead job on a
backend-less or read-only box): the handler is reachable exclusively through
``em/jobs/registry.py``, and the drift guard test fails if anything else
imports it.

Refusal before deletion, never a guess (``docs/plan/PRUNE_CARD_DRAFT.md``):

* No ``meta.embedding_model`` → no completed backfill → no deletion (logged).
* No transition record (``embedding_model_previous`` /
  ``embedding_model_switched_at``, written by the backfill's completion
  transaction) → no rollback-set identity → no deletion (logged). The
  previous model is never guessable: deleting it while it is still the
  rollback set would break the flip-back recovery.
* ``now − embedding_model_switched_at`` ≤ the grace (default 7 days,
  payload-overridable) → nothing prunes; a partial backfill never authorizes
  deletion. The previous model's rows survive the grace too — the test plan
  arbitrates the draft's AC2 tail: the grace unlocks deletion for every
  model **beyond** current and previous; the previous model stays until a
  newer completed backfill demotes it.
* An unreadable ``switched_at`` → refuse (logged), never guess.

``dry_run`` reports per-model counts and deletes nothing. A real run commits
its deletes in one transaction and then vacuums on a dedicated autocommit
connection (SQLite forbids VACUUM inside a transaction) — bounded by the
worker's cron budget; a set too large for one budget is finished by the next
run, because the handler is idempotent.

Invented data only: Acme.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Callable

from ..clock import parse_iso, utc_now
from ..store.embeddings import (
    counts_by_model,
    delete_rows_for_models,
    stored_model,
    stored_model_previous,
    switched_at,
)

__all__ = ["make_prune_handler"]

log = logging.getLogger("em.embeddings.prune")

#: How long the previous model keeps its rows after the switch so a bad model
#: can be rolled back off them. Overridable per job via ``grace_days``.
DEFAULT_GRACE_DAYS = 7.0


def _vacuum(db_path: "str | Path", *, check: Callable[[], None]) -> None:
    """Return pages after a prune's deletes. Dedicated autocommit connection."""
    check()
    con = sqlite3.connect(str(db_path), isolation_level=None, timeout=30.0)
    try:
        con.execute("PRAGMA wal_checkpoint(FULL)")
        con.execute("VACUUM")
    finally:
        con.close()


def make_prune_handler(db_path: "str | Path") -> Callable:
    """Handler factory for the ``prune`` job type (worker thread only)."""

    def handle(job, ctx) -> None:
        payload = job.payload or {}
        dry_run = bool(payload.get("dry_run"))
        try:
            grace_days = float(payload.get("grace_days", DEFAULT_GRACE_DAYS))
        except (TypeError, ValueError):
            grace_days = DEFAULT_GRACE_DAYS

        stamp = stored_model(ctx.store.reader())
        if not stamp:
            # Guard 1: a store that never completed a backfill has no model
            # identity at all — nothing is prunable, on any clock.
            log.info("prune: no current model recorded; nothing to prune")
            return
        previous = stored_model_previous(ctx.store.reader())
        switched = switched_at(ctx.store.reader())
        if not previous or not switched:
            # Guard 2: no rollback-set identity. Refuse rather than delete —
            # an unknown previous would make the rollback set prunable, and
            # that is exactly the failure mode the draft's risk section calls out.
            log.info("prune: transition record incomplete; refusing to prune")
            return

        try:
            switched_dt = parse_iso(switched)
        except (ValueError, TypeError) as exc:
            log.info("prune: transition record unreadable; refusing to prune (%s)", exc)
            return
        age = utc_now() - switched_dt
        if age <= timedelta(days=grace_days):
            log.info(
                "prune: the switch is %d day(s) old and the grace is %d day(s);"
                " nothing prunes yet",
                age.days,
                int(grace_days),
            )
            return

        counts = counts_by_model(ctx.store.reader())
        keep = {stamp, previous}
        prunable = [m for m in counts if m not in keep]
        if not prunable:
            log.info("prune: nothing beyond the current and previous models")
            return

        if dry_run:
            report = ", ".join(f"{m}={counts[m]}" for m in prunable)
            log.info("prune: dry-run; would delete %s", report)
            return

        with ctx.store.transaction() as conn:
            deleted = delete_rows_for_models(conn, prunable)
        log.info(
            "prune: deleted %d stale embeddings row(s) for %s",
            deleted,
            ", ".join(prunable),
        )
        _vacuum(db_path, check=_deletes_committed(ctx.store, prunable))

    return handle


def _deletes_committed(store, prunable: list[str]) -> Callable[[], None]:
    """The ``check`` hook under the vacuum: the deletes are already visible."""

    def check() -> None:
        conn = store.reader()
        marks = ",".join("?" for _ in prunable)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM embeddings WHERE model IN ({marks})",
            tuple(prunable),
        ).fetchone()
        assert row is not None and row["n"] == 0, (
            "vacuum must follow the committed delete"
        )

    return check
