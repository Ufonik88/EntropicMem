"""The v3 **shadow read** (P0) — exercise S3 on real turns without committing the store.

The cutover is deferred until the provider reads through S3, but a v3 read path only
exists once the store *is* v3 (engine selection is by ``PRAGMA user_version``). The
shadow is the way out of that circle: **the turn is served by v2 exactly as today**,
and S3 runs afterwards, off the turn path, over a **v3 copy**, writing a divergence
line. Nothing about the live store, its schema, or the served answer changes.

What this module guarantees, and how each is checked rather than asserted:

* **The flag is off by default.** ``ENTROPICMEM_SHADOW_V3`` unset means this module
  does nothing at all.
* **The served response is untouched when the flag is on.** The provider's
  ``_spawn_shadow`` runs *after* the response is built, and it is submitted to a
  background thread; a test blocks that thread on an event and asserts the response
  still returns, which is a proof rather than an inspection.
* **The live store is never written** (repo rule 3). The refresh reads it with a
  read-only connection and writes only the copy.

**Two biases this design cannot remove, so every line states them:**

* ``copy_age_s`` — the copy **lags**. A stale copy makes v3 look *less* diverged than
  it is, so **divergence here is a lower bound**, and it will read as "v3 is fine"
  when the truth is "the copy is old". The age is on every line, and ``stale`` marks
  the lines that exceed the bound.
* v3 scores today are **lexical, entity and episodic only** — no vector generator and
  no cosine support condition until EM-303. Divergence numbers are therefore **not**
  an apples-to-apples quality comparison against v2, and the line says so.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: Points at the **v3 copy** the shadow reads. Unset (the default) disables the shadow.
SHADOW_ENV = "ENTROPICMEM_SHADOW_V3"
#: Where divergence lines go. Defaults beside the copy.
LOG_ENV = "ENTROPICMEM_SHADOW_LOG"

#: A copy older than this is refreshed before use, and the line that used a stale one
#: is marked. 15 minutes is a bound, not a target: each refresh re-runs the migration.
MAX_COPY_AGE_S = 900.0

_DEFAULT_DIR = "entropicmem-shadow"

#: What a divergence report must carry, because neither bias can be designed away.
CAVEAT = (
    "v3 scores are lexical/entity/episodic only (no vectors or cosine until EM-303), "
    "and divergence is a LOWER BOUND because the copy lags"
)

#: The promotion observable, **fixed before any data is collected** so the threshold
#: cannot be chosen to fit the sample. An agent proposal, not an owner decision.
#:
#: The rule: shadow enough real turns to be worth reading, with a fresh copy, and
#: promote to *default* only when v3 has not once injected a memory v2 did not
#: (``max_v3_only``) — because the failure that matters is v3 fabricating a hit, not
#: v3 missing one — and when its off-turn cost stays inside the prefetch budget that
#: EM-403 will be measured against.
PROMOTION: Dict[str, Any] = {
    "min_turns": 200,
    "max_copy_age_s": MAX_COPY_AGE_S,
    "max_divergence_rate": 0.10,   # |v2_ids XOR v3_ids| > 0, over turns with injection
    "max_v3_only": 0,              # v3 must never inject something v2 did not
    "max_p95_shadow_ms": 150.0,    # §4.2's warm prefetch budget, off-turn
}

_ID_RE = re.compile(r"^- \[([^\]]+)\]", re.MULTILINE)


def injected_ids(block: str) -> List[str]:
    """Ids of the bullets in a rendered block — the same shape `evals.runner` reads."""
    return _ID_RE.findall(block or "")


def shadow_path() -> Optional[Path]:
    """The v3 copy to read, or ``None`` when the shadow is off (the default)."""
    raw = os.environ.get(SHADOW_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def log_path() -> Path:
    raw = os.environ.get(LOG_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    base = shadow_path()
    parent = base.parent if base is not None else Path(tempfile.gettempdir()) / _DEFAULT_DIR
    return parent / "divergence.jsonl"


def copy_age_s(path: Path) -> Optional[float]:
    """Seconds since the copy was written, or ``None`` when there is no copy yet."""
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def refresh(live_db: str | Path, shadow_db: Path) -> None:
    """Refresh the copy from the live store, then migrate it (§3.3's real path).

    **The live store is opened read-only and never written**; only the copy is.
    ``sqlite3.Connection.backup`` is the online-copy primitive, so a concurrent
    writer on the live store is fine.

    The copy is migrated rather than trusted, which means the shadow exercises the
    *migration* on every refresh — the same code the real cutover runs, on
    throwaway data, long before the cutover happens.
    """
    from em.store.db import open_db
    from em.store.migrations import migrate

    shadow_db.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{live_db}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(str(shadow_db))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    connection = open_db(shadow_db)
    try:
        migrate(connection)
    finally:
        connection.close()


def comparison_ids(conn: sqlite3.Connection, ids: Sequence[str]) -> List[str]:
    """Map v3 ids onto the ids **v2 knows**, so the two sets are comparable.

    The two stacks name the same memory differently: v2 uses the 16-hex content id and
    v3 uses a ``mem_…`` ULID, keeping the v2 id in ``legacy_id`` — which is exactly what
    that column is for. Comparing raw ids therefore marks **every** memory as a
    divergence, reports "v3 fabricated a hit" on every line, and would trip the
    ``v3_only == 0`` promotion condition on the first day. The comparison id is
    ``COALESCE(legacy_id, id)``: a migrated row compares by the id v2 already uses, and
    a row written straight to v3 keeps its own, so it still reads as v3-only.

    Discovered by running the shadow end to end against a real migrated store; the unit
    tests passed while every real line would have been meaningless.
    """
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return []
    marks = ",".join("?" for _ in wanted)
    try:
        rows = conn.execute(
            f"SELECT id, COALESCE(legacy_id, id) AS comparison FROM memories"
            f" WHERE id IN ({marks})",
            wanted,
        ).fetchall()
        mapping = {row["id"]: row["comparison"] for row in rows}
    except sqlite3.Error:
        return wanted
    return [mapping.get(item, item) for item in wanted]


def shadow_ids(shadow_db: Path, *, profile: str, query: str) -> List[str]:
    """Run S3 over the copy and return the injected ids, mapped for comparison."""
    from em.retrieval.pipeline import retrieve
    from em.store.db import Store
    from em.store.types import Scope

    store = Store(str(shadow_db))
    try:
        connection = store.reader()
        outcome = retrieve(
            connection, scope=Scope(profile=profile or "default"), query=query, with_gate=True
        )
        return comparison_ids(connection, outcome.ids)
    finally:
        store.close()


def run(
    live_db: str | Path,
    *,
    profile: str,
    query: str,
    v2_ids: Sequence[str],
    now: Optional[datetime] = None,
    destination: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Refresh-or-reuse the copy, run S3 over it, and append one divergence line.

    Returns the line, or ``None`` when the shadow is off or failed. **Never raises**:
    a diagnostic that can break a turn is worse than no diagnostic.
    """
    target = shadow_path()
    if target is None:
        return None

    started = time.perf_counter()
    try:
        age = copy_age_s(target)
        refreshed = age is None or age > MAX_COPY_AGE_S
        if refreshed:
            refresh(live_db, target)
            age = 0.0
        v3_ids = shadow_ids(target, profile=profile, query=query)
    except Exception as exc:  # noqa: BLE001 - a shadow must never break a turn
        logger.debug("EntropicMem v3 shadow failed: %s", exc)
        return None

    moment = now or datetime.now(timezone.utc)
    line: Dict[str, Any] = {
        "ts": moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "query": (query or "")[:200],
        "v2_ids": list(v2_ids),
        "v3_ids": v3_ids,
        "divergence": sorted(set(v2_ids) ^ set(v3_ids)),
        "v3_only": sorted(set(v3_ids) - set(v2_ids)),
        # The staleness bound travels with every number, so a stale copy cannot be
        # read as agreement.
        "copy_age_s": round(age, 1),
        "copy_refreshed": refreshed,
        "stale": age > MAX_COPY_AGE_S,
        "shadow_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "caveat": CAVEAT,
    }
    _append(line, destination or log_path())
    return line


def _append(line: Dict[str, Any], destination: Path) -> None:
    """Best-effort JSONL append: one line per turn, and never fatal."""
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        logger.debug("EntropicMem shadow log write failed: %s", exc)
