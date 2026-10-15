"""EM-405, the retraction half: /undo soft-deletes the undone turn's memories.

The card's acceptance scenario is *"/undo removes a memory stated in the undone
turn"* and its contract is explicit: the rewound ``on_session_switch`` enqueues a
``retract_turns`` **job** — soft-delete memories whose ``source_session = sid AND
source_turn >= turn``, audit the change as ``retracted_by_undo``, and leave
``review``'s restore able to undo it.

This file pins that contract from the store up:

* ``MemoryStore.retract_session`` — live, turn-stamped rows only; nothing else
  in the session's history moves (an earlier turn, another session, an
  unstamped row and the pending quarantine all survive).
* the audit + version trail — ``retracted_by_undo`` is the recorded reason on
  both, so the act is reviewable and the reversal identifiable.
* the one reversal of a terminal status — a *retraction* restores through
  ``review``; a *forget* stays terminal. §3.4's transition table is untouched
  (``deleted`` stays terminal there); the edge is reason-gated on the row's own
  deletion record, not added to the machine.
* ``retract_turns`` as a job — handler idempotence, malformed payloads going
  dead, and the CLI registration the operator runner needs.
* the provider end to end — ``/undo`` forwards ``rewound=True``, exactly one
  job lands with the current turn, the memory is gone, one restore brings it
  back, and a second undo walks one turn further back.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

from em.facade.engine import V3Engine  # noqa: E402
from em.jobs.worker import HandlerRegistry, JobWorker  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.jobs import JobQueue  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.retract import make_retract_handler  # noqa: E402
from em.store.types import InvalidTransition, MemoryDraft, Scope  # noqa: E402
from memory_engine import MemoryEngine  # noqa: E402

# --- fixtures ---------------------------------------------------------------


def _rows(db: Path, sql: str, params: tuple = ()) -> list:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def _status(db: Path, memory_id: str) -> str:
    return _rows(db, "SELECT status FROM memories WHERE id=?", (memory_id,))[0]["status"]


def _v3_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    V3Engine(db).close()
    return db


def _v2_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    MemoryEngine(db, profile_id="default").close()
    return db


def _provider(tmp_path: Path, db: Path, *, session: str = "sess-undo", **config) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(config={
        "core_memory_enabled": False,
        "touch_on_inject": False,
        **config,
    })
    provider.initialize(session, hermes_home=str(tmp_path))
    # `initialize` leaves these unset when the skill tree is not in the temp
    # home, so this points every hook at the real facade and the temp store.
    provider._scripts_dir = SCRIPTS
    provider._memory_db = db
    provider._profile_id = "default"
    return provider


def _seed(
    db: Path,
    *,
    content: str,
    session: str,
    turn: int | None = None,
    source: str = "agent",
    status: str = "active",
) -> str:
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            result = MemoryStore(conn).add(
                MemoryDraft(
                    content=content,
                    source=source,
                    source_session=session,
                    source_turn=turn,
                    status=status,
                ),
                scope=Scope(profile="default"),
                actor="seed",
            )
            assert result.ok, result
            return result.id
    finally:
        store.close()


def _remember(provider: EntropicMemMemoryProvider, content: str) -> str:
    payload = json.loads(provider.handle_tool_call("entropicmem_remember", {"content": content}))
    assert payload.get("ok"), payload
    return payload["id"]


def _enqueue_and_run(db: Path, payload: dict, *, job_type: str = "retract_turns") -> list:
    store = Store(str(db))
    registry = HandlerRegistry()
    registry.register(job_type, make_retract_handler())
    try:
        with store.transaction() as conn:
            JobQueue(conn).enqueue(job_type, payload)
        return JobWorker(store, registry).run_until_idle()
    finally:
        store.close()


def _run_retract_jobs(db: Path) -> list:
    """Run only the queued retractions — embed/link jobs the tools queued are
    not this file's business and are left where they are."""
    store = Store(str(db))
    registry = HandlerRegistry()
    registry.register("retract_turns", make_retract_handler())
    try:
        return JobWorker(store, registry).run_until_idle()
    finally:
        store.close()


# --- the store operation ----------------------------------------------------


def test_retract_session_soft_deletes_only_live_stamped_rows(tmp_path):
    db = _v3_db(tmp_path)
    s1_t2 = _seed(db, content="the release train leaves on Thursday", session="s1", turn=2)
    s1_t1 = _seed(db, content="the standup is at 09:30", session="s1", turn=1)
    s2_t2 = _seed(db, content="the invoice run is nightly", session="s2", turn=2)
    s1_none = _seed(db, content="a fact with no turn stamp at all", session="s1", turn=None)
    s1_pending_t2 = _seed(
        db,
        content="an extracted candidate from the same turn",
        session="s1",
        turn=2,
        source="auto_extracted",
        status="pending",
    )

    store = Store(str(db))
    try:
        with store.transaction() as conn:
            gone = MemoryStore(conn).retract_session("s1", 2, actor="undo")
    finally:
        store.close()

    assert gone == 1, "only the live, stamped row of that exact turn is retracted"
    status = {r["id"]: r["status"] for r in _rows(db, "SELECT id, status FROM memories")}
    assert status[s1_t2] == "deleted"
    assert status[s1_t1] == "active", "an earlier turn of the same session survives"
    assert status[s2_t2] == "active", "another session's same turn survives"
    assert status[s1_none] == "active", "an unstamped row is not attributable to a turn"
    assert status[s1_pending_t2] == "pending", "the quarantine has its own TTL/discard path"


