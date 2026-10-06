"""EM-211 Chunk 7: the entity-link job (``link:<memory_id>:<version>``).

Chunk 7 moves entity linking off the write path. ``EntityLinker`` and
``EntityStore.link`` already existed (EM-208); what was missing is the queueing:
nothing enqueued a link job, and no worker registered a ``link`` handler, so a v3
memory was never bound to an entity.

Two rules shape the tests:

* **Invariant 2.** The linker must never run inside the write transaction that
  created the memory. The store *enqueues*; the handler runs outside any write
  transaction and opens its own.
* **At-least-once delivery.** A job can be retried after a lost lease, so the
  handler must converge. ``EntityStore.link`` upserts and its sighting counter
  counts distinct memories, so a re-run is a no-op — that is asserted, not
  assumed.

The §3.5 owner-only rule is deliberately **not** here: it needs the gateway
identity threaded from the provider, which is a separate change (chunk 7.2).

Rules: invented data only (Acme/Globex/Initech, Alice/Bob Example).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.formation.entity_linker import make_link_handler  # noqa: E402
from em.jobs import HandlerRegistry, JobWorker  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.entities import EntityStore  # noqa: E402
from em.store.jobs import JobQueue  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, MemoryPatch, Scope  # noqa: E402

OWNER = Scope(profile="default")


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as conn:
        migrate(conn)
    yield s
    s.close()


def add(store, content: str, *, source: str = "agent"):
    with store.transaction() as conn:
        return MemoryStore(conn).add(
            MemoryDraft(content=content, source=source), scope=OWNER, actor="tester"
        )


def jobs_of(store, job_type: str):
    return store.reader().execute(
        "SELECT * FROM jobs WHERE type=? ORDER BY created_at, id", (job_type,)
    ).fetchall()


def links_of(store, memory_id: str) -> list[str]:
    return [r["entity_id"] for r in store.reader().execute(
        "SELECT entity_id FROM memory_entities WHERE memory_id=?", (memory_id,))]


def run_link(store, *, worker_id: str = "w"):
    reg = HandlerRegistry()
    reg.register("link", make_link_handler())
    return JobWorker(store, reg, worker_id=worker_id).run_until_idle()


def knows_entity(store, name: str) -> str:
    with store.transaction() as conn:
        return EntityStore(conn).get_or_create_entity(name, scope=OWNER)


# --- the enqueue --------------------------------------------------------------


def test_add_queues_exactly_one_link_job(store):
    result = add(store, "Acme deploys the billing service.")
    queued = jobs_of(store, "link")
    assert len(queued) == 1, "a write must queue the link work, once"
    payload = queued[0]["payload"]
    assert result.id in payload
    assert queued[0]["dedupe_key"] == f"link:{result.id}:1"


def test_repeated_writes_do_not_pile_up_link_jobs(store):
    """The dedupe key identifies the work: one job per (memory, version)."""
    add(store, "Acme deploys the billing service.")
    add(store, "Acme deploys the billing service.")
    add(store, "Acme deploys the billing service.")
    assert len(jobs_of(store, "link")) == 1


def test_a_pending_memory_queues_no_link_job(store):
    """A quarantined memory is not live, so there is nothing to link yet."""
    add(store, "Acme deploys the billing service.", source="auto_extracted")
    assert jobs_of(store, "link") == []


def test_promotion_to_active_queues_a_link_job(store):
    result = add(store, "Acme deploys the billing service.", source="auto_extracted")
    assert jobs_of(store, "link") == []
    with store.transaction() as conn:
        MemoryStore(conn).set_status(result.id, "active", actor="tester", reason="auto_commit")
    queued = jobs_of(store, "link")
    assert len(queued) == 1, "a memory that becomes live must be linked"
    assert result.id in queued[0]["payload"]


def test_a_content_update_queues_a_fresh_link_job(store):
    """New content is new entity material, so the job is re-queued at the new version."""
    result = add(store, "Acme deploys the billing service.")
    with store.transaction() as conn:
        MemoryStore(conn).update(result.id, MemoryPatch(content="Globex keeps a staging cluster."),
                                 actor="tester", reason="edit")
    keys = {j["dedupe_key"] for j in jobs_of(store, "link")}
    assert keys == {f"link:{result.id}:1", f"link:{result.id}:2"}


# --- the handler --------------------------------------------------------------


def test_handler_links_a_known_entity(store):
    entity_id = knows_entity(store, "Acme")
    result = add(store, "Acme deploys the billing service.")

    outcomes = run_link(store)
    assert [o.status for o in outcomes] == ["done"]
    assert links_of(store, result.id) == [entity_id]


def test_handler_is_idempotent_across_a_retry(store):
    """Delivery is at-least-once; a re-run must not duplicate or inflate anything."""
    entity_id = knows_entity(store, "Acme")
    result = add(store, "Acme deploys the billing service.")
    run_link(store)

    # Re-run the same work exactly as a lost-lease retry would: a fresh job for
    # the same memory and version, then the handler again.
    with store.transaction() as conn:
        JobQueue(conn).enqueue("link", {"memory_id": result.id, "version": 1},
                               dedupe_key=f"link:{result.id}:1:retry")
    run_link(store)

    assert links_of(store, result.id) == [entity_id], "one link, not two"


def test_handler_creates_no_entity_from_a_single_sighting(store):
    """The two-sighting rule survives the move off the write path.

    The phrase sits mid-sentence on purpose: a sentence-opening capitalised word
    is discarded by ``candidate_phrases`` (EM-208), so a sentence-initial name
    would test the opener rule rather than the sighting count.
    """
    result = add(store, "We met Zorp Systems about the window.")
    run_link(store)
    assert links_of(store, result.id) == [], (
        "a phrase seen once must not become an entity"
    )


def test_handler_promotes_on_the_second_sighting(store):
    """The two-sighting rule is EM-208's and the job wrapper does not change it.

    Promotion fires on whichever memory's job trips the counter, so exactly one
    of the pair is linked; **which** one depends on job claim order, not on write
    order, so the test does not assume it. The other is not retro-linked: its own
    job has already run by then, so in a real queue it stays unlinked until its
    content changes or something reconciles it. That is EM-208's semantics, not
    this chunk's to change (backfill is the plan's ``reconcile`` job in S5), and
    it is asserted here so it cannot drift unnoticed. Re-running both jobs once
    the entity exists links both, which is the recoverable path.
    """
    first = add(store, "We met Zorp Systems about the window.")
    second = add(store, "Then Zorp Systems owns the window.")
    run_link(store)

    with store.transaction() as conn:
        assert EntityStore(conn).find_entity("zorp systems") is not None, (
            "the second sighting must create the entity"
        )
    linked = [m for m in (first.id, second.id) if links_of(store, m)]
    assert len(linked) == 1, (
        f"promotion links exactly the memory that trips the counter, got {linked}"
    )

    for mid in (first.id, second.id):
        with store.transaction() as conn:
            JobQueue(conn).enqueue("link", {"memory_id": mid, "version": 1},
                                   dedupe_key=f"link:{mid}:1:again")
    run_link(store)
    assert links_of(store, first.id) and links_of(store, second.id), (
        "once the entity exists, a re-run resolves it for both"
    )


def test_handler_dead_letters_a_missing_memory(store):
    with store.transaction() as conn:
        JobQueue(conn).enqueue("link", {"memory_id": "mem_gone", "version": 1},
                               dedupe_key="link:mem_gone:1")
    outcomes = run_link(store)
    assert [o.status for o in outcomes] == ["dead"], (
        "a missing memory can never succeed, so retrying cannot help"
    )


def test_handler_dead_letters_a_payload_with_no_memory_id(store):
    with store.transaction() as conn:
        JobQueue(conn).enqueue("link", {}, dedupe_key="link:empty:1")
    outcomes = run_link(store)
    assert [o.status for o in outcomes] == ["dead"]


def test_handler_skips_a_memory_that_is_no_longer_live(store):
    # A known entity on purpose: a live row *would* link, so an empty result
    # means the status guard fired rather than that there was nothing to find.
    knows_entity(store, "Acme")
    result = add(store, "Acme deploys the billing service.")
    with store.transaction() as conn:
        MemoryStore(conn).set_status(result.id, "deleted", actor="tester", reason="forget")

    outcomes = run_link(store)
    assert [o.status for o in outcomes] == ["done"], "nothing to do is not a failure"
    assert links_of(store, result.id) == [], "a forgotten memory must not be linked"


def test_handler_skips_a_still_pending_memory(store):
    result = add(store, "Acme deploys the billing service.", source="auto_extracted")
    with store.transaction() as conn:
        JobQueue(conn).enqueue("link", {"memory_id": result.id, "version": 1},
                               dedupe_key="link:pending:1")
    run_link(store)
    assert links_of(store, result.id) == []


def test_handler_runs_outside_any_write_transaction(store):
    """Invariant 2: entity work must never hold the SQLite write lock."""
    knows_entity(store, "Acme")
    add(store, "Acme deploys the billing service.")
    observed = {}
    inner = make_link_handler()

    reg = HandlerRegistry()

    @reg.register("link")
    def _probe(job, ctx):
        observed["in_txn"] = ctx.store.writer().in_transaction
        inner(job, ctx)

    queued = jobs_of(store, "link")[0]
    JobWorker(store, reg, worker_id="w").run_once()
    assert observed["in_txn"] is False, "the handler held the write lock"
    assert queued["id"]  # sanity: a real job ran


def test_handler_uses_the_memorys_own_scope(store):
    """Linking must use the row's scope, not a default, or names cross profiles."""
    add(store, "Acme deploys the billing service.")
    reg = HandlerRegistry()
    seen = {}

    @reg.register("link")
    def _spy(job, ctx):
        with ctx.store.transaction() as conn:
            row = MemoryStore(conn).get(job.payload["memory_id"])
            seen["profile"] = row["scope_profile"]
        make_link_handler()(job, ctx)

    JobWorker(store, reg, worker_id="w").run_once()
    assert seen["profile"] == OWNER.profile


# --- the wiring ---------------------------------------------------------------


def test_entity_linker_and_handler_agree_on_the_job_type(store):
    from em.jobs.cli import _KNOWN_TYPES

    assert "link" in _KNOWN_TYPES, "the worker CLI must know how to run a link job"
    assert "backup" in _KNOWN_TYPES, "and must not have dropped the one it had"


def test_worker_registers_the_link_handler(tmp_path):
    """`entropicmem worker run --types link` must claim the job, not skip it."""
    from em.jobs.cli import run_worker

    db = tmp_path / "memory.db"
    store = Store(str(db))
    try:
        with store.writer() as conn:
            migrate(conn)
        with store.transaction() as conn:
            MemoryStore(conn).add(MemoryDraft(content="Acme deploys the billing service."),
                                  scope=OWNER, actor="tester")
    finally:
        store.close()

    assert run_worker(db, once=True, types=["link"]) == 0
    check = Store(str(db))
    try:
        statuses = [r["status"] for r in check.reader().execute(
            "SELECT status FROM jobs WHERE type='link'")]
    finally:
        check.close()
    assert statuses == ["done"]
