"""EM-503 wiring — neighbour retrieval, the reconcile pass, and the job chain.

The core decision/apply engine landed with EM-503; this is the half that makes
it run: `find_neighbours` through the pipeline's own seam, `reconcile_pending`
over the quarantined queue, the `reconcile` job handler, and the extraction
handler's enqueue that connects extract → reconcile → commit.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


from em.facade.engine import V3Engine  # noqa: E402
from em.formation.extract_jobs import (  # noqa: E402
    make_extract_window_handler,
    make_reconcile_handler,
)
from em.formation.reconcile import find_neighbours, reconcile_pending  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

SCOPE = Scope(profile="default", user="")
OTHER = Scope(profile="other", user="")
COMMIT = {"min_confidence": 0.75, "kinds": ["preference", "profile", "constraint", "procedure", "fact"], "ttl_days": 30}


class FakeCtx:
    def __init__(self, store: Store) -> None:
        self.store = store

    def heartbeat(self) -> bool:
        return True


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    V3Engine(db).close()
    return db


def _add(conn, content, *, scope=SCOPE, status="active", kind="fact", confidence=0.8,
         source="agent", pending_reason=""):
    result = MemoryStore(conn).add(
        MemoryDraft(
            content=content, kind=kind, confidence=confidence, status=status,
            source=source, pending_reason=pending_reason,
        ),
        scope=scope,
        actor="test",
    )
    assert result.ok, result
    return result.id


# --- neighbour retrieval -----------------------------------------------------


def test_find_neighbours_returns_in_scope_active_memories(tmp_path):
    db = _db(tmp_path)
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            wanted = _add(conn, "The staging port is 9090.")
            _add(conn, "The staging port is 7070.", scope=OTHER, status="active")
            _add(conn, "The staging port is 6060.", scope=SCOPE, status="pending",
                 source="auto_extracted", pending_reason="extracted")
            neighbours = find_neighbours(conn, SCOPE, "The staging port is 9090.")
    finally:
        store.close()
    ids = [n["id"] for n in neighbours]
    assert wanted in ids
    assert all(ids), "every neighbour must carry an id"
    assert not any(n["content"] == "The staging port is 6060." for n in neighbours)
    assert not any(n["content"] == "The staging port is 7070." for n in neighbours)


# --- the pass ----------------------------------------------------------------


def test_reconcile_pending_promotes_a_confident_preference(tmp_path):
    db = _db(tmp_path)
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            cid = _add(
                conn, "I prefer dark roast coffee in the morning.", kind="preference",
                status="pending", source="auto_extracted", pending_reason="extracted",
            )
            report = reconcile_pending(conn, SCOPE, commit=COMMIT)
            row = MemoryStore(conn).get(cid, scope=SCOPE)
    finally:
        store.close()
    assert report and report[0]["decision"] == "ADD" and report[0]["status"] == "active"
    assert row["status"] == "active"


def test_reconcile_pending_supersedes_a_changed_fact(tmp_path):
    db = _db(tmp_path)
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            old = _add(conn, "The staging port is 9090.")
            new = _add(
                conn, "The staging port is 7070.", status="pending",
                source="auto_extracted", pending_reason="extracted",
            )
            reconcile_pending(conn, SCOPE, commit=COMMIT)
            memories = MemoryStore(conn)
            old_row = memories.get(old, scope=SCOPE)
            cand = memories.get(new, scope=SCOPE)
    finally:
        store.close()
    assert old_row["status"] == "superseded" and old_row["superseded_by"]
    assert cand["status"] == "deleted"


def test_reconcile_pending_leaves_a_low_confidence_candidate_pending(tmp_path):
    db = _db(tmp_path)
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            cid = _add(
                conn, "I prefer dark roast coffee in the morning.", kind="preference",
                status="pending", source="auto_extracted", pending_reason="extracted",
                confidence=0.4,
            )
            report = reconcile_pending(conn, SCOPE, commit=COMMIT)
            row = MemoryStore(conn).get(cid, scope=SCOPE)
    finally:
        store.close()
    assert report and report[0]["status"] == "pending"
    assert row["status"] == "pending"


# --- the job chain -----------------------------------------------------------


def test_the_reconcile_job_handler_drains_the_scope(tmp_path):
    db = _db(tmp_path)
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            cid = _add(
                conn, "I prefer dark roast coffee in the morning.", kind="preference",
                status="pending", source="auto_extracted", pending_reason="extracted",
            )
        handler = make_reconcile_handler()
        handler(
            SimpleNamespace(payload={"scope": {"profile": "default", "user": ""}, "commit": COMMIT}),
            FakeCtx(store),
        )
        with store.transaction() as conn:
            row = MemoryStore(conn).get(cid, scope=SCOPE)
    finally:
        store.close()
    assert row["status"] == "active"


def test_the_extraction_handler_enqueues_a_reconcile_pass(tmp_path):
    db = _db(tmp_path)
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO transcript_chunks"
                " (digest, session_id, seq, role, author_id, text, ts, captured_at, source)"
                " VALUES ('d1','sess', 1, 'user', 'u-alice',"
                " 'I prefer dark roast coffee in the morning.', NULL, '2026-01-01T00:00:00Z', 'sync_turn')"
            )
        payload = {
            "session_id": "sess",
            "seq_start": 1,
            "seq_end": 1,
            "scope": {"profile": "default", "user": ""},
            "commit": COMMIT,
        }
        make_extract_window_handler()(SimpleNamespace(payload=payload), FakeCtx(store))
        with store.transaction() as conn:
            jobs = [dict(r) for r in conn.execute("SELECT type, payload, dedupe_key FROM jobs")]
            pending = [dict(r) for r in conn.execute(
                "SELECT status, pending_reason, source, pending_expires_at FROM memories"
            )]
    finally:
        store.close()

    reconcile = [j for j in jobs if j["type"] == "reconcile"]
    assert len(reconcile) == 1, jobs
    assert "reconcile:" in reconcile[0]["dedupe_key"]
    extracted = [r for r in pending if r["source"] == "auto_extracted"]
    assert extracted and all(r["status"] == "pending" for r in extracted)
    assert all(r["pending_expires_at"] for r in extracted), "§3.7's pending TTL is stamped"
