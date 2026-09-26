"""EM-206: hash-chained audit log."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.store.audit import (  # noqa: E402
    GENESIS_HASH,
    MAX_DETAIL_VALUE_LEN,
    append,
    audit_hash,
    verify,
)

DDL = """
CREATE TABLE audit_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, action TEXT NOT NULL,
  actor TEXT NOT NULL,
  session_id TEXT NOT NULL DEFAULT '', target_id TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '{}',
  ok INTEGER NOT NULL DEFAULT 1, prev_hash TEXT NOT NULL, hash TEXT NOT NULL
)
"""


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(DDL)
    yield c
    c.close()


def test_first_row_chains_to_genesis(conn):
    append(conn, "memory.write", "tester", "mem_1", {"kind": "fact"})
    row = conn.execute("SELECT * FROM audit_log").fetchone()
    assert row["prev_hash"] == GENESIS_HASH
    assert row["hash"] == audit_hash(GENESIS_HASH, row["ts"], "memory.write", "tester", "mem_1", row["detail"])


def test_chain_links_successive_rows(conn):
    append(conn, "a", "tester", "m1")
    append(conn, "b", "tester", "m2")
    append(conn, "c", "tester", "m3")
    rows = conn.execute("SELECT * FROM audit_log ORDER BY seq").fetchall()
    assert rows[1]["prev_hash"] == rows[0]["hash"]
    assert rows[2]["prev_hash"] == rows[1]["hash"]
    assert verify(conn).ok


def test_empty_chain_verifies(conn):
    assert verify(conn).ok
    assert verify(conn).checked == 0


# --- the acceptance criterion: a manual tamper is detected -------------------


def test_tamper_detected_when_triggers_dropped(conn):
    """AC: manual UPDATE with the append-only triggers dropped is caught."""
    append(conn, "memory.write", "tester", "mem_1", {"n": 1})
    append(conn, "memory.write", "tester", "mem_2", {"n": 2})
    append(conn, "memory.forget", "tester", "mem_2", {"n": 3})
    assert verify(conn).ok

    # An attacker with DB access drops the append-only triggers and edits history.
    conn.executescript("DROP TRIGGER IF EXISTS audit_no_update; DROP TRIGGER IF EXISTS audit_no_delete;")
    conn.execute("UPDATE audit_log SET actor='mallory' WHERE seq=1")
    conn.commit()

    result = verify(conn)
    assert not result.ok
    assert result.first_bad_seq == 1
    assert "hash" in result.reason


def test_tamper_in_middle_reports_that_row(conn):
    """Rewriting a middle row must be caught at that row, not at the end."""
    for i in range(5):
        append(conn, "op", "tester", f"m{i}")
    conn.executescript("DROP TRIGGER IF EXISTS audit_no_update; DROP TRIGGER IF EXISTS audit_no_delete;")
    conn.execute("UPDATE audit_log SET target_id='swapped' WHERE seq=3")
    conn.commit()

    result = verify(conn)
    assert not result.ok
    assert result.first_bad_seq == 3


def test_prev_hash_alone_is_checked(conn):
    """Corrupting only ``prev_hash`` (leaving ``hash`` intact) must be caught.

    ``prev_hash`` is part of the hashed payload, so overwriting it also
    invalidates the row's own digest. The link comparison is still what
    reports it first and names the right row, which is the useful property:
    a rolled-back or spliced chain is reported at the row where it breaks.
    """
    for i in range(3):
        append(conn, "op", "tester", f"m{i}")
    conn.executescript("DROP TRIGGER IF EXISTS audit_no_update; DROP TRIGGER IF EXISTS audit_no_delete;")
    conn.execute("UPDATE audit_log SET prev_hash=? WHERE seq=3", ("f" * 64,))
    conn.commit()

    result = verify(conn)
    assert not result.ok
    assert result.first_bad_seq == 3
    assert "prev_hash" in result.reason


def test_deleted_row_breaks_the_chain(conn):
    """Deleting a row cannot be hidden: the successor's prev_hash dangles."""
    for i in range(3):
        append(conn, "op", "tester", f"m{i}")
    conn.executescript("DROP TRIGGER IF EXISTS audit_no_update; DROP TRIGGER IF EXISTS audit_no_delete;")
    conn.execute("DELETE FROM audit_log WHERE seq=2")
    conn.commit()

    result = verify(conn)
    assert not result.ok
    assert result.first_bad_seq == 3


