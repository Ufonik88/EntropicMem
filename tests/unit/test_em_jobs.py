"""EM-209: durable job queue (``em.store.jobs``) and worker (``em.jobs``)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em import clock  # noqa: E402
from em.jobs import HandlerRegistry, JobWorker, PermanentJobError  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.jobs import (  # noqa: E402
    MAX_ERROR_CHARS,
    JobQueue,
    backoff_seconds,
    sanitise_error,
)
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

T0 = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as conn:
        migrate(conn)
    yield s
    s.close()


def enqueue(store, *args, **kwargs) -> str:
    with store.transaction() as conn:
        return JobQueue(conn).enqueue(*args, **kwargs)


def claim(store, worker="w1", **kwargs):
    with store.transaction() as conn:
        return JobQueue(conn).claim(worker, **kwargs)


def get(store, job_id):
    return JobQueue(store.reader()).get(job_id)


# --- enqueue ---------------------------------------------------------------


def test_enqueue_round_trips_payload_and_defaults(store):
    with clock.freeze(T0):
        jid = enqueue(store, "demo", {"b": 2, "a": "x"})
    job = get(store, jid)
    assert jid.startswith("job_")
    assert job.type == "demo" and job.payload == {"a": "x", "b": 2}
    assert (job.status, job.priority, job.attempts, job.max_attempts) == ("queued", 5, 0, 5)
    assert job.run_after == clock.to_iso(T0)


@pytest.mark.parametrize("kwargs", [{"type": ""}, {"type": "x", "max_attempts": 0}])
def test_enqueue_rejects_bad_arguments(store, kwargs):
    with pytest.raises(ValueError):
        enqueue(store, **kwargs)


def test_dedupe_refreshes_a_queued_job_instead_of_adding_one(store):
    a = enqueue(store, "demo", {"v": 1}, dedupe_key="k")
    b = enqueue(store, "demo", {"v": 2}, dedupe_key="k", priority=1)
    assert a == b
    job = get(store, a)
    assert job.payload == {"v": 2} and job.priority == 1
    assert JobQueue(store.reader()).stats() == {"demo": {"queued": 1}}


@pytest.mark.parametrize("final", ["done", "dead"])
def test_dedupe_leaves_a_finished_job_alone(store, final):
    jid = enqueue(store, "demo", {"v": 1}, dedupe_key="k", max_attempts=1)
    claim(store)
    with store.transaction() as conn:
        q = JobQueue(conn)
        if final == "done":
            assert q.complete(jid, "w1")
        else:
            assert q.fail(jid, "w1", "boom") == "dead"
    assert enqueue(store, "demo", {"v": 2}, dedupe_key="k") == jid
    job = get(store, jid)
    assert job.status == final and job.payload == {"v": 1}


def test_memory_add_enqueues_one_embed_job_per_version(store):
    scope = Scope(profile="default", user="")
    with store.transaction() as conn:
        mid = MemoryStore(conn).add(MemoryDraft(content="The build uses Acme CI."), scope=scope, actor="t").id
    job = JobQueue(store.reader()).get_by_key(f"embed:{mid}:1")
    assert job is not None and job.type == "embed" and job.payload == {"memory_id": mid, "version": 1}


# --- claim -----------------------------------------------------------------


def test_claim_order_is_priority_then_age(store):
    with clock.freeze(T0):
        late_urgent = enqueue(store, "demo", priority=1)
    with clock.freeze(T0 - timedelta(minutes=5)):
        old_normal = enqueue(store, "demo", priority=5)
        old_urgent = enqueue(store, "demo", priority=1)
    with clock.freeze(T0 + timedelta(seconds=1)):
        order = [claim(store).id for _ in range(3)]
    assert order == [old_urgent, late_urgent, old_normal]


def test_claim_waits_for_run_after(store):
    with clock.freeze(T0):
        jid = enqueue(store, "demo", run_after=T0 + timedelta(minutes=10))
        assert claim(store) is None
    with clock.freeze(T0 + timedelta(minutes=10)):
        assert claim(store).id == jid


def test_claim_only_takes_registered_types(store):
    enqueue(store, "other")
    assert claim(store, types=["demo"]) is None
    assert claim(store, types=[]) is None
    assert claim(store, types=["other"]).type == "other"


def test_claim_sets_a_lease_and_counts_the_attempt(store):
    with clock.freeze(T0):
        jid = enqueue(store, "demo")
        job = claim(store, "w1", lease_seconds=30)
        assert claim(store, "w2") is None  # leased
    assert job.id == jid and job.status == "running" and job.attempts == 1
    assert job.locked_by == "w1"
    assert job.locked_until == clock.to_iso(T0 + timedelta(seconds=30))


def test_an_expired_lease_is_reclaimed_and_the_old_holder_is_told(store):
    with clock.freeze(T0):
        jid = enqueue(store, "demo")
        claim(store, "w1", lease_seconds=30)
    with clock.freeze(T0 + timedelta(seconds=31)):
        again = claim(store, "w2", lease_seconds=30)
        assert again.id == jid and again.attempts == 2 and again.locked_by == "w2"
        with store.transaction() as conn:
            q = JobQueue(conn)
            assert q.complete(jid, "w1") is False  # lost
            assert q.heartbeat(jid, "w1") is False
            assert q.fail(jid, "w1", "late") is None
            assert q.complete(jid, "w2") is True


def test_a_job_that_keeps_killing_workers_goes_dead(store):
    """attempts counts at claim time, so a crash (no fail() call) still uses
    an attempt, and a poison job cannot take down every worker forever."""
    with clock.freeze(T0):
        jid = enqueue(store, "demo", max_attempts=2)
        claim(store, "w1", lease_seconds=10)  # attempt 1, worker "dies"
    with clock.freeze(T0 + timedelta(seconds=11)):
        claim(store, "w2", lease_seconds=10)  # attempt 2, dies too
    with clock.freeze(T0 + timedelta(seconds=22)):
        assert claim(store, "w3") is None
    job = get(store, jid)
    assert job.status == "dead" and job.locked_by is None
    assert "lease expired" in job.last_error


# --- fail / retry ----------------------------------------------------------


def test_backoff_is_exponential_capped_and_jittered():
    assert backoff_seconds(1, rand=lambda: 0.5) == pytest.approx(30)
    assert backoff_seconds(3, rand=lambda: 0.5) == pytest.approx(120)
    assert backoff_seconds(50, rand=lambda: 0.5) == pytest.approx(3600)
    assert backoff_seconds(1, rand=lambda: 0.0) == pytest.approx(27)
    assert backoff_seconds(1, rand=lambda: 1.0) == pytest.approx(33)


def test_fail_schedules_a_retry_then_dead_letters(store):
    with clock.freeze(T0):
        jid = enqueue(store, "demo", max_attempts=2)
        claim(store)
        with store.transaction() as conn:
            assert JobQueue(conn).fail(jid, "w1", RuntimeError("nope"), rand=lambda: 0.5) == "failed"
        job = get(store, jid)
        assert job.run_after == clock.to_iso(T0 + timedelta(seconds=30))
        assert job.last_error == "RuntimeError: nope"
        assert claim(store) is None  # backing off
    with clock.freeze(T0 + timedelta(seconds=30)):
        assert claim(store).attempts == 2
        with store.transaction() as conn:
            assert JobQueue(conn).fail(jid, "w1", "again") == "dead"
    with clock.freeze(T0 + timedelta(days=1)):
        assert claim(store) is None


def test_permanent_failure_skips_the_retries(store):
    jid = enqueue(store, "demo", max_attempts=5)
    claim(store)
    with store.transaction() as conn:
        assert JobQueue(conn).fail(jid, "w1", "bad payload", permanent=True) == "dead"


def test_last_error_is_first_line_only_and_capped():
    err = sanitise_error(ValueError("line one\nsecret second line"))
    assert err == "ValueError: line one"
    assert len(sanitise_error("x" * 5000)) == MAX_ERROR_CHARS
    assert sanitise_error("") == ""


def test_release_gives_the_attempt_back(store):
    jid = enqueue(store, "demo")
    claim(store)
    with store.transaction() as conn:
        assert JobQueue(conn).release(jid, "w1")
    job = get(store, jid)
    assert (job.status, job.attempts, job.locked_by) == ("queued", 0, None)


def test_heartbeat_extends_the_lease(store):
    with clock.freeze(T0):
        jid = enqueue(store, "demo")
        claim(store, lease_seconds=10)
    with clock.freeze(T0 + timedelta(seconds=9)):
        with store.transaction() as conn:
            assert JobQueue(conn).heartbeat(jid, "w1", lease_seconds=10)
    with clock.freeze(T0 + timedelta(seconds=15)):
        assert claim(store, "w2") is None  # would have expired at +10 without it


# --- operating -------------------------------------------------------------


def test_retry_dead_prune_stats_and_next_run_after(store):
    with clock.freeze(T0):
        dead = enqueue(store, "demo", max_attempts=1)
        claim(store)
        with store.transaction() as conn:
            JobQueue(conn).fail(dead, "w1", "x")
        done = enqueue(store, "demo")
        claim(store)
        with store.transaction() as conn:
            JobQueue(conn).complete(done, "w1")
        later = enqueue(store, "other", run_after=T0 + timedelta(hours=1))
        q = JobQueue(store.reader())
        assert q.stats() == {"demo": {"dead": 1, "done": 1}, "other": {"queued": 1}}
        assert q.next_run_after(types=["other"]) == T0 + timedelta(hours=1)
        assert q.next_run_after(types=["demo"]) is None
        assert [j.id for j in q.list(status="dead")] == [dead]
        with pytest.raises(ValueError):
            q.list(status="nonsense")
    with clock.freeze(T0 + timedelta(days=8)):
        with store.transaction() as conn:
            assert JobQueue(conn).prune() == 1  # done > 7 days; dead kept (30)
    with clock.freeze(T0 + timedelta(days=31)):
        with store.transaction() as conn:
            q = JobQueue(conn)
            assert q.retry_dead(dead) is True
            assert q.get(dead).status == "queued" and q.get(dead).attempts == 0
            assert q.retry_dead(later) is False  # only dead jobs


# --- worker ----------------------------------------------------------------


def test_worker_runs_handlers_and_records_outcomes(store):
    seen = []
    reg = HandlerRegistry()

    @reg.register("ok")
    def _ok(job, ctx):
        seen.append(job.payload["n"])

    @reg.register("flaky")
    def _flaky(job, ctx):
        raise RuntimeError("transient")

    @reg.register("bad")
    def _bad(job, ctx):
        raise PermanentJobError("malformed")

    for n in range(3):
        enqueue(store, "ok", {"n": n})
    enqueue(store, "flaky")
    enqueue(store, "bad")
    orphan = enqueue(store, "no_handler_for_this")

    outcomes = JobWorker(store, reg, worker_id="w").run_until_idle()
    assert sorted(seen) == [0, 1, 2]
    assert sorted(o.status for o in outcomes) == ["dead", "done", "done", "done", "failed"]
    assert get(store, orphan).status == "queued"  # never claimed


def test_handler_runs_outside_any_write_transaction(store):
    """The rule the module exists for: no handler (embedding call, LLM
    call) ever holds the SQLite write lock. The handler's own writes go
    through ctx.store.transaction() and must not deadlock."""
    reg = HandlerRegistry()
    state = {}

    @reg.register("probe")
    def _probe(job, ctx):
        state["in_txn"] = ctx.store.writer().in_transaction
        with ctx.store.transaction() as conn:
            conn.execute("INSERT INTO meta (key, value) VALUES ('probe', 'ran')")

    enqueue(store, "probe")
    assert JobWorker(store, reg).run_once().status == "done"
    assert state["in_txn"] is False
    assert store.reader().execute("SELECT value FROM meta WHERE key='probe'").fetchone()[0] == "ran"


def test_handler_lease_is_its_own_not_the_longest(store):
    reg = HandlerRegistry()
    reg.register("short", lambda job, ctx: None, lease_seconds=5)
    reg.register("long", lambda job, ctx: None, lease_seconds=600)
    leases = {}

    def spy(job, ctx):
        leases["until"] = get(store, job.id).locked_until

    reg._handlers["short"].handler = spy  # observe the live lease mid-run
    with clock.freeze(T0):
        enqueue(store, "short")
        JobWorker(store, reg).run_once()
    assert leases["until"] == clock.to_iso(T0 + timedelta(seconds=5))


def test_registering_a_type_twice_is_an_error():
    reg = HandlerRegistry()
    reg.register("a", lambda j, c: None)
    with pytest.raises(ValueError):
        reg.register("a", lambda j, c: None)


def test_interrupt_releases_the_job_and_propagates(store):
    reg = HandlerRegistry()

    @reg.register("stop")
    def _stop(job, ctx):
        raise KeyboardInterrupt

    jid = enqueue(store, "stop")
    with pytest.raises(KeyboardInterrupt):
        JobWorker(store, reg).run_once()
    job = get(store, jid)
    assert (job.status, job.attempts) == ("queued", 0)


def test_context_heartbeat_reports_a_lost_lease(store):
    reg = HandlerRegistry()
    result = {}

    @reg.register("slow", lease_seconds=10)
    def _slow(job, ctx):
        with clock.freeze(T0 + timedelta(seconds=11)):
            claim(store, "thief")  # lease expired, someone else took it
            result["hb"] = ctx.heartbeat()
            result["again"] = ctx.heartbeat()

    with clock.freeze(T0):
        enqueue(store, "slow")
        outcome = JobWorker(store, reg, worker_id="w").run_once()
    assert result == {"hb": False, "again": False}
    assert outcome.status == "lost"


def test_run_loop_stops_promptly(store):
    reg = HandlerRegistry()
    done = threading.Event()
    reg.register("ping", lambda job, ctx: done.set())
    stop = threading.Event()
    # The worker needs its own Store: a Store's writer connection belongs to
    # the thread discipline of its owner, and this is a second thread.
    worker_store = Store(store.path)
    t = threading.Thread(target=JobWorker(worker_store, reg).run, args=(stop,), kwargs={"poll_seconds": 0.05})
    t.start()
    try:
        enqueue(store, "ping")
        assert done.wait(5), "worker never ran the job"
    finally:
        stop.set()
        t.join(5)
        worker_store.close()
    assert not t.is_alive()


def test_four_processes_run_each_job_exactly_once(tmp_path, store):
    """AC: concurrent workers in separate processes never double-claim.

    Each handler run inserts the job id into a table with a UNIQUE key, so a
    double run would raise inside the handler and show up as a failed job.
    """
    with store.transaction() as conn:
        conn.execute("CREATE TABLE ran (job_id TEXT PRIMARY KEY, worker TEXT NOT NULL)")
        q = JobQueue(conn)
        for n in range(300):
            q.enqueue("count", {"n": n})
    script = textwrap.dedent(
        f"""
        import pathlib, sys, time
        sys.path.insert(0, {str(SCRIPTS)!r})
        from em.jobs import HandlerRegistry, JobWorker
        from em.store.db import Store
        s = Store({str(store.path)!r})
        reg = HandlerRegistry()
        wid = sys.argv[1]
        # Start barrier: interpreter start-up is slow on some CI runners, and
        # without it the first process can drain the queue before the others
        # exist, which would prove nothing about concurrent claims.
        gate = pathlib.Path({str(tmp_path)!r})
        (gate / f"ready_{{wid}}").touch()
        deadline = time.monotonic() + 60
        while len(list(gate.glob("ready_*"))) < 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        def count(job, ctx):
            time.sleep(0.001)  # a little real work, so claims interleave
            with ctx.store.transaction() as conn:
                conn.execute("INSERT INTO ran (job_id, worker) VALUES (?, ?)", (job.id, wid))
        reg.register("count", count)
        outs = JobWorker(s, reg, worker_id=wid).run_until_idle()
        bad = [o for o in outs if o.status != "done"]
        s.close()
        print(len(outs), len(bad))
        """
    )
    procs = [
        subprocess.Popen([sys.executable, "-c", script, f"p{i}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for i in range(4)
    ]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
        results.append(tuple(int(x) for x in out.split()))
    assert sum(r[0] for r in results) == 300
    assert all(r[1] == 0 for r in results), results
    conn = store.reader()
    assert conn.execute("SELECT count(*) FROM ran").fetchone()[0] == 300
    assert JobQueue(conn).stats() == {"count": {"done": 300}}
    # Work was actually shared, not serialised onto one process.
    assert conn.execute("SELECT count(DISTINCT worker) FROM ran").fetchone()[0] >= 2
