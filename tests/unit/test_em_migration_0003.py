"""0003_audit_append_only: every v3 database refuses audit edits (EM-206 fix)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.store import audit as em_audit  # noqa: E402
from em.store import db as emdb  # noqa: E402
from em.store import migrations as emmig  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "db"


def _triggers(conn) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_log'"
        )
    }


def _seed_audit(conn) -> None:
    with emdb.write_txn(conn):
        em_audit.append(conn, "memory.write", "tester", "mem_1", {"n": 1})
        em_audit.append(conn, "memory.write", "tester", "mem_2", {"n": 2})


def test_registered_as_version_3():
    found = {m.version: m.name for m in emmig.discover()}
    assert found[3] == "audit_append_only"
    assert emmig.LATEST >= 3


def test_fresh_install_refuses_audit_update_and_delete(tmp_path):
    """The bug: 0002's fresh-install branch returned before creating the
    triggers, so a brand-new store's audit log accepted UPDATE and DELETE."""
    conn = emdb.open_db(tmp_path / "fresh.db")
    emmig.migrate(conn)
    assert _triggers(conn) == {"audit_no_update", "audit_no_delete"}
    _seed_audit(conn)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with emdb.write_txn(conn):
            conn.execute("UPDATE audit_log SET action='forged'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with emdb.write_txn(conn):
            conn.execute("DELETE FROM audit_log")
    assert em_audit.verify(conn).ok
    conn.close()


def test_a_database_already_at_v2_gets_the_triggers(tmp_path):
    """Dev and test stores created before 0003 existed sit at user_version 2
    with no triggers; upgrading them must close the gap."""
    conn = emdb.open_db(tmp_path / "v2.db")
    emmig.migrate(conn, target=2)
    assert _triggers(conn) == set(), "precondition: 0002 fresh install has none"
    applied = emmig.migrate(conn)
    assert [m.version for m in applied] == list(range(3, emmig.LATEST + 1))
    assert _triggers(conn) == {"audit_no_update", "audit_no_delete"}
    conn.close()


def test_migrated_v2_store_keeps_exactly_one_copy_of_each(tmp_path):
    """0002's v2 path already created the triggers; 0003 must be a no-op there."""
    dst = tmp_path / "v2_7_0.db"
    dst.write_bytes((FIXTURES / "v2_7_0.db").read_bytes())
    conn = emdb.open_db(dst)
    emmig.migrate(conn, target=2)
    assert _triggers(conn) == {"audit_no_update", "audit_no_delete"}
    emmig.migrate(conn)
    rows = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_log'"
    ).fetchone()[0]
    assert rows == 2
    conn.close()


def test_purge_token_still_allows_a_sanctioned_delete(tmp_path):
    """audit_no_delete has one sanctioned escape (a purge token in meta);
    0003 must keep it, not replace it with an unconditional block."""
    conn = emdb.open_db(tmp_path / "purge.db")
    emmig.migrate(conn)
    _seed_audit(conn)
    with emdb.write_txn(conn):
        conn.execute("INSERT INTO meta (key, value) VALUES ('audit_purge_token', 'op-approved')")
        conn.execute("DELETE FROM audit_log WHERE target_id='mem_1'")
    assert conn.execute("SELECT count(*) FROM audit_log").fetchone()[0] == 1
    conn.close()
