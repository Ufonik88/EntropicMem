"""EM-411, the capture half: window seals from idle, cadence and compaction.

Three §6.3 behaviours land here:

* **one window, one key.** Every trigger that seals the unsealed transcript
  range — the cadence flush, an idle gap, a compaction — enqueues one
  ``extract_window`` job under the shared dedupe key
  ``extract:window:{session}:{seq_start}-{seq_end}``: a recomputed range (the
  process died between the enqueue and the boundary record) and a retried
  compression collapse onto that one queued row, because the queue is
  idempotent by dedupe key — one key means one row.
* **the idle floor.** A gap under ``formation.idle_after_sec`` is not a seal;
  a sealed window enqueues only when it holds at least
  ``formation.min_window_turns`` turns *or* ``formation.min_window_chars``
  characters — under both floors it enqueues nothing, so "resume and say
  hello" does not spend a job. A floored window is still sealed — its content
  cannot leak into the next window.
* **the gates and the soft edges.** Capture is v3-only and ships inert:
  enqueues happen only when ``formation.mode != "off"`` and this build carries
  an ``extract_window`` handler (it carries none until EM-502 registers one);
  an enqueue failure never fails the checkpoint and still advances the
  boundary, so a dead queue cannot turn into a retry storm.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

import em.jobs  # noqa: E402
import em.provider.provider as surface  # noqa: E402
from em.facade.engine import V3Engine  # noqa: E402
from memory_engine import MemoryEngine  # noqa: E402

SESSION = "sess-em411"
IDLE_AFTER = 60.0
LONG = "x" * 150  # one sync_turn(LONG, LONG) is 300 chars — clears the character floor


# --- fixtures ---------------------------------------------------------------


def _rows(db: Path, sql: str, params: tuple = ()) -> list:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def _v3_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    V3Engine(db).close()
    return db


def _v2_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    MemoryEngine(db, profile_id="default").close()
    return db


def _real_spawn(target, name):
    import threading

    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


class _Clock:
    """A frozen clock; the provider binds ``time`` at module import."""

    def __init__(self, t: float = 1000.0):
        self.t = float(t)

    def time(self) -> float:
        return self.t


def _provider(tmp_path: Path, db: Path, **config) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(config={
        "core_memory_enabled": False,
        "touch_on_inject": False,
        **config,
    })
    provider.initialize(SESSION, hermes_home=str(tmp_path))
    provider._scripts_dir = SCRIPTS
    provider._memory_db = db
    provider._profile_id = "default"
    provider._spawn = _real_spawn
    return provider


def _capture(monkeypatch, tmp_path: Path, db: Path, **config) -> EntropicMemMemoryProvider:
    """A provider with capture explicitly on (handler patched + mode set)."""
    monkeypatch.setattr(
        "em.jobs.BUILT_FORMATION_HANDLERS", frozenset({"extract_window"}), raising=False
    )
    return _provider(
        tmp_path,
        db,
        **{"formation.mode": "realtime", "formation.idle_after_sec": IDLE_AFTER, **config},
    )


def _sync(provider: EntropicMemMemoryProvider, n: int, pad: str = "") -> None:
    for i in range(1, n + 1):
        provider.sync_turn(f"user line {i} {pad}", f"assistant answer {i} {pad}")


def _messages(n: int) -> list:
    out = []
    for i in range(1, n + 1):
        out.append({"role": "user", "content": f"user line {i}"})
        out.append({"role": "assistant", "content": f"assistant answer {i}"})
    return out


def _salient_messages() -> list:
    """Two turns whose markers give ``build_handoff`` something to carry."""
    return [
        {"role": "user", "content": "Always use UTC windows."},
        {"role": "assistant", "content": "Understood — UTC everywhere."},
        {"role": "user", "content": "Never commit on Friday."},
        {"role": "assistant", "content": "Agreed."},
    ]


def _sync_salient(provider: EntropicMemMemoryProvider) -> None:
    provider.sync_turn("Always use UTC windows.", "Understood — UTC everywhere.")
    provider.sync_turn("Never commit on Friday.", "Agreed.")


def _jobs(db: Path) -> list:
    return _rows(
        db,
        "SELECT id, payload, dedupe_key, status FROM jobs WHERE type='extract_window'"
        " ORDER BY rowid",
    )


# --- one window, one key ----------------------------------------------------


def test_three_seal_kinds_over_one_window_enqueue_exactly_one_job(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    provider = _capture(monkeypatch, tmp_path, db)
    try:
        _sync(provider, 2)  # four messages: positions 1-4
        provider._seal_window("cadence")
        provider._seal_window("idle", floor=True)
        provider._seal_window("compaction")
    finally:
        provider.shutdown()

    jobs = _jobs(db)
    assert len(jobs) == 1, "one window, one job — the ledger and the key both collapse"
    assert jobs[0]["dedupe_key"] == f"extract:window:{SESSION}:1-4"
    assert jobs[0]["status"] == "queued"
    payload = json.loads(jobs[0]["payload"])
    assert payload["session_id"] == SESSION
    assert payload["seq_start"] == 1 and payload["seq_end"] == 4
    assert payload["reason"] == "cadence"
    # EM-502 slice 2: the job carries the effective turn scope, not
    # ``agent_identity`` (usually empty) — the write/read consistency contract.
    assert payload["scope"]["profile"] == "default"
    assert payload["scope"]["user"] == ""


def test_a_cadence_flush_seals_the_same_window(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    clock = _Clock()
    monkeypatch.setattr(surface, "time", clock)
    provider = _capture(
        monkeypatch,
        tmp_path,
        db,
        **{"turn_cadence_flush_turns": 1, "turn_cadence_min_interval_sec": 0},
    )
    try:
        provider.on_turn_start(1, "question one")
        _sync(provider, 1, pad=LONG)
        clock.t += 5
        provider.on_turn_start(2, "question two")
        jobs = _jobs(db)
        assert len(jobs) == 1
        assert jobs[0]["dedupe_key"] == f"extract:window:{SESSION}:1-2"
        assert json.loads(jobs[0]["payload"])["reason"] == "cadence"
    finally:
        provider.shutdown()


def test_a_recomputed_window_range_collapses_on_the_shared_key(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    provider = _capture(monkeypatch, tmp_path, db)
    try:
        _sync(provider, 2)
        first = provider._seal_window("compaction")
        assert first == f"extract:window:{SESSION}:1-4"
        # The process died between the enqueue and the boundary record: the
        # next seal recomputes the same range.
        provider._state.window_sealed = 0
        again = provider._seal_window("idle")
    finally:
        provider.shutdown()

    assert again == first
    jobs = _jobs(db)
    assert len(jobs) == 1, "a recomputed range must not open a second row"
    assert jobs[0]["dedupe_key"] == first


def test_a_retried_compression_does_not_enqueue_a_second_extraction(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    provider = _capture(monkeypatch, tmp_path, db)
    messages = _salient_messages()
    try:
        _sync_salient(provider)  # four messages: positions 1-4
        first = provider.on_pre_compress(messages)
        assert first, "the handoff is non-empty"
        second = provider.on_pre_compress(messages)
        assert second == first, "a retry converges on the same handoff"
    finally:
        provider.shutdown()

    jobs = _jobs(db)
    assert len(jobs) == 1
    assert jobs[0]["dedupe_key"] == f"extract:window:{SESSION}:1-4"


def test_the_window_ledger_survives_a_restart_and_continues_the_sequence(
    tmp_path, monkeypatch
):
    db = _v3_db(tmp_path)
    clock = _Clock()
    monkeypatch.setattr(surface, "time", clock)
    monkeypatch.setattr(
        "em.jobs.BUILT_FORMATION_HANDLERS", frozenset({"extract_window"}), raising=False
    )
    cfg = {"formation.mode": "realtime", "formation.idle_after_sec": IDLE_AFTER}

    first = _provider(tmp_path, db, **cfg)
    try:
        first.on_turn_start(1, "question one")
        _sync(first, 2, pad=LONG)
        clock.t += IDLE_AFTER + 1
        first.on_turn_start(2, "question two")
    finally:
        first.shutdown()

    second = _provider(tmp_path, db, **cfg)
    try:
        second.on_turn_start(3, "question three")
        _sync(second, 2, pad=LONG)
        clock.t += IDLE_AFTER + 1
        second.on_turn_start(4, "question four")
    finally:
        second.shutdown()

    assert [j["dedupe_key"] for j in _jobs(db)] == [
        f"extract:window:{SESSION}:1-4",
        f"extract:window:{SESSION}:5-8",
    ], "a restart continues the window sequence; ranges never repeat"


# --- the idle floor ---------------------------------------------------------


def test_an_idle_gap_under_both_floors_enqueues_nothing_and_still_seals(
    tmp_path, monkeypatch
):
    db = _v3_db(tmp_path)
    clock = _Clock()
    monkeypatch.setattr(surface, "time", clock)
    provider = _capture(monkeypatch, tmp_path, db)
    try:
        provider.on_turn_start(1, "hi")
        provider.sync_turn("hi", "hey there")  # one turn, eleven characters
        clock.t += IDLE_AFTER + 1
        provider.on_turn_start(2, "next question")
        assert _jobs(db) == [], "a window under both floors must not burn an extraction"

        # A floored window is sealed anyway: its content cannot leak into
        # the next window's range.
        provider.sync_turn(LONG, LONG)
        clock.t += IDLE_AFTER + 1
        provider.on_turn_start(3, "more")
        assert [j["dedupe_key"] for j in _jobs(db)] == [
            f"extract:window:{SESSION}:3-4"
        ]
    finally:
        provider.shutdown()


def test_the_turn_floor_alone_admits_the_window(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    clock = _Clock()
    monkeypatch.setattr(surface, "time", clock)
    provider = _capture(monkeypatch, tmp_path, db)
    try:
        provider.on_turn_start(1, "hi")
        provider.sync_turn("hi", "hey")  # 2 turns, 5 characters
        provider.sync_turn("ok", "sure")  # 2 turns, 6 characters
        clock.t += IDLE_AFTER + 1
        provider.on_turn_start(2, "next")
        assert [j["dedupe_key"] for j in _jobs(db)] == [
            f"extract:window:{SESSION}:1-4"
        ], "at least min_window_turns turns admits the window on their own"
    finally:
        provider.shutdown()


def test_the_character_floor_alone_admits_the_window(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    clock = _Clock()
    monkeypatch.setattr(surface, "time", clock)
    provider = _capture(monkeypatch, tmp_path, db)
    try:
        provider.on_turn_start(1, "one long message")
        provider.sync_turn("y" * 400, "")  # 1 turn, 400 characters
        clock.t += IDLE_AFTER + 1
        provider.on_turn_start(2, "next")
        assert [j["dedupe_key"] for j in _jobs(db)] == [
            f"extract:window:{SESSION}:1-1"
        ], "at least min_window_chars characters admits the window on their own"
    finally:
        provider.shutdown()


def test_an_idle_gap_meeting_the_floor_seals_the_previous_window(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    clock = _Clock()
    monkeypatch.setattr(surface, "time", clock)
    provider = _capture(monkeypatch, tmp_path, db)
    try:
        provider.on_turn_start(1, "question one")
        _sync(provider, 1, pad=LONG)
        clock.t += IDLE_AFTER + 1
        provider.on_turn_start(2, "question two")
        jobs = _jobs(db)
        assert len(jobs) == 1, "an idle gap past the floor seals exactly one window"
        assert jobs[0]["dedupe_key"] == f"extract:window:{SESSION}:1-2"
        assert json.loads(jobs[0]["payload"])["reason"] == "idle"

        clock.t += IDLE_AFTER + 1
        provider.on_turn_start(3, "question three")
        assert len(_jobs(db)) == 1, "nothing new unsealed means nothing new enqueued"
    finally:
        provider.shutdown()


def test_a_gap_under_the_idle_threshold_does_not_seal(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    clock = _Clock()
    monkeypatch.setattr(surface, "time", clock)
    provider = _capture(monkeypatch, tmp_path, db)
    try:
        provider.on_turn_start(1, "question one")
        _sync(provider, 1, pad=LONG)
        clock.t += IDLE_AFTER - 1
        provider.on_turn_start(2, "question two")
        assert _jobs(db) == []
        clock.t += IDLE_AFTER + 1  # measured from the last turn start
        provider.on_turn_start(3, "question three")
        assert len(_jobs(db)) == 1
    finally:
        provider.shutdown()


# --- the gates --------------------------------------------------------------


def test_capture_is_off_by_default(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    clock = _Clock()
    monkeypatch.setattr(surface, "time", clock)
    monkeypatch.setattr(
        "em.jobs.BUILT_FORMATION_HANDLERS", frozenset({"extract_window"}), raising=False
    )
    provider = _provider(tmp_path, db, **{"formation.idle_after_sec": IDLE_AFTER})
    try:
        provider.on_turn_start(1, "question one")
        _sync(provider, 1, pad=LONG)
        clock.t += IDLE_AFTER + 1
        provider.on_turn_start(2, "question two")
        provider.on_pre_compress(_messages(1))
        assert _jobs(db) == [], "formation.mode ships off until EM-502's caps exist"
    finally:
        provider.shutdown()


def test_a_build_without_the_window_handler_enqueues_nothing(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    # Since EM-502 this build DOES carry the handler, so the "no handler" case
    # is simulated explicitly — the gate, not the default, is what this pins.
    monkeypatch.setattr("em.jobs.BUILT_FORMATION_HANDLERS", frozenset(), raising=False)
    clock = _Clock()
    monkeypatch.setattr(surface, "time", clock)
    provider = _provider(
        tmp_path,
        db,
        **{"formation.mode": "realtime", "formation.idle_after_sec": IDLE_AFTER},
    )
    try:
        provider.on_turn_start(1, "question one")
        _sync(provider, 1, pad=LONG)
        clock.t += IDLE_AFTER + 1
        provider.on_turn_start(2, "question two")
        provider.on_pre_compress(_messages(1))
        assert _jobs(db) == [], "no handler, no enqueue — the queue never fills with unservable work"
    finally:
        provider.shutdown()


def test_the_build_ships_the_em502_window_handler():
    """EM-502 registered both formation handlers, so EM-411's gate now passes.

    Deliberate repoint: this test used to pin the *pre-EM-502* state (an empty
    set). The changed surface's claim is now the opposite — the handlers exist
    and the registry builds them.
    """
    from em.jobs.registry import KNOWN_JOB_TYPES

    assert em.jobs.BUILT_FORMATION_HANDLERS == frozenset(
        {"extract_window", "extract_session"}
    ), "EM-502 ships both formation handlers together with the job types"
    assert {"extract_window", "extract_session"} <= set(KNOWN_JOB_TYPES)


# --- the soft edges ---------------------------------------------------------


def test_an_enqueue_failure_does_not_fail_the_checkpoint(tmp_path, monkeypatch):
    db = _v3_db(tmp_path)
    provider = _capture(monkeypatch, tmp_path, db)

    def boom(*args, **kwargs):
        raise RuntimeError("queue down")

    # The seal's producer itself misbehaves (the store layer has its own
    # fail-soft; the seal must not depend on it).
    monkeypatch.setattr(provider, "_enqueue_job", boom)
    try:
        _sync_salient(provider)
        handoff = provider.on_pre_compress(_salient_messages(), require_checkpoint=True)
        assert handoff, "the checkpoint still returns its handoff"
        assert _jobs(db) == []
        assert provider._seal_window("idle") is None, (
            "the boundary advanced anyway — a dead queue is not a retry storm"
        )
    finally:
        provider.shutdown()


def test_a_v2_store_gains_no_capture(tmp_path, monkeypatch):
    db = _v2_db(tmp_path)
    clock = _Clock()
    monkeypatch.setattr(surface, "time", clock)
    monkeypatch.setattr(
        "em.jobs.BUILT_FORMATION_HANDLERS", frozenset({"extract_window"}), raising=False
    )
    provider = _provider(
        tmp_path,
        db,
        **{"formation.mode": "realtime", "formation.idle_after_sec": IDLE_AFTER},
    )
    try:
        provider.on_turn_start(1, "question one")
        _sync(provider, 1, pad=LONG)
        clock.t += IDLE_AFTER + 1
        provider.on_turn_start(2, "question two")
        provider.on_pre_compress(_messages(1))
    finally:
        provider.shutdown()

    tables = {r["name"] for r in _rows(db, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "jobs" not in tables, "capture is v3-only; a v2 schema gains nothing"
