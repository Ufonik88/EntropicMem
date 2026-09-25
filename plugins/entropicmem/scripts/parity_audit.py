#!/usr/bin/env python3
"""
parity_audit.py — EntropicMem P3 parity audit CLI.

Compares canonical memory store against shared sync log and subscriber
projections. Implements the gated contract:

- pre-backfill expected state: outbox >= 0 + shared == 0 => OK
- post-backfill divergence: shared_facts projection != canonical => FAIL

Usage:
  entropicmem parity-audit [--canonical PATH] [--shared PATH] [--profiles-dir PATH]
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


def _hermes_base() -> Path:
    """Default Hermes home (~/.hermes).

    H3/EM-102: no HERMES_HOME env read (parity_audit runs as a library too);
    callers with a non-default home pass explicit --canonical/--shared/
    --profiles-dir paths.
    """
    return Path.home() / ".hermes"

DEFAULT_CANONICAL = _hermes_base() / "entropicmem" / "memory.db"
DEFAULT_SHARED = _hermes_base() / "entropicmem-shared" / "memory.db"
DEFAULT_PROFILES_DIR = _hermes_base() / "profiles"


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _rowcount(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else 0


def audit_pre_backfill(shared: sqlite3.Connection, canonical: sqlite3.Connection) -> Dict[str, Any]:
    # shared_facts projection + sync_offsets live in the LOCAL store; the
    # shared DB holds only the append-only sync_events log (SHARED_SCHEMA).
    local_projection = _rowcount(canonical, "SELECT count(*) FROM shared_facts")
    outbox_count = _rowcount(canonical, "SELECT count(*) FROM sync_outbox WHERE emitted=0")
    sync_events = _rowcount(shared, "SELECT count(*) FROM sync_events")
    local_offsets = _rowcount(canonical, "SELECT count(*) FROM sync_offsets")
    return {
        "expected_empty": local_projection == 0 and sync_events == 0 and local_offsets == 0,
        "shared_facts": local_projection,
        "sync_events": sync_events,
        "sync_offsets": local_offsets,
        "outbox_pending": outbox_count,
        "status": "ok" if local_projection == 0 and sync_events == 0 else "divergence",
    }


def audit_post_backfill(
    shared: sqlite3.Connection,
    canonical: sqlite3.Connection,
    profile_stores: Optional[Dict[str, Path]] = None,
) -> Dict[str, Any]:
    """Post-backfill parity against the shared sync_events log.

    Contract (matches memory_engine v2.5.0 schema split):
    - publishable = non-deleted, non-secret/sensitive canonical facts
    - every publishable fact must appear in the shared log at least once
    - no secret/sensitive fact id may appear in the shared log
    - subscriber projection drift is measured per profile store
    """
    publishable = _rowcount(
        canonical,
        "SELECT count(*) FROM facts WHERE deleted=0 "
        "AND lower(coalesce(sensitivity,'internal')) NOT IN ('secret','sensitive')",
    )
    covered = _rowcount(shared, "SELECT count(DISTINCT fact_id) FROM sync_events")
    secret_ids = [
        r["id"]
        for r in canonical.execute(
            "SELECT id FROM facts WHERE deleted=0 "
            "AND lower(coalesce(sensitivity,'internal')) IN ('secret','sensitive')"
        ).fetchall()
    ]
    secret_leaked = (
        _rowcount(
            shared,
            "SELECT count(*) FROM sync_events WHERE fact_id IN "
            "(%s)" % ",".join("?" * len(secret_ids)),
            tuple(secret_ids),
        )
        if secret_ids
        else 0
    )
    divergence = covered < publishable

    subscriber_drift: Dict[str, Optional[int]] = {}
    if profile_stores:
        for profile, path in profile_stores.items():
            if not Path(path).exists():
                subscriber_drift[profile] = None
                continue
            try:
                sub = _connect(Path(path))
                projected = _rowcount(sub, "SELECT count(*) FROM shared_facts WHERE deleted=0")
                subscriber_drift[profile] = projected - covered
                sub.close()
            except Exception:
                subscriber_drift[profile] = None

    return {
        "expected_empty": False,
        "canonical_facts": publishable,
        "shared_facts": covered,
        "secret_leaked": secret_leaked,
        "subscriber_drift": subscriber_drift,
        "divergence": divergence,
        "status": "ok" if not divergence and secret_leaked == 0 else "fail",
    }


def discover_profile_stores(profiles_dir: Path) -> Dict[str, Path]:
    stores: Dict[str, Path] = {}
    if not profiles_dir.is_dir():
        return stores
    for entry in profiles_dir.iterdir():
        if entry.is_dir():
            candidate = entry / "entropicmem" / "memory.db"
            if candidate.exists():
                stores[entry.name] = candidate
    return stores


def run_parity_audit(
    canonical: Path,
    shared: Path,
    profiles_dir: Path,
) -> Dict[str, Any]:
    if not canonical.exists() or not shared.exists():
        return {
            "status": "fail",
            "error": f"missing store: canonical={canonical} shared={shared}",
        }

    canonical_conn = _connect(canonical)
    shared_conn = _connect(shared)
    try:
        outbox_count = _rowcount(canonical_conn, "SELECT count(*) FROM sync_outbox WHERE emitted=0")
        pre = audit_pre_backfill(shared_conn, canonical_conn)
        profile_stores = discover_profile_stores(profiles_dir)
        post = audit_post_backfill(shared_conn, canonical_conn, profile_stores)

        mode = "pre-backfill" if pre["expected_empty"] else "post-backfill"
        result = pre if pre["expected_empty"] else post
        result["mode"] = mode
        result["outbox_pending"] = outbox_count
        result["profiles_scanned"] = len(profile_stores)
        result["status"] = result.get("status", "ok")
        return result
    finally:
        canonical_conn.close()
        shared_conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="entropicmem parity-audit")
    parser.add_argument("--canonical", default=str(DEFAULT_CANONICAL))
    parser.add_argument("--shared", default=str(DEFAULT_SHARED))
    parser.add_argument("--profiles-dir", default=str(DEFAULT_PROFILES_DIR))
    args = parser.parse_args(argv)

    result = run_parity_audit(
        Path(args.canonical),
        Path(args.shared),
        Path(args.profiles_dir),
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