def test_rechained_deletion_is_a_known_limitation(conn):
    """Pin the real guarantee: a *re-chained* deletion is NOT detected.

    An attacker who deletes a middle row and recomputes the next row's
    ``prev_hash``/``hash`` from the row before it produces a chain that is
    internally consistent: every row's digest matches its own fields, and every
    ``prev_hash`` matches its predecessor. No hash chain that only checks
    adjacency can see this, so ``verify`` reports OK.

    The card's acceptance criterion is narrower (a manual UPDATE is detected),
    and that holds: see the tests above. Seq contiguity is not an available
    defence either, because migration 0002 deliberately preserves the original
    v2 ids in ``seq``, so a migrated chain legitimately has gaps (see
    ``test_migrated_chain_shape_is_verifiable``).

    Closing this would need an anchor outside the database, e.g. publishing the
    head digest or signing it. Deliberately not built here.
    """
    for i in range(3):
        append(conn, "op", "tester", f"m{i}")
    conn.executescript("DROP TRIGGER IF EXISTS audit_no_update; DROP TRIGGER IF EXISTS audit_no_delete;")

    first = conn.execute("SELECT * FROM audit_log WHERE seq=1").fetchone()
    third = conn.execute("SELECT * FROM audit_log WHERE seq=3").fetchone()
    conn.execute("DELETE FROM audit_log WHERE seq=2")
    forged = audit_hash(first["hash"], third["ts"], third["action"], third["actor"],
                        third["target_id"], third["detail"])
    conn.execute("UPDATE audit_log SET prev_hash=?, hash=? WHERE seq=3", (first["hash"], forged))
    conn.commit()

    # Each surviving row is self-consistent, which is exactly why this passes.
    assert verify(conn).ok
    assert verify(conn).checked == 2


def test_appending_after_tamper_is_still_caught(conn):
    """Re-chaining the tail after an edit does not launder the edit."""
    for i in range(3):
        append(conn, "op", "tester", f"m{i}")
    conn.executescript("DROP TRIGGER IF EXISTS audit_no_update; DROP TRIGGER IF EXISTS audit_no_delete;")
    conn.execute("UPDATE audit_log SET actor='mallory' WHERE seq=1")
    append(conn, "op", "tester", "m3")  # the chain happily continues from the forged row
    assert not verify(conn).ok


# --- detail handling ---------------------------------------------------------


def test_detail_is_canonical_so_key_order_does_not_change_the_hash(conn):
    """Key order must not change the digest.

    ``ts`` is pinned: ``append`` stamps rows from SQLite's ``'now'``, which has
    millisecond resolution, so two appends can legitimately land either side of
    a millisecond boundary and differ in ``ts`` (and therefore in the digest)
    even though the detail is identical. That would make this test flaky for a
    reason unrelated to canonicalisation.
    """
    ts = "2026-01-01T00:00:00.000Z"
    append(conn, "op", "tester", "m1", {"b": 1, "a": 2}, ts=ts)
    first = conn.execute("SELECT hash FROM audit_log").fetchone()["hash"]
    conn.execute("DELETE FROM audit_log")
    append(conn, "op", "tester", "m1", {"a": 2, "b": 1}, ts=ts)
    assert conn.execute("SELECT hash FROM audit_log").fetchone()["hash"] == first


