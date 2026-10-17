"""EM-502 slice 2 — the extraction handlers, the registry, and the scope contract.

The isolation-sensitive claim is here: **the scope a job writes is the scope the
same turn's reads use.** ``transcript_chunks`` carries no scope, so the payload
must carry the provider's effective turn scope (``_turn_scope()`` — profile
``_profile_id or 'default'``), and the handler must refuse a payload without one
rather than guess. A write/read mismatch would be a silent cross-profile leak;
the trap is an empty ``agent_identity`` (``_state.scope.profile == ''`` while
reads use ``'default'``), which is tested explicitly.
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

import pytest  # noqa: E402
from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

from em.facade.engine import V3Engine  # noqa: E402
from em.formation.extract_jobs import (  # noqa: E402
    make_extract_session_handler,
    make_extract_window_handler,
    scope_from_payload,
)
from em.jobs.worker import PermanentJobError  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402

SESSION = "s-em502"
SCOPE_PAYLOAD = {
    "profile": "team-a",
    "user": "",
    "chat": "",
    "chat_type": "",
    "author": "u-alice",
    "is_owner": True,
}


class FakeCtx:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.heartbeats = 0

    def heartbeat(self) -> bool:
        self.heartbeats += 1
        return True


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    V3Engine(db).close()
    return db


def _chunks(db: Path, rows) -> None:
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            for seq, role, author, text in rows:
                conn.execute(
                    "INSERT INTO transcript_chunks"
                    " (digest, session_id, seq, role, author_id, text, ts, captured_at, source)"
                    " VALUES (?,?,?,?,?,?,?,?,'sync_turn')",
                    (f"d{seq}-{role}", SESSION, seq, role, author, text, None,
                     "2026-01-01T00:00:00Z"),
                )
    finally:
        store.close()


def _run(handler, payload, db: Path) -> None:
    store = Store(str(db))
    try:
        handler(SimpleNamespace(payload=payload), FakeCtx(store))
    finally:
        store.close()


def _rows(db: Path):
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            rows = conn.execute(
                "SELECT content, kind, status, scope_profile, scope_user, source_session,"
                " source_turn, confidence, evidence FROM memories ORDER BY rowid"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        store.close()


def _payload(**overrides):
    payload = {
        "session_id": SESSION,
        "seq_start": 1,
        "seq_end": 2,
        "scope": dict(SCOPE_PAYLOAD),
    }
    payload.update(overrides)
    return payload


# --- the handler -------------------------------------------------------------


def test_the_window_handler_writes_pending_candidates_in_the_payload_scope(tmp_path):
    db = _db(tmp_path)
    _chunks(db, [
        (1, "user", "u-alice", "I prefer tea over coffee in the mornings."),
        (2, "assistant", "", "Noted."),
    ])
    _run(make_extract_window_handler(), _payload(), db)

    rows = _rows(db)
    assert len(rows) == 1, rows
    row = rows[0]
    assert "prefer tea over coffee" in row["content"]
    assert row["kind"] == "preference"
    assert row["status"] == "pending"
    assert row["scope_profile"] == "team-a" and row["scope_user"] == ""
    assert row["source_session"] == SESSION and row["source_turn"] == 1
    assert row["evidence"] == row["content"], "the verbatim evidence is stored with the row"


def test_a_missing_scope_is_permanent_and_writes_nothing(tmp_path):
    db = _db(tmp_path)
    _chunks(db, [(1, "user", "u-alice", "I prefer tea over coffee.")])
    payload = _payload()
    payload.pop("scope")
    with pytest.raises(PermanentJobError):
        _run(make_extract_window_handler(), payload, db)
    assert _rows(db) == []
    with pytest.raises(PermanentJobError):
        scope_from_payload({"scope": {"profile": "", "user": ""}})


def test_the_window_handler_is_idempotent(tmp_path):
    db = _db(tmp_path)
    _chunks(db, [(1, "user", "u-alice", "I prefer tea over coffee.")])
    handler = make_extract_window_handler()
    _run(handler, _payload(seq_end=1), db)
    _run(handler, _payload(seq_end=1), db)
    assert len(_rows(db)) == 1, "a retried delivery must converge, not duplicate"


def test_the_session_handler_reads_the_chunks_and_caps_confidence(tmp_path):
    db = _db(tmp_path)
    _chunks(db, [(1, "user", "u-alice", "I use info-level logging for the worker.")])
    _run(
        make_extract_session_handler(),
        {"session_id": SESSION, "source": "extracted_llm", "confidence_cap": 0.5,
         "scope": dict(SCOPE_PAYLOAD)},
        db,
    )
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["confidence"] <= 0.5
    assert rows[0]["status"] == "pending"


def test_a_malformed_window_payload_is_permanent(tmp_path):
    db = _db(tmp_path)
    handler = make_extract_window_handler()
    for payload in (
        _payload(session_id=""),
        _payload(seq_start=2, seq_end=1),
        _payload(seq_start=True),
    ):
        with pytest.raises(PermanentJobError):
            _run(handler, payload, db)


# --- the registry and the provider gate --------------------------------------


def test_the_registry_carries_both_formation_handlers(tmp_path):
    from em.jobs.registry import KNOWN_JOB_TYPES, build_registry

    db = _db(tmp_path)
    registry = build_registry(str(db))
    assert {"extract_window", "extract_session"} <= set(registry.types())
    assert {"extract_window", "extract_session"} <= set(KNOWN_JOB_TYPES)
    assert build_registry(str(db), types=["extract_window"]).types() == ["extract_window"]


def test_the_provider_serializes_the_effective_turn_scope_not_agent_identity(tmp_path):
    """The trap: ``agent_identity`` empty means ``_state.scope.profile == ''``,
    while every read uses ``_profile_id or 'default'``. The payload must carry
    the read profile or the write lands where no read looks."""
    provider = EntropicMemMemoryProvider(config={"core_memory_enabled": False})
    provider.initialize("s-scope", hermes_home=str(tmp_path))
    try:
        assert provider._state.scope.profile == "", "the fixture must exercise the trap"
        assert provider._scope_payload()["profile"] == "default"
    finally:
        provider.shutdown()

    named = EntropicMemMemoryProvider(config={"core_memory_enabled": False})
    named.initialize("s-scope", hermes_home=str(tmp_path), agent_identity="team-a")
    try:
        assert named._scope_payload()["profile"] == "team-a"
    finally:
        named.shutdown()


def test_a_write_and_its_later_read_resolve_to_the_same_scope(tmp_path):
    """**The owner's scope-consistency AC, end to end.**

    The provider serializes its effective turn scope, the handler writes with
    exactly that scope, and the provider's own read scope finds the row.
    """
    db = _db(tmp_path)
    _chunks(db, [(1, "user", "u-alice", "My timezone is Europe/Johannesburg.")])

    provider = EntropicMemMemoryProvider(config={"core_memory_enabled": False})
    provider.initialize("s-consistency", hermes_home=str(tmp_path))
    provider._memory_db = db
    try:
        scope_payload = provider._scope_payload()
        payload = {
            "session_id": SESSION,
            "seq_start": 1,
            "seq_end": 1,
            "scope": scope_payload,
        }
        _run(make_extract_window_handler(), payload, db)

        read_scope = provider._turn_scope()
        assert read_scope is not None
        assert scope_payload["profile"] == read_scope.profile
        store = Store(str(db))
        try:
            with store.transaction() as conn:
                found = MemoryStore(conn).list(scope=read_scope, status=("pending",))
        finally:
            store.close()
    finally:
        provider.shutdown()

    assert len(found) == 1, "the write must be visible to the turn's own read scope"
    assert found[0]["scope_profile"] == read_scope.profile
    assert "timezone is Europe/Johannesburg" in found[0]["content"]
