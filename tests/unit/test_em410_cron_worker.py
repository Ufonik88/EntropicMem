"""EM-410 — cron & worker integration: the provider's JobWorker, harnessed.

The card: in ``agent_context == "cron"`` prefetch stays read-only, tool
writes are disabled, and the JobWorker runs when ``jobs.run_in_cron``
(bounded by ``jobs.cron_budget_s``); in primary gateway sessions the
JobWorker runs continuously and pauses while a prefetch is in flight.
The AC: a harness cron session drains queued jobs and performs no memory
writes via tools.

One group per claim:

* **cron** — the initialize-driven worker drains a queued ``retract_turns``
  job; ``entropicmem_remember`` is refused with ``writes_disabled`` and no
  row lands; the read path still serves a fact.
* **primary** — the worker runs, the in-flight gate is raised for the whole
  prefetch call (cleared even when the service raises), and a gated worker
  leaves jobs queued.
* **the gates** — ``jobs.run_in_cron`` / ``jobs.run_in_primary`` off start
  nothing; subagent/flush start nothing; a v2 store starts nothing; one
  start per provider.
* **the budget** — the cron worker is bounded by ``jobs.cron_budget_s``
  (a timer whose fire stops the loop); the primary worker has no timer.
* **the registry** — the shared builder carries the CLI's known set.

The harness drives the real ``initialize``: the plugin-local scripts tree
resolves (``plugins/entropicmem/scripts``), and the typed ``paths.memory_db``
and ``jobs.*`` keys arrive through the dashboard JSON source
(``$HERMES_HOME/entropicmem/config.json``) — §3.8's read order, as
production uses it. Only ``_spawn`` is replaced, for the same reason EM-403's
wiring tests replace it: under pytest the host factory is mocked to a no-op,
so a real thread factory stands in. The pause test raises the gate **before**
``initialize`` so the worker is born gated — no claim-before-gate race.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

from em.facade.engine import V3Engine  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.jobs import JobQueue  # noqa: E402
from memory_engine import MemoryEngine  # noqa: E402

SESSION = "em410-session"
STAGING = "the staging server runs on port 9090"
QUERY = "what port does the staging server use"
RETRACT = {"session_id": SESSION, "from_turn": 1}


# --- harness ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """The §3.8 env layer must not leak a developer's live paths into a test."""
    for name in ("ENTROPICMEM_MEMORY_DB", "ENTROPICMEM_INDEX_DB", "ENTROPICMEM_VAULT_PATH"):
        monkeypatch.delenv(name, raising=False)


def _v3_db(tmp_path: Path) -> Path:
    """A migrated v3 store with one invented fact."""
    db = tmp_path / "memory.db"
    engine = V3Engine(db)
    engine.remember(STAGING, domain="Infrastructure", importance=0.8)
    engine.close()
    return db


def _home_config(tmp_path: Path, *, memory_db: Path, **jobs) -> None:
    """``$HERMES_HOME/entropicmem/config.json`` — §3.8's dashboard source."""
    path = tmp_path / "entropicmem" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"paths": {"memory_db": str(memory_db)}, "jobs": jobs}),
        encoding="utf-8",
    )


def _build(*, config: dict | None = None):
    """One provider plus the names its ``_spawn`` was asked to start."""
    provider = EntropicMemMemoryProvider(
        config={"core_memory_enabled": False, "touch_on_inject": False, **(config or {})}
    )
    names: list[str] = []

    def spawn(target, name):
        names.append(name)
        threading.Thread(target=target, name=name, daemon=True).start()

    provider._spawn = spawn
    return provider, names


def _provider(tmp_path: Path, *, context: str = "primary", config: dict | None = None):
    provider, names = _build(config=config)
    provider.initialize(
        SESSION,
        hermes_home=str(tmp_path),
        agent_context=context,
        agent_identity="default",
    )
    return provider, names


def _enqueue(db: Path, job_type: str, payload: dict) -> str:
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            return JobQueue(conn).enqueue(job_type, payload)
    finally:
        store.close()


def _job_status(db: Path, job_id: str) -> str | None:
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            job = JobQueue(conn).get(job_id)
            return job.status if job is not None else None
    finally:
        store.close()