def test_two_appends_in_the_same_millisecond_are_still_chained(conn):
    """Rows appended back to back must link even when ``ts`` is identical.

    ``ts`` is not part of the uniqueness of a row; ``seq`` and the hash chain
    are. A slow machine or a fast loop can produce two rows with the same
    millisecond stamp, and the chain must still hold.
    """
    ts = "2026-01-01T00:00:00.000Z"
    append(conn, "a", "tester", "m1", ts=ts)
    append(conn, "b", "tester", "m2", ts=ts)
    rows = conn.execute("SELECT * FROM audit_log ORDER BY seq").fetchall()
    assert rows[0]["ts"] == rows[1]["ts"]
    assert rows[1]["prev_hash"] == rows[0]["hash"]
    assert verify(conn).ok


def test_detail_never_carries_content(conn):
    with pytest.raises(ValueError, match="never content"):
        append(conn, "op", "tester", "m1", {"content": "x" * (MAX_DETAIL_VALUE_LEN + 1)})


def test_detail_accepts_ids_hashes_and_codes(conn):
    append(
        conn,
        "op",
        "tester",
        "m1",
        {"id": "mem_" + "0" * 20, "hash": "a" * 64, "reason": "pii_high_confidence"},
    )
    assert verify(conn).ok


def test_empty_and_none_detail_hash_as_empty_object(conn):
    append(conn, "op", "tester", "m1")
    append(conn, "op", "tester", "m2", None)
    rows = conn.execute("SELECT detail FROM audit_log").fetchall()
    assert [r["detail"] for r in rows] == ["{}", "{}"]
    assert verify(conn).ok


# --- the formula is frozen ---------------------------------------------------


