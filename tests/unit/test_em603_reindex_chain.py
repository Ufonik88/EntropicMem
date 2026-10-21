"""Regression test for EM-603: enqueue_reindex chain fix.

This test verifies that enqueue_reindex creates a follow-up job after a done row,
mirroring the projection's proven pattern from EM-601 slice 2.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[0]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for entry in (str(REPO), str(SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from em.store.db import Store
from em.vault.schedule import REINDEX_JOB_TYPE, enqueue_reindex


def _memory_store(tmp_path: Path):
    """Create a test store with migrations applied (matches existing test pattern)."""
    from em.store.migrations import migrate

    saved = Store(str(tmp_path / "memory.db"))
    with saved.writer() as conn:
        migrate(conn)
    return saved


def test_enqueue_reindex_creates_followup_after_done(tmp_path):
    """Regression test for EM-603: enqueue_reindex must create a follow-up job after a done row.

    The defect: enqueue_reindex uses a stable dedupe key, so once the first
    reindex_vault row reaches 'done', every later request returns that dead
    row's id and no new job is ever created.

    The fix: mirror the projection's pattern - walk the chain and create a
    follow-up key derived from the terminal row's id.
    """
    # Setup - create vault root and index db path
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    index_db = tmp_path / "index.db"

    # Create the index database file to pass validation
    index_db.touch()

    saved = _memory_store(tmp_path)

    try:
        # Step 1: Enqueue a reindex job and claim it in the same transaction
        with saved.transaction() as conn:
            first_id = enqueue_reindex(conn, root=vault_root, index_db=index_db)
            assert first_id is not None, "First enqueue should return a job ID"

            # Verify we have exactly one queued job
            rows = conn.execute(
                f"SELECT id, status FROM jobs WHERE type='{REINDEX_JOB_TYPE}'"
            ).fetchall()
            assert len(rows) == 1, f"Expected 1 job, got {len(rows)}"
            assert rows[0]["id"] == first_id
            assert rows[0]["status"] == "queued"

            # Simulate the job being claimed (worker picks it up)
            from em.store.jobs import JobQueue
            queue = JobQueue(conn)
            claimed = queue.claim("test-worker")
            assert claimed is not None and claimed.id == first_id, "Should claim the queued job"
            assert claimed.status == "running"

            # Simulate the job completing
            completed = queue.complete(first_id, "test-worker")
            assert completed, "Should complete the running job"

        # Step 2: Enqueue another reindex job - this should create a NEW job,
        # NOT return the done job ID
        with saved.transaction() as conn:
            second_id = enqueue_reindex(conn, root=vault_root, index_db=index_db)
            assert second_id is not None, "Second enqueue should return a job ID"
            assert second_id != first_id, "Should create a NEW job, not return the done one"

            # Verify we now have TWO jobs (the original done one and the new queued one)
            rows = conn.execute(
                f"SELECT id, status FROM jobs WHERE type='{REINDEX_JOB_TYPE}' ORDER BY created_at"
            ).fetchall()
            assert len(rows) == 2, f"Expected 2 jobs, got {len(rows)}"

            # First should be done, second should be queued
            assert rows[0]["status"] == "done", f"First job should be done, got {rows[0]['status']}"
            assert rows[1]["status"] == "queued", f"Second job should be queued, got {rows[1]['status']}"
            assert rows[1]["id"] == second_id, "Second job ID should match what was returned"

        print("✅ Test passed: Created follow-up reindex job")
        print(f"   First job: {first_id} (status: done)")
        print(f"   Second job: {second_id} (status: queued)")

    finally:
        saved.close()


def test_enqueue_reindex_still_dedups_before_run(tmp_path):
    """Regression test: existing dedupe behavior must be preserved.

    Two enqueues before any run must still collapse to one row.
    """
    # Create vault root and index db path
    vault_root = tmp_path / "vault"
    vault_root.mkdir(exist_ok=True)
    index_db = tmp_path / "index.db"
    index_db.touch()

    saved = _memory_store(tmp_path)

    try:
        with saved.transaction() as conn:
            # First enqueue
            first_id = enqueue_reindex(conn, root=vault_root, index_db=index_db)
            assert first_id is not None

            # Second enqueue before any run - should return the same job ID
            second_id = enqueue_reindex(conn, root=vault_root, index_db=index_db)
            assert second_id is not None
            assert second_id == first_id, "Two enqueues before any run should return the same job"

            # Verify we have exactly one job
            rows = conn.execute(
                f"SELECT id, status FROM jobs WHERE type='{REINDEX_JOB_TYPE}'"
            ).fetchall()
            assert len(rows) == 1, f"Expected 1 job, got {len(rows)}"
            assert rows[0]["id"] == first_id
            assert rows[0]["status"] == "queued"

        print("✅ Test passed: Existing dedupe behavior preserved")
        print(f"   Job ID: {first_id}")

    finally:
        saved.close()


def test_reindex_chain_walks_past_a_running_followup(tmp_path):
    """The chain must keep walking while follow-up rows are in flight.

    QA (EM-603 review) showed the first cut of this fix returned immediately
    after computing the follow-up key, so a follow-up row that was itself
    running/done absorbed the request - the same defect one level deeper.
    With r1 running and its follow-up r2 also running, a third request must
    produce a NEW row, not r2.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir(exist_ok=True)
    index_db = tmp_path / "index.db"
    index_db.touch()

    saved = _memory_store(tmp_path)

    try:
        with saved.transaction() as conn:
            from em.store.jobs import JobQueue

            queue = JobQueue(conn)

            # r1: queued -> running
            r1 = enqueue_reindex(conn, root=vault_root, index_db=index_db)
            assert r1 is not None
            queue.claim("test-worker")

            # r2: the follow-up, also taken in flight
            r2 = enqueue_reindex(conn, root=vault_root, index_db=index_db)
            assert r2 is not None
            assert r2 != r1, "second request must produce a new row"
            queue.claim("test-worker")

            # r3: both r1 and r2 are running - the chain must walk past BOTH
            r3 = enqueue_reindex(conn, root=vault_root, index_db=index_db)
            assert r3 is not None
            assert r3 != r2, (
                "third request was absorbed by the in-flight follow-up r2: the "
                "chain stopped walking one level deep (EM-603 defect, again)"
            )
            assert len({r1, r2, r3}) == 3

            rows = conn.execute(
                f"SELECT id, status FROM jobs WHERE type='{REINDEX_JOB_TYPE}'"
            ).fetchall()
            assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
            assert [r["status"] for r in rows].count("running") == 2
            assert [r["status"] for r in rows].count("queued") == 1

    finally:
        saved.close()


