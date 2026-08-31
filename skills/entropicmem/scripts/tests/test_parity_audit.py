#!/usr/bin/env python3
"""test_parity_audit.py — Unit tests for EntropicMem P3 parity audit CLI.

Schema contract (mirrors memory_engine.py v2.5.0):
- SHARED store: sync_events (append-only origin log) ONLY.
- LOCAL (canonical) store: facts, sync_outbox, shared_facts (projection),
  sync_offsets (per-store read position).
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from parity_audit import (  # noqa: E402
    audit_post_backfill,
    audit_pre_backfill,
    run_parity_audit,
)


class TestParityAudit(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

        self.canonical_path = self.tmp_path / "canonical.db"
        self.shared_path = self.tmp_path / "shared.db"
        self.profiles_dir = self.tmp_path / "profiles"
        self.profiles_dir.mkdir()

        # Init canonical (LOCAL schema: facts, outbox, projection, offsets)
        conn = sqlite3.connect(str(self.canonical_path))
        conn.executescript("""
            CREATE TABLE facts (
                id TEXT PRIMARY KEY,
                content TEXT,
                deleted INTEGER DEFAULT 0,
                sensitivity TEXT DEFAULT 'internal'
            );
            CREATE TABLE sync_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_id TEXT,
                emitted INTEGER DEFAULT 0
            );
            CREATE TABLE shared_facts (
                fact_id TEXT,
                origin_store TEXT,
                deleted INTEGER DEFAULT 0,
                sensitivity TEXT DEFAULT 'internal',
                PRIMARY KEY (fact_id, origin_store)
            );
            CREATE TABLE sync_offsets (store_id TEXT PRIMARY KEY);
        """)
        conn.commit()
        conn.close()

        # Init shared (sync_events only)
        conn = sqlite3.connect(str(self.shared_path))
        conn.executescript("""
            CREATE TABLE sync_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                origin_store TEXT DEFAULT 'default',
                fact_id TEXT
            );
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_pre_backfill_expected_empty(self):
        canonical = sqlite3.connect(str(self.canonical_path))
        shared = sqlite3.connect(str(self.shared_path))
        try:
            res = audit_pre_backfill(shared, canonical)
            self.assertTrue(res["expected_empty"])
            self.assertEqual(res["status"], "ok")
        finally:
            canonical.close()
            shared.close()

    def test_post_backfill_divergence(self):
        # Add a publishable fact to canonical but no shared event -> divergence
        canonical = sqlite3.connect(str(self.canonical_path))
        canonical.execute("INSERT INTO facts (id, content, deleted) VALUES ('f1', 'hello', 0)")
        canonical.commit()
        canonical.close()

        shared = sqlite3.connect(str(self.shared_path))
        try:
            res = audit_post_backfill(shared, sqlite3.connect(str(self.canonical_path)))
            self.assertTrue(res["divergence"])
            self.assertEqual(res["status"], "fail")
        finally:
            shared.close()

    def test_post_backfill_converged(self):
        # Every publishable fact has a shared event; secret facts filtered out
        canonical = sqlite3.connect(str(self.canonical_path))
        canonical.execute("INSERT INTO facts (id, content, deleted) VALUES ('f1', 'hello', 0)")
        canonical.execute(
            "INSERT INTO facts (id, content, deleted, sensitivity) "
            "VALUES ('s1', 'secret thing', 0, 'secret')"
        )
        canonical.commit()
        canonical.close()

        shared = sqlite3.connect(str(self.shared_path))
        shared.execute("INSERT INTO sync_events (fact_id) VALUES ('f1')")
        shared.commit()
        shared.close()

        res = run_parity_audit(self.canonical_path, self.shared_path, self.profiles_dir)
        self.assertEqual(res["divergence"], False)
        self.assertEqual(res["secret_leaked"], 0)
        self.assertEqual(res["status"], "ok")

    def test_secret_leak_detection(self):
        # A secret fact id must never appear in the shared log
        canonical = sqlite3.connect(str(self.canonical_path))
        canonical.execute("INSERT INTO facts (id, content, deleted) VALUES ('f1', 'hello', 0)")
        canonical.execute(
            "INSERT INTO facts (id, content, deleted, sensitivity) "
            "VALUES ('s1', 'secret thing', 0, 'secret')"
        )
        canonical.commit()
        canonical.close()

        shared = sqlite3.connect(str(self.shared_path))
        shared.execute("INSERT INTO sync_events (fact_id) VALUES ('f1')")
        shared.execute("INSERT INTO sync_events (fact_id) VALUES ('s1')")
        shared.commit()
        shared.close()

        res = run_parity_audit(self.canonical_path, self.shared_path, self.profiles_dir)
        self.assertEqual(res["secret_leaked"], 1)
        self.assertEqual(res["status"], "fail")


if __name__ == "__main__":
    unittest.main()