def _memory_count(db: Path) -> int:
    store = Store(str(db))
    try:
        row = store.reader().execute("SELECT COUNT(*) FROM memories").fetchone()
        return int(row[0])
    finally:
        store.close()


def _wait_until(predicate, *, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


# --- cron: the AC -----------------------------------------------------------


def test_cron_session_drains_queued_jobs(tmp_path):
    """AC: a harness cron session drains queued jobs."""
    db = _v3_db(tmp_path)
    _home_config(tmp_path, memory_db=db)
    job_id = _enqueue(db, "retract_turns", dict(RETRACT))
    provider, names = _provider(tmp_path, context="cron")
    try:
        assert provider._scripts_dir is not None
        assert provider._memory_db == db
        assert provider._jobs_started is True
        assert "entropicmem-jobs" in names
        assert _wait_until(lambda: _job_status(db, job_id) == "done"), _job_status(db, job_id)
    finally:
        provider.shutdown()


def test_cron_tool_writes_are_refused(tmp_path):
    """AC: ... and performs no memory writes via tools."""
    db = _v3_db(tmp_path)
    _home_config(tmp_path, memory_db=db)
    provider, _ = _provider(tmp_path, context="cron")
    try:
        assert provider._writes_allowed() is False
        before = _memory_count(db)
        out = json.loads(
            provider.handle_tool_call("entropicmem_remember", {"content": "should not land"})
        )
        assert out["reason_code"] == "writes_disabled"
        assert _memory_count(db) == before
    finally:
        provider.shutdown()


def test_cron_prefetch_stays_read_only_and_serving(tmp_path):
    db = _v3_db(tmp_path)
    _home_config(tmp_path, memory_db=db)
    provider, _ = _provider(tmp_path, context="cron")
    try:
        block = provider.prefetch(QUERY)
        assert STAGING in block
    finally:
        provider.shutdown()


# --- primary: the gate ------------------------------------------------------


def test_primary_worker_runs_and_the_prefetch_raises_the_gate(tmp_path):
    db = _v3_db(tmp_path)
    _home_config(tmp_path, memory_db=db)
    provider, names = _provider(tmp_path, context="primary")
    try:
        assert provider._jobs_started is True
        assert "entropicmem-jobs" in names
        assert provider._jobs_timer is None  # only cron is budgeted

        seen: list[bool] = []

        class _Stub:
            def prefetch(self, *a, **k):
                seen.append(provider._prefetch_in_flight.is_set())
                return SimpleNamespace(text="", injected_count=0)

        provider._prefetch_service_for_turn = lambda: _Stub()
        provider.prefetch("hello")
        assert seen == [True]  # raised for the whole call
        assert not provider._prefetch_in_flight.is_set()

        class _Boom:
            def prefetch(self, *a, **k):
                seen.append(provider._prefetch_in_flight.is_set())
                raise RuntimeError("boom")

        provider._prefetch_service_for_turn = lambda: _Boom()
        assert provider.prefetch("hello") == ""  # fail-soft, as before
        assert seen == [True, True]
        assert not provider._prefetch_in_flight.is_set()  # cleared even on a raise
    finally:
        provider.shutdown()


def test_worker_pauses_while_the_gate_is_raised(tmp_path):
    db = _v3_db(tmp_path)
    _home_config(tmp_path, memory_db=db)
    provider, _ = _build()
    gate = provider._prefetch_in_flight
    gate.set()  # raise it before initialize so the worker is born gated
    job_id = _enqueue(db, "retract_turns", dict(RETRACT))
    provider.initialize(
        SESSION, hermes_home=str(tmp_path), agent_context="primary", agent_identity="default"
    )
    try:
        time.sleep(0.5)
        assert _job_status(db, job_id) == "queued"  # gated, not claimed
        gate.clear()
        assert _wait_until(lambda: _job_status(db, job_id) == "done")
    finally:
        gate.clear()
        provider.shutdown()


# --- the gates --------------------------------------------------------------


@pytest.mark.parametrize("context,key", [("cron", "run_in_cron"), ("primary", "run_in_primary")])
def test_disabled_config_starts_nothing(tmp_path, context, key):
    db = _v3_db(tmp_path)
    _home_config(tmp_path, memory_db=db, **{key: False})
    provider, names = _provider(tmp_path, context=context)
    try:
        assert provider._jobs_started is False
        assert names == []
        job_id = _enqueue(db, "retract_turns", dict(RETRACT))
        time.sleep(0.3)
        assert _job_status(db, job_id) == "queued"
    finally:
        provider.shutdown()


@pytest.mark.parametrize("context", ["subagent", "flush"])
def test_no_worker_outside_primary_and_cron(tmp_path, context):
    db = _v3_db(tmp_path)
    _home_config(tmp_path, memory_db=db)
    provider, names = _provider(tmp_path, context=context)
    try:
        assert provider._jobs_started is False
        assert names == []
    finally:
        provider.shutdown()


def test_missing_store_file_starts_nothing_and_pins_nothing(tmp_path):
    """A store that does not exist yet must not pin the instance to the v2 path."""
    missing = tmp_path / "memory.db"  # never created
    _home_config(tmp_path, memory_db=missing)
    provider, names = _provider(tmp_path, context="primary")
    try:
        assert provider._jobs_started is False
        assert names == []
        assert not missing.exists()  # the probe must not create the store file
        assert provider._prefetch_service_kind is None  # cache left unpinned
    finally:
        provider.shutdown()


def test_v2_store_starts_nothing(tmp_path):
    db = tmp_path / "memory.db"
    engine = MemoryEngine(db, profile_id="default")
    engine.remember(STAGING, importance=0.8, source="agent")
    engine.close()
    _home_config(tmp_path, memory_db=db)
    provider, names = _provider(tmp_path, context="primary")
    try:
        assert provider._jobs_started is False
        assert names == []
    finally:
        provider.shutdown()


def test_worker_starts_once_per_provider(tmp_path):
    db = _v3_db(tmp_path)
    _home_config(tmp_path, memory_db=db)
    provider, names = _provider(tmp_path, context="primary")
    try:
        provider._start_job_workers()
        provider._start_job_workers()
        assert names.count("entropicmem-jobs") == 1
    finally:
        provider.shutdown()


# --- the budget -------------------------------------------------------------


def test_cron_worker_is_budgeted_by_cron_budget_s(tmp_path):
    db = _v3_db(tmp_path)
    _home_config(tmp_path, memory_db=db, cron_budget_s=17)
    provider, _ = _provider(tmp_path, context="cron")
    try:
        timer = provider._jobs_timer
        assert timer is not None
        assert timer.interval == 17.0
        timer.function()  # the budget fires -> the loop stops
        assert provider._jobs_done.wait(2)
        job_id = _enqueue(db, "retract_turns", dict(RETRACT))
        time.sleep(0.3)
        assert _job_status(db, job_id) == "queued"  # stopped, not draining
    finally:
        provider.shutdown()


# --- shutdown ---------------------------------------------------------------


def test_shutdown_stops_the_worker_and_releases_its_store(tmp_path):
    db = _v3_db(tmp_path)
    _home_config(tmp_path, memory_db=db)
    provider, _ = _provider(tmp_path, context="primary")
    provider.shutdown()
    try:
        assert provider._jobs_done.wait(2)
        assert provider._jobs_store is None
        job_id = _enqueue(db, "retract_turns", dict(RETRACT))
        time.sleep(0.3)
        assert _job_status(db, job_id) == "queued"
    finally:
        provider.shutdown()


# --- the registry -----------------------------------------------------------


def test_registry_builder_carries_the_known_set(tmp_path):
    from em.jobs.cli import _KNOWN_TYPES
    from em.jobs.registry import KNOWN_JOB_TYPES, build_registry

    db = _v3_db(tmp_path)
    assert set(_KNOWN_TYPES) == set(KNOWN_JOB_TYPES)  # CLI and provider cannot drift
    assert build_registry(str(db)).types() == sorted(KNOWN_JOB_TYPES)
    assert build_registry(str(db), types=["link"]).types() == ["link"]
