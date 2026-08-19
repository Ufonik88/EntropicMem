"""P2 controlled-sync tests (spec: docs/MULTI_PROFILE_PROVENANCE_SPEC.md §3).

Covers the P2 acceptance contract:
- outbox row created transactionally with each eligible write; secret/sensitive
  tiers never appear in the outbox
- publish twice → no duplicate sync_events (idempotent)
- pull twice → no duplicate shared_facts; own events skipped (echo prevention)
- newer (version, written_at) wins; stale events are no-ops (LWW)
- publish --backfill emits non-secret facts once; re-run emits nothing
- recall scope own|shared|all
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "entropicmem" / "scripts"))
from memory_engine import MemoryEngine  # noqa: E402


@pytest.fixture()
def shared_db(tmp_path):
    return MemoryEngine.shared_init(tmp_path / "shared.db")["shared_db"]


def _store(tmp_path, slug):
    return MemoryEngine(tmp_path / f"{slug}.db", profile_id=slug, publish_scope="shared")


def _shared_count(db, **where):
    conn = sqlite3.connect(db)
    sql = "SELECT COUNT(*) FROM sync_events"
    if where:
        sql += " WHERE " + " AND ".join(f"{k}=?" for k in where)
        row = conn.execute(sql, tuple(str(v) for v in where.values())).fetchone()[0]
    else:
        row = conn.execute(sql).fetchone()[0]
    conn.close()
    return row


def test_outbox_created_transactionally(tmp_path, shared_db):
    a = _store(tmp_path, "a")
    eid = a.remember("shared masterpiece", domain="Knowledge", importance=0.9)
    rows = a.db.execute("SELECT * FROM sync_outbox").fetchall()
    assert len(rows) == 1
    assert rows[0]["fact_id"] == eid
    assert rows[0]["op"] == "create"
    assert rows[0]["version"] == 1
    assert rows[0]["emitted"] == 0
    payload = json.loads(rows[0]["payload"])
    assert payload["content"] == "shared masterpiece"
    a.close()


def test_sensitive_and_secret_never_enter_outbox(tmp_path, shared_db):
    a = _store(tmp_path, "a")
    # 'secret' is blocked by write policy before storage (use VaultKnox)
    with pytest.raises(ValueError):
        a.remember("top secret", sensitivity="secret")
    # 'sensitive' is storable but must never be queued for cross-profile publish
    a.remember("finance internal", sensitivity="sensitive")
    count = a.db.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0]
    assert count == 0
    a.close()


def test_publish_idempotent_no_duplicate_events(tmp_path, shared_db):
    a = _store(tmp_path, "a")
    a.remember("once and once only", domain="Test")
    first = a.publish(shared_db)
    assert first["published"] == 1
    second = a.publish(shared_db)
    assert second["published"] == 0          # outbox drained
    assert _shared_count(shared_db) == 1     # still exactly one event
    a.close()


def test_pull_idempotent_and_echo_prevention(tmp_path, shared_db):
    a = _store(tmp_path, "a")
    b = _store(tmp_path, "b")
    a.remember("from a to b", domain="Knowledge")
    a.publish(shared_db)

    pull1 = b.pull(shared_db)
    assert pull1["applied"] == 1
    rows = b.db.execute(
        "SELECT fact_id, origin_store FROM shared_facts"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["origin_store"] == "a"

    # second pull: nothing new → no duplicate projection
    pull2 = b.pull(shared_db)
    assert b.db.execute("SELECT COUNT(*) FROM shared_facts").fetchone()[0] == 1

    # echo prevention: a pulls its own event → not applied to a's projection
    echo = a.pull(shared_db)
    assert echo["applied"] == 0
    assert a.db.execute("SELECT COUNT(*) FROM shared_facts").fetchone()[0] == 0
    a.close()
    b.close()


def test_lww_newer_wins_and_stale_is_noop(tmp_path, shared_db):
    a = _store(tmp_path, "a")
    b = _store(tmp_path, "b")

    a.remember("versioned fact", domain="Test")
    a.publish(shared_db)
    b.pull(shared_db)
    assert b.db.execute("SELECT version FROM shared_facts").fetchone()["version"] == 1

    # update → version 2; newer wins on pull (LWW by version)
    a.remember("versioned fact", domain="Test")
    a.publish(shared_db)
    b.pull(shared_db)
    row = b.db.execute("SELECT fact_id, version, content FROM shared_facts").fetchone()
    assert row["version"] == 2

    # a stale event with an EQUAL version + older written_at must be a no-op.
    # This is the only reachable LWW-stale path: the UNIQUE(origin,fact,version)
    # index forbids re-emitting a lower version, so a re-pull of an older-write
    # event is only possible at the current version.
    conn = sqlite3.connect(shared_db)
    conn.execute(
        "INSERT OR IGNORE INTO sync_events (origin_store, fact_id, op, version, written_at, fact_timestamp, payload) "
        "VALUES ('a', ?, 'update', 2, '2020-01-01T00:00:00', '', ?)",
        (
            row["fact_id"],
            json.dumps({"content": "stale", "domain": "Test", "sensitivity": "internal"}),
        ),
    )
    conn.commit()
    conn.close()
    b.pull(shared_db)                           # stale event → skipped (LWW)
    after = b.db.execute("SELECT version, content FROM shared_facts").fetchone()
    assert after["content"] == "versioned fact"
    assert after["version"] == 2
    a.close()
    b.close()


def test_backfill_emits_non_secret_once(tmp_path, shared_db):
    a = _store(tmp_path, "a")
    a.remember("public note", domain="Knowledge", sensitivity="public")
    a.remember("internal note", domain="Knowledge")
    a.remember("sensitive nibble", domain="Finance", sensitivity="sensitive")
    first = a.backfill(shared_db)
    assert _shared_count(shared_db) == 2        # only non-secret
    second = a.backfill(shared_db)
    assert second["emitted"] == 0               # idempotent re-run
    assert _shared_count(shared_db) == 2
    a.close()


def test_recall_scope_merges_shared(tmp_path, shared_db):
    a = _store(tmp_path, "a")
    b = _store(tmp_path, "b")
    a.remember("choose your fighter model", domain="Knowledge")
    a.publish(shared_db)
    b.pull(shared_db)

    own = b.recall("choose your fighter model", scope="own")
    assert len(own) == 0                        # b has nothing locally

    shared = b.recall("choose your fighter model", scope="shared")
    assert len(shared) == 1
    assert shared[0].source == "shared:a"

    both = b.recall("choose your fighter model", scope="all")
    assert len(both) == 1
    a.close()
    b.close()


def test_shared_init_idempotent(tmp_path):
    db = str(tmp_path / "shared.db")
    MemoryEngine.shared_init(db)
    MemoryEngine.shared_init(db)  # no error on re-run
    assert Path(db).exists()


def test_delete_propagates_as_tombstone(tmp_path, shared_db):
    """Regression: a delete must reach the shared log even when the fact was
    previously updated — the tombstone version must not collide with the
    existing update event's version (UNIQUE origin+fact+version)."""
    a = _store(tmp_path, "a")
    b = _store(tmp_path, "b")

    a.remember("doomed fact", domain="Test")
    a.remember("doomed fact", domain="Test")   # v1 → v2
    a.publish(shared_db)
    b.pull(shared_db)
    assert b.db.execute("SELECT version FROM shared_facts").fetchone()["version"] == 2

    a.forget(b.db.execute("SELECT fact_id FROM shared_facts").fetchone()["fact_id"], confirm=True)
    res = a.publish(shared_db)
    assert res["published"] == 1                # tombstone got a NEW version slot

    b.pull(shared_db)
    row = b.db.execute("SELECT deleted, version FROM shared_facts").fetchone()
    assert row["deleted"] == 1                  # tombstone applied
    assert row["version"] == 3                  # delete carries version+1
    assert b.recall("doomed fact", scope="shared") == []  # hidden from recall
    a.close()
    b.close()