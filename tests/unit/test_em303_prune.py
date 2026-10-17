"""EM-303 — the ``prune`` job: a destructive, worker-only handler.

Rules the tests pin (``docs/plan/PRUNE_CARD_DRAFT.md``; the test plan is the
arbiter where the draft's AC2 tail contradicts the spec's own delete rule and
its rollback story — the **previous** model's rows survive after the grace and
are only prunable once a newer completed backfill demotes them):

* **Nothing deletes without a completed backfill.** An empty
  ``meta.embedding_model`` or a missing transition record
  (``embedding_model_previous`` / ``embedding_model_switched_at``) is a
  no-op, logged — never a guess and never a dead job.
* **The grace gates the whole prune.** Deletion runs only when
  ``now − embedding_model_switched_at`` exceeds the grace (default 7 days,
  payload-overridable). A partial backfill never authorizes deletion.
* **Current and previous survive.** After the grace, one run deletes every
  row whose model is neither the current nor the immediately previous one.
* **Dry-run reports per-model counts and deletes nothing.**
* **Vacuum comes after the delete commits**, on the worker's call stack, and
  ``prune`` may only be imported by the job registry (no request path).
* **Idempotent** — a second run deletes nothing more.

Invented data only: Acme. Bob Example waters the fern.
"""

from __future__ import annotations

import logging
import sys
from datetime import timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import parse_iso, to_iso, utc_now  # noqa: E402
from em.embeddings.jobs import ensure_embedding_model  # noqa: E402
from em.embeddings.prune import make_prune_handler  # noqa: E402
from em.jobs import HandlerRegistry, JobWorker  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.embeddings import (  # noqa: E402
    put_embedding,
    set_stored_model,
    stored_model,
)
from em.store.jobs import JobQueue  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

OWNER = Scope(profile="default")
MODEL_OLD = "fake-embed-a"
MODEL_PREV = "fake-embed-b"
MODEL_CUR = "fake-embed-c"
GRACE = 7  # the handler's default, in days


@pytest.fixture
def store(tmp_path):
    saved = Store(str(tmp_path / "memory.db"))
    with saved.writer() as conn:
        migrate(conn)
    yield saved, str(tmp_path / "memory.db")
    saved.close()


def _add(conn, content):
    result = MemoryStore(conn).add(
        MemoryDraft(content=content, source="agent"), scope=OWNER, actor="tester"
    )
    assert result.ok, result
    return result.id


def _seed_three_models(store):
    """Memories carrying vectors for models A (old), B (previous), C (current)."""
    saved, _db = store
    ids: list[str] = []
    with saved.transaction() as conn:
        ids.append(_add(conn, "the Acme staging port is 9090"))
        ids.append(_add(conn, "Bob Example waters the fern on Fridays"))
        for model in (MODEL_OLD, MODEL_PREV, MODEL_CUR):
            put_embedding(
                conn,
                owner_id=ids[0],
                model=model,
                vector=(1.0, 0.0, 0.0, 0.0),
                content_hash="hash",
                created_at=to_iso(utc_now()),
            )
    return ids


def _stamp_transition(store, *, current=MODEL_CUR, previous=MODEL_PREV, age_days=8):
    """The transition record a completed backfill would leave behind."""
    saved, _db = store
    with saved.transaction() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("embedding_model", current),
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("embedding_model_previous", previous),
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("embedding_model_switched_at", to_iso(utc_now() - timedelta(days=age_days))),
        )


def _counts(store):
    saved, _db = store
    rows = saved.reader().execute(
        "SELECT model, COUNT(*) AS n FROM embeddings GROUP BY model"
    )
    return {row["model"]: row["n"] for row in rows}


def _enqueue_prune(store, payload=None):
    saved, _db = store
    with saved.transaction() as conn:
        JobQueue(conn).enqueue("prune", dict(payload or {}))


def _run_prune(store, payload=None):
    saved, db_path = store
    _enqueue_prune(store, payload)
    registry = HandlerRegistry()
    registry.register("prune", make_prune_handler(db_path))
    return JobWorker(saved, registry, worker_id="w").run_until_idle()


# --- the core guarantees -----------------------------------------------------


def test_after_the_grace_only_models_beyond_current_and_previous_are_deleted(store):
    _seed_three_models(store)
    _stamp_transition(store, age_days=8)
    outcomes = _run_prune(store)
    assert [o.status for o in outcomes] == ["done"]
    counts = _counts(store)
    assert MODEL_OLD not in counts, "the stale model's rows are gone"
    assert counts == {MODEL_PREV: 1, MODEL_CUR: 1}, "previous and current survive"