def test_retraction_is_audited_and_versioned(tmp_path):
    db = _v3_db(tmp_path)
    mid = _seed(db, content="the staging key lives in the vault", session="s1", turn=4)

    store = Store(str(db))
    try:
        with store.transaction() as conn:
            MemoryStore(conn).retract_session("s1", 4, actor="undo")
    finally:
        store.close()

    latest = _rows(
        db,
        "SELECT status, change_reason FROM memory_versions WHERE memory_id=?"
        " ORDER BY version DESC LIMIT 1",
        (mid,),
    )[0]
    assert latest["status"] == "deleted" and latest["change_reason"] == "retracted_by_undo"

    audit = _rows(
        db, "SELECT action, detail FROM audit_log WHERE target_id=? ORDER BY seq DESC", (mid,)
    )
    assert audit and audit[0]["action"] == "set_status"
    detail = json.loads(audit[0]["detail"])
    assert detail["to"] == "deleted" and detail["reason"] == "retracted_by_undo"


def test_retracting_from_a_turn_catches_every_later_turn_too(tmp_path):
    """``from_turn`` is the undone turn, not the only one: a rewind further
    back takes everything stated from there on."""
    db = _v3_db(tmp_path)
    t1 = _seed(db, content="the standup is at 09:30", session="s1", turn=1)
    t2 = _seed(db, content="the release train leaves on Thursday", session="s1", turn=2)
    t3 = _seed(db, content="the retro is on Friday", session="s1", turn=3)

    store = Store(str(db))
    try:
        with store.transaction() as conn:
            gone = MemoryStore(conn).retract_session("s1", 2, actor="undo")
    finally:
        store.close()

    assert gone == 2, "turn 2 and everything after it"
    assert _status(db, t1) == "active", "turn 1 was not undone"
    assert _status(db, t2) == "deleted" and _status(db, t3) == "deleted"


def test_only_a_retraction_is_reversible(tmp_path):
    """§3.4's machine keeps ``deleted`` terminal; the reversal is gated on the
    row's own *latest* deletion record, so a forget can never be quietly
    undone — not on a clean row, and not on one a retraction once touched."""
    db = _v3_db(tmp_path)
    retracted = _seed(db, content="the kanban board is called Flow 7", session="s1", turn=2)
    forgotten = _seed(db, content="the office wifi password is hunter2x", session="s1", turn=1)

    store = Store(str(db))
    try:
        with store.transaction() as conn:
            memories = MemoryStore(conn)
            memories.retract_session("s1", 2, actor="undo")
            forget = memories.set_status(forgotten, "deleted", actor="undo", reason="forget")
            assert forget.ok

            back = memories.set_status(retracted, "active", actor="review", reason="restore")
            assert back.ok and back.status == "active"

            with pytest.raises(InvalidTransition):
                memories.set_status(forgotten, "active", actor="review", reason="restore")

            # …and once restored, a later *forget* is terminal again: the
            # reversal reads the row's latest deletion, not any deletion it
            # ever had.
            assert memories.set_status(retracted, "deleted", actor="undo", reason="forget").ok
            with pytest.raises(InvalidTransition):
                memories.set_status(retracted, "active", actor="review", reason="restore")
    finally:
        store.close()


# --- the job ----------------------------------------------------------------


def test_the_retract_handler_runs_the_job_and_is_idempotent(tmp_path):
    db = _v3_db(tmp_path)
    undone = _seed(db, content="the deploy window is Sunday night", session="s1", turn=3)
    kept = _seed(db, content="the board is called Flow 7", session="s1", turn=1)

    outcomes = _enqueue_and_run(db, {"session_id": "s1", "from_turn": 3})
    assert [o.status for o in outcomes] == ["done"]
    assert _status(db, undone) == "deleted" and _status(db, kept) == "active"

    outcomes = _enqueue_and_run(db, {"session_id": "s1", "from_turn": 3})
    assert [o.status for o in outcomes] == ["done"], (
        "delivery is at-least-once: a re-run over an empty target set must converge, not raise"
    )


