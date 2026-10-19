"""EM-412 — the query-embedding wiring: one fail-soft seam, three sites.

The card (owner-approved 2026-10-16 with four edits): wire ``embed_query``
at the v3 read sites — the tool search path, ``PrefetchService`` (its async
precompute half) and the facade's flag-on ``recall_with_relevance`` —
reusing the existing optional backends, with a per-call ``openai_compat``
timeout and hard fail-soft to lexical (a raising or timing-out embedder
still returns the lexical result; nothing propagates), a per-session
embed-count log, and stale-model skips logged at debug and exposed in the
search diagnostics.

One group per claim:

* **the seam** — ``QueryEmbedder`` passes vectors through, hard fail-softs
  (raise / timeout / unavailable service), counts, logs the session summary
  only when the session actually embedded, and cuts a stuck backend off at
  its own wall-clock bound (later calls fast-fail until it finishes).
* **the sites** — a fake backend's vector reaches ``retrieve`` at each of
  the three sites, and the LRU snapshot is consulted once per owner type.
* **the flag** — off ⇒ no backend is even selected, no vector is passed, no
  ``diagnostics`` key appears; a failing-but-enabled search returns the
  byte-identical payload.
* **diagnostics** — vectors for another model are skipped, logged at debug
  (``em.retrieval.vectors``) and counted in ``outcome.diagnostics`` and the
  search payload.
* **the backfill** — initialize queues ``embed_backfill`` on a model switch
  (flag on, v3), and queues nothing when off or already recorded.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import json
import logging
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

import em.retrieval.candidates as candidates_mod  # noqa: E402
import em.retrieval.pipeline as pipeline_mod  # noqa: E402
from em.embeddings.cache import reset_cache  # noqa: E402
from em.embeddings.query import QueryEmbedder  # noqa: E402
from em.facade.engine import V3_RETRIEVAL_ENV, V3Engine  # noqa: E402
from em.facade.select import open_engine  # noqa: E402
from em.retrieval.pipeline import retrieve  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.embeddings import put_embedding, set_stored_model  # noqa: E402
from em.store.jobs import JobQueue  # noqa: E402
from em.store.types import Scope  # noqa: E402
from memory_engine import MemoryEngine  # noqa: E402

SESSION = "em412-session"
QUERY = "what port does the staging server use"
STAGING = "the staging server runs on port 9090"
BILLING = "nightly billing job reconciles invoices"
MODEL = "fake-model"
VEC = (1.0, 0.0, 0.0)
OTHER_VEC = (0.0, 1.0, 0.0)
NOW = "2026-10-16T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """§3.8 env and the process-wide vector LRU must not leak across tests."""
    for name in (
        "ENTROPICMEM_MEMORY_DB",
        "ENTROPICMEM_INDEX_DB",
        "ENTROPICMEM_VAULT_PATH",
        "ENTROPICMEM_V3_RETRIEVAL",
        "ENTROPICMEM_EMBEDDINGS_BACKEND",
        "ENTROPICMEM_EMBEDDINGS_BASE_URL",
        "ENTROPICMEM_EMBEDDINGS_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_cache()
    yield
    reset_cache()


# --- harness ----------------------------------------------------------------


class _FakeService:
    """The ``EmbeddingService`` half ``QueryEmbedder`` talks to."""

    def __init__(self, *, vector=VEC, model=MODEL, error=None):
        self.model = model
        self._vector = vector
        self._error = error
        self.calls: list = []

    def embed_query(self, text):
        self.calls.append(text)
        if self._error is not None:
            raise self._error
        if self._vector is None:
            return None
        return list(self._vector)


class _FakeBackend:
    name = "fake"
    default_model = MODEL

    def __init__(self, *, vector, error, calls):
        self._vector = vector
        self._error = error
        self._calls = calls

    def available(self):
        return True

    def warm(self):
        return None

    def embed(self, texts):
        self._calls.extend(texts)
        if self._error is not None:
            raise self._error
        return [list(self._vector) for _ in texts]


def _patch_backend(monkeypatch, *, error=None, vector=VEC) -> list:
    """Route ``EmbeddingService`` construction to a fake backend; return its call log."""
    calls: list = []
    backend = _FakeBackend(vector=vector, error=error, calls=calls)

    def fake_select(preference="auto", *, model=None, env=None):
        return backend

    monkeypatch.setattr("em.embeddings.service.select_backend", fake_select)
    return calls


def _spy_retrieve(monkeypatch) -> dict:
    """Record the kwargs of the next ``pipeline.retrieve`` calls."""
    captured: dict = {}
    real = pipeline_mod.retrieve

    def spy(conn, *, scope, query, **kwargs):
        captured.clear()
        captured.update(kwargs)
        return real(conn, scope=scope, query=query, **kwargs)

    monkeypatch.setattr(pipeline_mod, "retrieve", spy)
    return captured


def _v3_db(tmp_path: Path, *, extra_memory: bool = False) -> Path:
    db = tmp_path / "memory.db"
    engine = V3Engine(db)
    engine.remember(STAGING, domain="Infrastructure", importance=0.8)
    if extra_memory:
        engine.remember(BILLING, domain="Operations", importance=0.5)
    engine.close()
    return db


def _memory_id(db: Path, content: str) -> str:
    store = Store(str(db))
    try:
        row = store.reader().execute(
            "SELECT id FROM memories WHERE content = ?", (content,)
        ).fetchone()
        assert row is not None, f"no memory with content {content!r}"
        return str(row["id"])
    finally:
        store.close()


def _seed_embedding(db: Path, owner_id: str, model: str, vector) -> None:
    store = Store(str(db))
    try:
        with store.writer() as conn:
            put_embedding(
                conn,
                owner_id=owner_id,
                model=model,
                vector=list(vector),
                content_hash="",
                created_at=NOW,
            )
    finally:
        store.close()


def _home_config(tmp_path: Path, *, memory_db: Path, embeddings=None, jobs=None) -> None:
    """``$HERMES_HOME/entropicmem/config.json`` — §3.8's dashboard source."""
    path = tmp_path / "entropicmem" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"paths": {"memory_db": str(memory_db)}, "jobs": jobs or {}}
    if embeddings is not None:
        payload["embeddings"] = embeddings
    path.write_text(json.dumps(payload), encoding="utf-8")