def test_hash_formula_matches_an_independent_implementation(conn):
    """Pin the formula itself, not just self-consistency.

    A verifier that calls the same helper it was written with cannot detect a
    wrong formula, so recompute it here from the spec text.
    """
    append(conn, "op", "tester", "m1", {"k": "v"})
    row = conn.execute("SELECT * FROM audit_log").fetchone()
    expected = hashlib.sha256(
        "".join(
            (
                GENESIS_HASH,
                row["ts"],
                "op",
                "tester",
                "m1",
                json.dumps({"k": "v"}, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
            )
        ).encode("utf-8")
    ).hexdigest()
    assert row["hash"] == expected


def test_migrated_chain_shape_is_verifiable(conn):
    """The chain EM-204 rebuilt from v2 must verify with this module.

    Migration 0002 wrote the chain in ``seq`` order starting at the original v2
    ids, so a store that skips sequence numbers must still verify.
    """
    rows = [
        (1, "2026-01-01T00:00:00.000Z", "a", "tester", "m1", '{"n":1}'),
        (7, "2026-01-02T00:00:00.000Z", "b", "tester", "m2", '{"n":2}'),
        (19, "2026-01-03T00:00:00.000Z", "c", "tester", "m3", '{"n":3}'),
    ]
    prev = GENESIS_HASH
    for seq, ts, action, actor, target, detail in rows:
        digest = audit_hash(prev, ts, action, actor, target, detail)
        conn.execute(
            "INSERT INTO audit_log (seq, ts, action, actor, target_id, detail, ok, prev_hash, hash)"
            " VALUES (?,?,?,?,?,?,1,?,?)",
            (seq, ts, action, actor, target, detail, prev, digest),
        )
        prev = digest
    assert verify(conn).ok
    assert verify(conn).checked == 3


# --- CLI ---------------------------------------------------------------------


def _cli(tmp_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the CLI against ``tmp_dir/memory.db`` in a throwaway profile.

    ``HERMES_HOME`` is what the product reads (not ``HOME``): setting only
    ``HOME`` still resolves the real ``~/.hermes``, and the live-store guard in
    EM-203 then refuses the open, which would look like a bug in this command.
    """
    db = tmp_dir / "memory.db"
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(tmp_dir),
        "HERMES_HOME": str(tmp_dir / "hermes"),
        "ENTROPICMEM_MEMORY_DB": str(db),
        "ENTROPICMEM_VAULT_PATH": str(tmp_dir / "vault"),
        "ENTROPICMEM_INDEX_DB": str(tmp_dir / "index.db"),
    }
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "entropicmem.py"), "audit", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def test_cli_audit_verify_reports_ok(tmp_path):
    from em.store.db import Store
    from em.store.migrations import migrate

    db = tmp_path / "memory.db"
    store = Store(db)
    try:
        with store.writer() as conn:
            migrate(conn)
            append(conn, "memory.write", "tester", "mem_1", {"n": 1})
    finally:
        store.close()

    out = _cli(tmp_path, "verify")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["ok"] is True


def test_cli_audit_verify_fails_on_tamper(tmp_path):
    from em.store.db import Store
    from em.store.migrations import migrate

    db = tmp_path / "memory.db"
    store = Store(db)
    try:
        with store.writer() as conn:
            migrate(conn)
            append(conn, "memory.write", "tester", "mem_1", {"n": 1})
            conn.executescript(
                "DROP TRIGGER IF EXISTS audit_no_update; DROP TRIGGER IF EXISTS audit_no_delete;"
            )
            conn.execute("UPDATE audit_log SET actor='mallory'")
    finally:
        store.close()

    out = _cli(tmp_path, "verify")
    assert out.returncode == 1
    assert json.loads(out.stdout)["ok"] is False
def test_cli_audit_verify_is_read_only_on_a_v3_db(tmp_path):
    """EM-208 follow-up: verify must not mutate the DB it inspects.

    Store(db) opened read-write chmods the parent dir to 0700, the DB to 0600
    and sets journal_mode=WAL. A verify command that rewrites the file it is
    checking is not a verify command. Assert permissions, journal mode and the
    file bytes are all untouched.
    """
    import sqlite3

    from em.store.db import Store
    from em.store.migrations import migrate

    db = tmp_path / "memory.db"
    store = Store(db)
    try:
        with store.writer() as conn:
            migrate(conn)
            append(conn, "memory.write", "tester", "mem_1", {"n": 1})
        store.close()
        # Undo Store's side effects so the fixture starts as the test wants:
        # 0755 dir, 0644 file, DELETE journal, bytes captured after.
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        tmp_path.chmod(0o755)
        db.chmod(0o644)
        before = db.read_bytes()
    finally:
        store.close()

    out = _cli(tmp_path, "verify")
    assert out.returncode == 0, out.stderr
    assert oct(tmp_path.stat().st_mode & 0o777) == "0o755"
    assert oct(db.stat().st_mode & 0o777) == "0o644"
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
    conn.close()
    assert db.read_bytes() == before, "verify rewrote the DB file"


def test_cli_audit_verify_is_read_only_on_a_v2_db(tmp_path):
    """EM-208 follow-up: the v2 refusal path must also be read-only.

    The old code opened read-write through Store, so even the v2 DB it then
    refused was chmodded and flipped to WAL on the way out.
    """
    import sqlite3

    db = tmp_path / "memory.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE audit_log ("
        "  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,"
        "  action TEXT NOT NULL, actor TEXT NOT NULL,"
        "  session_id TEXT NOT NULL DEFAULT '', target_id TEXT NOT NULL DEFAULT '',"
        "  detail TEXT NOT NULL DEFAULT '{}', ok INTEGER NOT NULL DEFAULT 1);"
    )
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    tmp_path.chmod(0o755)
    db.chmod(0o644)
    before = db.read_bytes()

    out = _cli(tmp_path, "verify")
    assert out.returncode == 1  # refused: v2 has no hash chain
    assert "not hash-chained" in out.stderr
    assert oct(tmp_path.stat().st_mode & 0o777) == "0o755"
    assert oct(db.stat().st_mode & 0o777) == "0o644"
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
    conn.close()
    assert db.read_bytes() == before, "verify mutated a DB it refuses to check"