def test_inside_the_grace_nothing_is_deleted(store):
    _seed_three_models(store)
    _stamp_transition(store, age_days=3)  # 3 < 7: inside the grace window
    outcomes = _run_prune(store)
    assert [o.status for o in outcomes] == ["done"]
    assert _counts(store) == {MODEL_OLD: 1, MODEL_PREV: 1, MODEL_CUR: 1}


def test_no_current_model_is_a_logged_noop(store, caplog):
    _seed_three_models(store)  # rows exist, but the store claims no model
    with caplog.at_level(logging.INFO, logger="em.embeddings.prune"):
        outcomes = _run_prune(store)
    assert [o.status for o in outcomes] == ["done"]
    assert _counts(store) == {MODEL_OLD: 1, MODEL_PREV: 1, MODEL_CUR: 1}
    assert any("no current model" in r.getMessage().lower() for r in caplog.records)


def test_a_missing_transition_record_is_a_logged_noop(store, caplog):
    _seed_three_models(store)
    with store[0].transaction() as conn:
        set_stored_model(conn, MODEL_CUR)  # completed backfill, but no record
    with caplog.at_level(logging.INFO, logger="em.embeddings.prune"):
        outcomes = _run_prune(store)
    assert [o.status for o in outcomes] == ["done"]
    assert _counts(store) == {MODEL_OLD: 1, MODEL_PREV: 1, MODEL_CUR: 1}
    assert any("transition record" in r.getMessage().lower() for r in caplog.records)

    # The half-record shape is the dangerous one: an old, readable clock with
    # no previous-model identity — a prune would delete the rollback set whose
    # existence it cannot even name.
    with store[0].transaction() as conn:
        conn.execute("DELETE FROM meta WHERE key='embedding_model_previous'")
        conn.execute("DELETE FROM meta WHERE key='embedding_model_switched_at'")
    _stamp_transition(store, current=MODEL_CUR, previous="", age_days=8)
    with caplog.at_level(logging.INFO, logger="em.embeddings.prune"):
        outcomes = _run_prune(store)
    assert [o.status for o in outcomes] == ["done"]
    assert _counts(store) == {MODEL_OLD: 1, MODEL_PREV: 1, MODEL_CUR: 1}, (
        "an unnamed rollback set is never prunable"
    )


def test_dry_run_reports_counts_and_deletes_nothing(store, caplog):
    _seed_three_models(store)
    _stamp_transition(store, age_days=8)
    with caplog.at_level(logging.INFO, logger="em.embeddings.prune"):
        outcomes = _run_prune(store, payload={"dry_run": True})
    assert [o.status for o in outcomes] == ["done"]
    assert _counts(store) == {MODEL_OLD: 1, MODEL_PREV: 1, MODEL_CUR: 1}
    report = max(
        (r.getMessage() for r in caplog.records if "dry-run" in r.getMessage().lower()),
        default="",
    )
    assert MODEL_OLD in report, "the report names the stale model"
    assert "1" in report, "the report carries the per-model row count"


def test_prune_is_idempotent(store):
    _seed_three_models(store)
    _stamp_transition(store, age_days=8)
    first = _run_prune(store)
    second = _run_prune(store)
    assert [o.status for o in first] == ["done"]
    assert [o.status for o in second] == ["done"]
    assert _counts(store) == {MODEL_PREV: 1, MODEL_CUR: 1}


def test_vacuum_runs_only_after_the_delete_commits(store, monkeypatch):
    _seed_three_models(store)
    _stamp_transition(store, age_days=8)
    calls: list[str] = []

    def fake_vacuum(path, check):
        calls.append(path)
        check()  # the delete transaction is already committed at this point

    def check():
        n = store[0].reader().execute(
            "SELECT COUNT(*) AS n FROM embeddings WHERE model=?", (MODEL_OLD,)
        ).fetchone()["n"]
        assert n == 0, "vacuum must follow the committed delete"

    monkeypatch.setattr("em.embeddings.prune._vacuum", fake_vacuum)
    outcomes = _run_prune(store)
    assert [o.status for o in outcomes] == ["done"]
    assert calls == [store[1]]