def test_a_malformed_retract_job_is_permanently_dead(tmp_path):
    db = _v3_db(tmp_path)

    assert [o.status for o in _enqueue_and_run(db, {"session_id": "", "from_turn": 3})] == ["dead"]
    assert [o.status for o in _enqueue_and_run(db, {"session_id": "s1", "from_turn": "three"})] == [
        "dead"
    ], "a non-integer turn is a contract violation, not a transient failure"
    assert [o.status for o in _enqueue_and_run(db, {"session_id": "s1", "from_turn": 0})] == ["dead"]


def test_the_operator_cli_registers_retract_turns(tmp_path):
    """The queue only moves for registered types; the CLI is the operator
    runner today (EM-410 will run the same registry in-process)."""
    db = _v3_db(tmp_path)
    mid = _seed(db, content="the staging key lives in the vault", session="s1", turn=5)
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            JobQueue(conn).enqueue("retract_turns", {"session_id": "s1", "from_turn": 5})
    finally:
        store.close()

    from em.jobs.cli import run_worker

    assert run_worker(Path(db), once=True, types=["retract_turns"]) == 0
    assert _status(db, mid) == "deleted"


# --- the provider end to end (the card's acceptance scenario) ---------------


def test_undo_removes_a_memory_stated_in_the_undone_turn(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        provider.on_turn_start(1, "first question about the deploy plan")
        kept = _remember(provider, "The staging deploy key lives in the vault")
        provider.on_turn_start(2, "second question — what is the board called")
        undone = _remember(provider, "The kanban board is called Flow 7")

        # /undo: the host rewound the conversation and forwards rewound=True.
        provider.on_session_switch("sess-undo", rewound=True, reason="undo")

        jobs = _rows(db, "SELECT type, payload FROM jobs WHERE type='retract_turns'")
        assert len(jobs) == 1, "the undo enqueues exactly one retraction"
        assert json.loads(jobs[0]["payload"]) == {"session_id": "sess-undo", "from_turn": 2}

        [outcome] = _run_retract_jobs(db)
        assert outcome.status == "done"
        assert _status(db, undone) == "deleted"
        assert _status(db, kept) == "active"

        # and the reversal the card promises: review can bring it back
        restored = json.loads(
            provider.handle_tool_call("entropicmem_review", {"action": "restore", "id": undone})
        )
        assert restored.get("ok") and restored.get("status") == "active"
        assert _status(db, undone) == "active"
    finally:
        provider.shutdown()


def test_a_second_undo_walks_back_another_turn(tmp_path):
    """Each undo retracts the turn it reversed — the counter steps back with it,
    so a second /undo reaches the previous turn instead of re-aiming at the
    last one."""
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        provider.on_turn_start(1, "turn one")
        first = _remember(provider, "the staging key lives in the vault")
        provider.on_turn_start(2, "turn two")
        second = _remember(provider, "the board is called Flow 7")
        provider.on_turn_start(3, "turn three")
        third = _remember(provider, "the retro is on Friday")

        provider.on_session_switch("sess-undo", rewound=True, reason="undo")
        _run_retract_jobs(db)
        assert _status(db, third) == "deleted"
        assert _status(db, second) == "active"

        provider.on_session_switch("sess-undo", rewound=True, reason="undo")
        _run_retract_jobs(db)
        assert _status(db, second) == "deleted"
        assert _status(db, first) == "active", "the counter stepped back, not just sideways"
    finally:
        provider.shutdown()


def test_rewind_on_a_v2_store_is_a_safe_no_op(tmp_path):
    """No v3 queue, no retraction: the v2 path stays exactly what it was."""
    db = _v2_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        provider.on_turn_start(1, "a question")
        with provider._open_engine(scope=provider._state.scope.write_scope()) as engine:
            engine.remember("the board is called Flow 7", session_id="sess-undo")
        provider.on_session_switch("sess-undo", rewound=True, reason="undo")
    finally:
        provider.shutdown()

    tables = {r["name"] for r in _rows(db, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "jobs" not in tables, "a v2 store has no queue to enqueue into"
    facts = _rows(db, "SELECT content FROM facts WHERE content LIKE '%Flow 7%'")
    assert facts, "nothing is retracted without a v3 queue to carry the job"


def test_the_rewind_budget_is_not_a_stall(tmp_path):
    """The hook runs on the agent thread with a 30 ms budget: enqueueing is one
    short transaction, never the retraction itself."""
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        provider.on_turn_start(1, "one")
        _remember(provider, "the staging key lives in the vault")
        provider.on_turn_start(2, "two")
        _remember(provider, "the board is called Flow 7")

        started = time.monotonic()
        provider.on_session_switch("sess-undo", rewound=True, reason="undo")
        elapsed = time.monotonic() - started
    finally:
        provider.shutdown()

    assert elapsed < 0.25, f"the undo hook took {elapsed:.3f}s — it must only enqueue"
    rows = _rows(db, "SELECT status FROM memories WHERE source_turn=2")
    assert [r["status"] for r in rows] == ["active"], (
        "the hook enqueues; the worker (not the turn) does the deleting"
    )