def _provider(tmp_path: Path):
    """One provider over the tmp hermes home, with a real ``_spawn``."""
    provider = EntropicMemMemoryProvider(
        config={"core_memory_enabled": False, "touch_on_inject": False}
    )

    def spawn(target, name):
        threading.Thread(target=target, name=name, daemon=True).start()

    provider._spawn = spawn
    provider.initialize(
        SESSION,
        hermes_home=str(tmp_path),
        agent_context="primary",
        agent_identity="default",
    )
    return provider


# --- the seam ---------------------------------------------------------------


def test_query_embedder_passes_the_vector_through_and_counts():
    service = _FakeService()
    embedder = QueryEmbedder(service, session_id="s1")
    assert embedder("hello") == [1.0, 0.0, 0.0]
    assert (embedder.calls, embedder.embedded, embedder.failed) == (1, 1, 0)
    assert embedder.model == MODEL


def test_query_embedder_fails_soft_when_the_service_raises(caplog):
    embedder = QueryEmbedder(_FakeService(error=RuntimeError("backend down")))
    with caplog.at_level(logging.DEBUG, logger="em.embeddings.query"):
        assert embedder("hello") is None
    assert (embedder.calls, embedder.embedded, embedder.failed) == (1, 0, 1)
    assert any("backend down" in record.getMessage() for record in caplog.records)


def test_query_embedder_none_from_the_service_is_not_a_failure():
    embedder = QueryEmbedder(_FakeService(vector=None))
    assert embedder("hello") is None
    assert (embedder.calls, embedder.embedded, embedder.failed) == (1, 0, 0)


def test_query_embedder_session_summary_profiles_paid_usage(caplog):
    embedder = QueryEmbedder(_FakeService(), session_id="s9")
    embedder.log_summary()
    assert not [r for r in caplog.records if "query embeddings" in r.getMessage()]
    assert embedder("hello") == [1.0, 0.0, 0.0]
    with caplog.at_level(logging.INFO, logger="em.embeddings.query"):
        embedder.log_summary()
    lines = [
        r.getMessage()
        for r in caplog.records
        if "query embeddings this session" in r.getMessage()
    ]
    assert lines and "1 call(s)" in lines[-1] and "s9" in lines[-1]


class _BlockingService:
    """An embed that starts (recorded) and then never returns until released."""

    def __init__(self):
        self.started = 0
        self.started_event = threading.Event()
        self.release = threading.Event()

    def embed_query(self, text):
        self.started += 1
        self.started_event.set()
        self.release.wait(timeout=10.0)
        return [1.0, 0.0, 0.0]


