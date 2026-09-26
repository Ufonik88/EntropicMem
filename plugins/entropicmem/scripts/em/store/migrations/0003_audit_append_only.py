"""0003: append-only audit triggers on every v3 database (EM-206 fix).

``0002_v3_core`` creates ``audit_no_update`` and ``audit_no_delete`` only on the
v2-to-v3 path, after the rebuilt chain is final. Its fresh-install branch
returns early, before that step. So every new install (and every database
created from scratch in tests) got a hash-chained ``audit_log`` with nothing
stopping ``UPDATE`` or ``DELETE`` on it. The chain still *detects* tampering;
the triggers are what *refuse* it, and §3.3 wants both.

``0002`` is applied and checksummed, so it can't be edited. This migration adds
the triggers wherever they are missing. ``IF NOT EXISTS`` makes it a no-op on a
migrated v2 store that already has them. The statements are copied verbatim
from ``0002._AUDIT_TRIGGERS`` and deliberately not imported, so this file's
meaning can never change under its recorded checksum.
"""

from __future__ import annotations

import sqlite3

VERSION = 3
NAME = "audit_append_only"

_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
       BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
       WHEN (SELECT value FROM meta WHERE key='audit_purge_token') IS NULL
       BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END""",
)


def up(conn: sqlite3.Connection) -> None:
    for statement in _TRIGGERS:
        conn.execute(statement)