def test_reindex_chain_respects_max_chain(tmp_path):
    """A burst that exhausts the chain must raise, not silently drop the request.

    Fills every slot so that the next walk cannot find a free key, and asserts
    the terminal RuntimeError is actually reachable (it was dead code in the
    first cut).
    """
    from em.vault.schedule import _MAX_CHAIN

    vault_root = tmp_path / "vault"
    vault_root.mkdir(exist_ok=True)
    index_db = tmp_path / "index.db"
    index_db.touch()

    saved = _memory_store(tmp_path)

    try:
        with saved.transaction() as conn:
            from em.store.jobs import JobQueue

            queue = JobQueue(conn)

            ids = []
            for _ in range(_MAX_CHAIN):
                jid = enqueue_reindex(conn, root=vault_root, index_db=index_db)
                assert jid is not None, "chain should still hand out rows under the bound"
                queue.claim("test-worker")  # take it in flight so the key stays occupied
                ids.append(jid)

            assert len(set(ids)) == _MAX_CHAIN, "each walk must allocate a distinct row"

            with pytest.raises(RuntimeError):
                enqueue_reindex(conn, root=vault_root, index_db=index_db)

    finally:
        saved.close()


def test_enqueue_reindex_needs_both_paths(tmp_path):
    """Regression test: enqueue_reindex should return None when paths are missing."""
    saved = _memory_store(tmp_path)

    try:
        with saved.transaction() as conn:
            # Test missing root
            result1 = enqueue_reindex(conn, root="", index_db="x")
            assert result1 is None, "Should return None when root is empty"

            # Test missing index_db
            result2 = enqueue_reindex(conn, root="x", index_db=None)
            assert result2 is None, "Should return None when index_db is None"

            # Verify no jobs were created
            rows = conn.execute(
                f"SELECT COUNT(*) FROM jobs WHERE type='{REINDEX_JOB_TYPE}'"
            ).fetchone()
            assert rows[0] == 0, "Should not create any jobs when paths are invalid"

        print("✅ Test passed: Path validation works correctly")

    finally:
        saved.close()


if __name__ == "__main__":
    import tempfile

    # Run tests
    print("Running EM-603 regression tests...\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        test_enqueue_reindex_creates_followup_after_done(tmp_path)
        print()
        test_enqueue_reindex_still_dedups_before_run(tmp_path)
        print()
        test_reindex_chain_respects_max_chain(tmp_path)
        print()
        test_enqueue_reindex_needs_both_paths(tmp_path)
        print()

    print("\n✅ All tests passed!")