def _wait_out_the_stuck_thread(embedder, timeout=5.0):
    """After ``release`` is set: wait until the stuck daemon thread exits."""
    deadline = time.monotonic() + timeout
    thread = embedder._inflight
    while thread is not None and thread.is_alive():
        assert time.monotonic() < deadline, "the released embed thread did not finish"
        time.sleep(0.01)


def test_a_stuck_embed_is_cut_off_at_the_seam_bound():
    """The seam's own clock: a backend that ships without one is still bounded."""
    service = _BlockingService()
    embedder = QueryEmbedder(service, session_id="s1", timeout_s=0.2)
    try:
        started = time.monotonic()
        assert embedder("hello") is None
        elapsed = time.monotonic() - started
    finally:
        service.release.set()
    assert service.started_event.wait(timeout=5.0), "the embed ran on the seam thread"
    assert service.started == 1
    assert (embedder.calls, embedder.embedded, embedder.failed) == (1, 0, 1)
    assert elapsed >= 0.15, "the cut-off waited for the bound"
    assert elapsed < 5.0, "and it was bounded, not hung"
    _wait_out_the_stuck_thread(embedder)


def test_a_call_while_a_stuck_embed_runs_fast_fails_and_recovers():
    service = _BlockingService()
    embedder = QueryEmbedder(service, session_id="s1", timeout_s=0.5)
    try:
        assert embedder("hello") is None  # the first call pays the bound
        started = time.monotonic()
        assert embedder("hello") is None  # the second must not queue behind it
        assert time.monotonic() - started < 0.4
    finally:
        service.release.set()
    assert service.started == 1, "the second call never reached the backend"
    assert (embedder.calls, embedder.embedded, embedder.failed) == (2, 0, 2)
    _wait_out_the_stuck_thread(embedder)
    assert embedder("hello") == [1.0, 0.0, 0.0], "a released backend embeds again"
    assert (embedder.calls, embedder.embedded, embedder.failed) == (3, 1, 2)


def test_the_seam_bound_defaults_to_the_openai_compat_per_call_timeout():
    from em.embeddings.backends import OpenAICompatBackend

    backend = OpenAICompatBackend("http://127.0.0.1:9")
    assert QueryEmbedder(_FakeService()).timeout_s == backend.timeout == 20.0


def test_openai_compat_timeout_is_per_call_and_fails_soft(monkeypatch, tmp_path):
    from em.embeddings.backends import OpenAICompatBackend
    from em.embeddings.service import EmbeddingService

    seen: dict = {}

    def fake_urlopen(request, timeout=None):
        seen["timeout"] = timeout
        raise socket.timeout("timed out")

    monkeypatch.setattr("em.embeddings.backends.open_validated", fake_urlopen)
    backend = OpenAICompatBackend(base_url="http://127.0.0.1:9", model=MODEL, timeout=0.25)
    service = EmbeddingService(str(tmp_path / "emb.db"), backend=backend)
    embedder = QueryEmbedder(service, session_id="s1")
    assert embedder("hello") is None
    assert embedder.failed == 1
    assert seen["timeout"] == 0.25


# --- the tool search site ---------------------------------------------------


def test_tool_search_embeds_the_query_and_exposes_diagnostics(tmp_path, monkeypatch, caplog):
    db = _v3_db(tmp_path, extra_memory=True)
    _seed_embedding(db, _memory_id(db, STAGING), MODEL, VEC)
    _seed_embedding(db, _memory_id(db, BILLING), "other-model", OTHER_VEC)
    _home_config(
        tmp_path,
        memory_db=db,
        embeddings={"enabled": True, "backend": "auto", "model": MODEL},
        jobs={"run_in_primary": False},
    )
    calls = _patch_backend(monkeypatch)
    captured = _spy_retrieve(monkeypatch)
    lru_calls: list = []
    real_cached = candidates_mod.cached_vectors

    def spy_cached(conn, **kwargs):
        lru_calls.append(kwargs.get("owner_type"))
        return real_cached(conn, **kwargs)

    monkeypatch.setattr(candidates_mod, "cached_vectors", spy_cached)
    provider = _provider(tmp_path)
    try:
        with caplog.at_level(logging.DEBUG, logger="em.retrieval.vectors"):
            raw = provider.handle_tool_call(
                "entropicmem_search", {"query": QUERY, "sources": ["memories"]}
            )
        payload = json.loads(raw)
        assert payload["ok"] is True
        assert [row["id"] for row in payload["results"]] == [_memory_id(db, STAGING)]
        assert calls == [QUERY]
        assert captured["query_vector"] == [1.0, 0.0, 0.0]
        assert captured["embedding_model"] == MODEL
        diagnostics = payload["diagnostics"]["vector"]["memory"]
        assert diagnostics["model"] == MODEL
        assert diagnostics["other_model_skipped"] == 1
        assert diagnostics["usable"] == 1 and diagnostics["active"] == 2
        assert lru_calls.count("memory") == 1
        assert any("another model" in r.getMessage() for r in caplog.records)
        assert "warnings" not in payload
        engine = provider._open_engine()
        try:
            assert engine._embed_query is provider._query_embedder()
        finally:
            engine.close()
    finally:
        provider.shutdown()