def test_a_dry_run_never_reaches_vacuum(store, monkeypatch):
    _seed_three_models(store)
    _stamp_transition(store, age_days=8)
    monkeypatch.setattr(
        "em.embeddings.prune._vacuum",
        lambda *a, **k: pytest.fail("a dry run must not vacuum"),
    )
    outcomes = _run_prune(store, payload={"dry_run": True})
    assert [o.status for o in outcomes] == ["done"]


def test_prune_is_only_reachable_through_the_job_registry():
    """The drift guard: no request path imports the prune module."""
    patterns = (
        "embeddings.prune",
        "embeddings import prune",
        "from .prune import",
        "from ..embeddings import prune",
    )
    for path in sorted((SCRIPTS / "em").rglob("*.py")):
        if path.name == "prune.py":
            continue  # the handler's own docstring mentions the registry
        text = path.read_text(encoding="utf-8")
        if any(pat in text for pat in patterns):
            assert path.name == "registry.py", (
                f"{path.name} reaches the prune handler outside the job registry"
            )


# --- the backfill writes the transition record --------------------------------


class _FakeBackend:
    name = "fake"
    dim = 4
    default_model = "fake-embed"

    def available(self) -> bool:
        return True

    def warm(self) -> None:
        pass

    def embed(self, texts):
        return [list(_fake_vector(t)) for t in texts]


def _fake_vector(text: str) -> tuple:
    return (float(sum(text.encode()) % 1000), 1.0, 0.0, 0.0)


def _run_backfill(saved, model: str):
    from em.embeddings.jobs import make_embed_backfill_handler
    from em.embeddings.service import EmbeddingService

    with saved.transaction() as conn:
        JobQueue(conn).enqueue(
            "embed_backfill",
            {"model": model},
            dedupe_key=f"embed_backfill:{model}",
        )
    service = EmbeddingService(
        ":memory:", backend=_FakeBackend(), model=model
    )
    registry = HandlerRegistry()
    registry.register("embed_backfill", make_embed_backfill_handler(service))
    return JobWorker(saved, registry, worker_id="w").run_until_idle()


def test_the_backfill_records_current_previous_and_the_grace_clock(store):
    from em.store.embeddings import stored_model_previous, switched_at

    saved, db_path = store
    with saved.transaction() as conn:
        _add(conn, "the Acme staging port is 9090")
    with saved.transaction() as conn:
        ensure_embedding_model(conn, MODEL_PREV)
    _run_backfill(saved, MODEL_PREV)
    with saved.transaction() as conn:
        ensure_embedding_model(conn, MODEL_CUR)
    _run_backfill(saved, MODEL_CUR)

    reader = saved.reader()
    assert stored_model(reader) == MODEL_CUR
    assert stored_model_previous(reader) == MODEL_PREV, (
        "the completed switch stamps the rollback identity"
    )
    switched = switched_at(reader)
    assert switched and parse_iso(switched) <= utc_now(), (
        "the grace clock is stamped at completion"
    )
    rows = reader.execute("SELECT type, dedupe_key FROM jobs WHERE type='prune'").fetchall()
    assert [(r["type"], r["dedupe_key"]) for r in rows] == [
        ("prune", f"prune:{MODEL_CUR}")
    ], "one dedupe-keyed prune rides the completed switch"


def test_the_registry_and_the_cli_know_prune(store):
    from em.jobs import cli as jobs_cli
    from em.jobs.registry import KNOWN_JOB_TYPES, build_registry

    assert "prune" in KNOWN_JOB_TYPES
    _, db_path = store
    registry = build_registry(db_path, types=("prune",))
    assert registry.get("prune") is not None
    # the CLI's types filter takes KNOWN_JOB_TYPES directly
    assert "prune" in jobs_cli.KNOWN_JOB_TYPES


def test_the_payload_can_carry_a_wider_or_narrower_grace(store):
    _seed_three_models(store)
    _stamp_transition(store, age_days=3)
    outcomes = _run_prune(store, payload={"grace_days": 1})
    assert [o.status for o in outcomes] == ["done"]
    assert MODEL_OLD not in _counts(store), "grace 1 < age 3 lets the prune run"

    _stamp_transition(store, age_days=8)
    outcomes = _run_prune(store, payload={"grace_days": 365})
    assert [o.status for o in outcomes] == ["done"]
    assert _counts(store) == {MODEL_PREV: 1, MODEL_CUR: 1}, "grace 365 keeps everything"