def test_prefetch_service_gets_the_seam_and_embeds_in_its_worker(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    _home_config(
        tmp_path,
        memory_db=db,
        embeddings={"enabled": True, "backend": "auto", "model": MODEL},
        jobs={"run_in_primary": False},
    )
    calls = _patch_backend(monkeypatch)
    provider = _provider(tmp_path)
    try:
        service = provider._ensure_prefetch_service()
        assert service is not None
        scope = provider._state.scope.to_scope()
        handle = service.queue_precompute(QUERY, session_id=SESSION, scope=scope)
        assert handle.done.wait(timeout=5.0)
        pool = service.candidate_pool(SESSION, scope)
        assert pool is not None
        assert pool["query_vector"] == [1.0, 0.0, 0.0]
        assert calls == [QUERY]
    finally:
        provider.shutdown()


# --- the facade site --------------------------------------------------------


def test_facade_recall_passes_the_embedded_vector(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    _seed_embedding(db, _memory_id(db, STAGING), MODEL, VEC)
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    captured = _spy_retrieve(monkeypatch)
    service = _FakeService()
    engine = V3Engine(
        db, embed_query=QueryEmbedder(service, session_id="s1"), embedding_model=MODEL
    )
    try:
        facts = engine.recall_with_relevance(QUERY)
        assert service.calls == [QUERY]
        assert captured["query_vector"] == [1.0, 0.0, 0.0]
        assert captured["embedding_model"] == MODEL
        assert [fact.content for fact in facts] == [STAGING]
    finally:
        engine.close()


def test_open_engine_forwards_the_seam_and_v2_ignores_it(tmp_path):
    v3 = _v3_db(tmp_path)
    embedder = QueryEmbedder(_FakeService())
    engine = open_engine(v3, embed_query=embedder, embedding_model=MODEL)
    try:
        assert engine._embed_query is embedder
        assert engine._embedding_model == MODEL
    finally:
        engine.close()
    v2_db = tmp_path / "v2.db"
    MemoryEngine(str(v2_db)).close()
    with open_engine(v2_db, embed_query=embedder, embedding_model=MODEL) as engine:
        assert isinstance(engine, MemoryEngine)


# --- the flag ---------------------------------------------------------------


def test_flag_off_never_selects_a_backend_and_a_failing_run_is_byte_identical(
    tmp_path, monkeypatch
):
    db = _v3_db(tmp_path)
    _home_config(
        tmp_path,
        memory_db=db,
        embeddings={"enabled": False},
        jobs={"run_in_primary": False},
    )
    selections: list = []

    def fake_select(preference="auto", *, model=None, env=None):
        selections.append(preference)
        raise AssertionError("no backend may be selected with the flag off")

    monkeypatch.setattr("em.embeddings.service.select_backend", fake_select)
    provider = _provider(tmp_path)
    try:
        assert provider._query_embedder() is None
        off_raw = provider.handle_tool_call(
            "entropicmem_search", {"query": QUERY, "sources": ["memories"]}
        )
        assert "diagnostics" not in json.loads(off_raw)
        assert selections == []
    finally:
        provider.shutdown()

    # A failing-but-enabled embedder over the same store returns the same bytes.
    _home_config(
        tmp_path,
        memory_db=db,
        embeddings={"enabled": True, "model": MODEL},
        jobs={"run_in_primary": False},
    )
    _patch_backend(monkeypatch, error=RuntimeError("backend down"))
    provider = _provider(tmp_path)
    try:
        on_raw = provider.handle_tool_call(
            "entropicmem_search", {"query": QUERY, "sources": ["memories"]}
        )
        assert "diagnostics" not in json.loads(on_raw)
        assert on_raw == off_raw
    finally:
        provider.shutdown()


def test_a_raising_embedder_still_returns_the_lexical_result(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    _home_config(
        tmp_path,
        memory_db=db,
        embeddings={"enabled": True, "model": MODEL},
        jobs={"run_in_primary": False},
    )
    calls = _patch_backend(monkeypatch, error=RuntimeError("backend down"))
    captured = _spy_retrieve(monkeypatch)
    provider = _provider(tmp_path)
    try:
        payload = json.loads(
            provider.handle_tool_call(
                "entropicmem_search", {"query": QUERY, "sources": ["memories"]}
            )
        )
        assert payload["ok"] is True
        assert "warnings" not in payload
        assert [row["id"] for row in payload["results"]] == [_memory_id(db, STAGING)]
        assert captured["query_vector"] is None
        assert calls == [QUERY]
    finally:
        provider.shutdown()


# --- diagnostics at the pipeline level --------------------------------------


def test_pipeline_diagnostics_expose_other_model_skips(tmp_path, caplog):
    db = _v3_db(tmp_path, extra_memory=True)
    _seed_embedding(db, _memory_id(db, STAGING), MODEL, VEC)
    _seed_embedding(db, _memory_id(db, BILLING), "other-model", OTHER_VEC)
    store = Store(str(db))
    try:
        with caplog.at_level(logging.DEBUG, logger="em.retrieval.vectors"):
            outcome = retrieve(
                store.reader(),
                scope=Scope(profile="default"),
                query=QUERY,
                query_vector=list(VEC),
                embedding_model=MODEL,
                with_gate=False,
            )
    finally:
        store.close()
    assert outcome.diagnostics["vector"]["memory"] == {
        "model": MODEL,
        "coverage": 0.5,
        "usable": 1,
        "active": 2,
        "stale_excluded": 0,
        "other_model_skipped": 1,
    }
    assert any("another model" in r.getMessage() for r in caplog.records)
    store = Store(str(db))
    try:
        outcome = retrieve(store.reader(), scope=Scope(profile="default"), query=QUERY)
    finally:
        store.close()
    assert outcome.diagnostics == {}


# --- the backfill -----------------------------------------------------------


def _backfill_job(db: Path):
    store = Store(str(db))
    try:
        with store.writer() as conn:
            return JobQueue(conn).get_by_key(f"embed_backfill:{MODEL}")
    finally:
        store.close()


def test_initialize_queues_the_model_switch_backfill(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    _home_config(
        tmp_path,
        memory_db=db,
        embeddings={"enabled": True, "model": MODEL},
        jobs={"run_in_primary": False},
    )
    _patch_backend(monkeypatch)
    provider = _provider(tmp_path)
    try:
        job = _backfill_job(db)
        assert job is not None
        assert job.payload.get("model") == MODEL
    finally:
        provider.shutdown()


def test_backfill_is_not_queued_when_off_or_already_recorded(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    store = Store(str(db))
    try:
        with store.writer() as conn:
            set_stored_model(conn, MODEL)
    finally:
        store.close()
    _home_config(
        tmp_path,
        memory_db=db,
        embeddings={"enabled": True, "model": MODEL},
        jobs={"run_in_primary": False},
    )
    _patch_backend(monkeypatch)
    provider = _provider(tmp_path)
    try:
        assert _backfill_job(db) is None
    finally:
        provider.shutdown()

    db2 = tmp_path / "off"
    db2.mkdir()
    engine = V3Engine(db2 / "memory.db")
    engine.remember(STAGING, importance=0.5)
    engine.close()
    _home_config(
        tmp_path,
        memory_db=db2 / "memory.db",
        embeddings={"enabled": False},
        jobs={"run_in_primary": False},
    )
    provider = _provider(tmp_path)
    try:
        assert _backfill_job(db2 / "memory.db") is None
    finally:
        provider.shutdown()


# --- the session summary ----------------------------------------------------


def test_session_close_logs_the_embed_count(tmp_path, monkeypatch, caplog):
    db = _v3_db(tmp_path)
    _home_config(
        tmp_path,
        memory_db=db,
        embeddings={"enabled": True, "model": MODEL},
        jobs={"run_in_primary": False},
    )
    _patch_backend(monkeypatch)
    provider = _provider(tmp_path)
    provider.handle_tool_call("entropicmem_search", {"query": QUERY, "sources": ["memories"]})
    with caplog.at_level(logging.INFO, logger="em.embeddings.query"):
        provider.shutdown()
    lines = [
        r.getMessage()
        for r in caplog.records
        if "query embeddings this session" in r.getMessage()
    ]
    assert lines and "1 call(s)" in lines[-1] and SESSION in lines[-1]
