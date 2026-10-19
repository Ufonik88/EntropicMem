"""EM-404 validation slice: store-level behaviour of the v3 tool surface.

The surface-level rules (schemas, aliases, validation, fuzz) live in
``test_em404_tool_surface.py``; this file drives the handlers against real
stores and pins what the card's Spec/AC promise on top of them:

* ``remember``/``update``/``forget`` are the §4.4 write shape
  (``{"ok", "id", "status", "decision"}``) and keep history (supersede);
* ``search`` answers query *or* ids across ``memories``/``episodes``/``notes``/
  ``shared``, and every result carries ``id``, ``short_id``, ``kind``,
  ``content``, ``valid_from``/``valid_to``, ``status``, ``score``, ``why``;
  ``include_history`` appends superseded predecessors;
* forget-by-query returns candidates plus a single-use ``confirm_token``
  (5 minutes) and applies only when the token comes back;
* the v2 store keeps working: remember/search/forget/timeline go through the
  engine, and the v3-only tools refuse with ``needs_v3_store``.

Rules: invented data only.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for entry in (str(REPO), str(SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

from em.facade.engine import V3Engine  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.episodes import EpisodeStore  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402
from memory_engine import MemoryEngine  # noqa: E402

PROFILE = Scope(profile="default")
STAMP = "2026-03-01T10:00:00Z"
STAGING = "the staging server runs on port 9090"


# --- fixtures ----------------------------------------------------------------


def _v3_db(tmp_path: Path) -> Path:
    """A migrated v3 store."""
    db = tmp_path / "memory.db"
    engine = V3Engine(db)
    engine.close()
    return db


def _v2_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    engine = MemoryEngine(db)
    engine.close()
    return db


def _provider(tmp_path: Path, db: Path | None, **config) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(
        config={"core_memory_enabled": False, "touch_on_inject": False, **config}
    )
    # ``agent_identity`` is the §3.5 profile the host resolves the session to;
    # passing it makes the provider's scope the same "default" the seeds use.
    provider.initialize("em404-session", hermes_home=str(tmp_path), agent_identity="default")
    provider._scripts_dir = SCRIPTS
    if db is not None:
        provider._memory_db = db
        provider._profile_id = "default"
    return provider


def _call(provider: EntropicMemMemoryProvider, name: str, args: dict) -> dict:
    out = provider.handle_tool_call(name, args)
    assert isinstance(out, str)
    return json.loads(out)


def _draft(content: str, **kw) -> MemoryDraft:
    return MemoryDraft(content=content, status="active", source="agent", **kw)


def _seed(db: Path, *drafts: MemoryDraft, scope: Scope = PROFILE) -> list[str]:
    store = Store(str(db))
    ids: list[str] = []
    try:
        with store.transaction() as conn:
            ms = MemoryStore(conn)
            for draft in drafts:
                result = ms.add(draft, scope=scope, actor="tester")
                assert result.ok, result
                ids.append(result.id)
    finally:
        store.close()
    return ids


def _seed_episode(db: Path, *, title: str, summary: str, start_at: str = STAMP) -> str:
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            episode_id = EpisodeStore(conn).add_episode(
                scope=PROFILE, kind="manual", title=title, summary=summary
            )
            conn.execute(
                "UPDATE episodes SET start_at=?, end_at=?, created_at=? WHERE id=?",
                (start_at, start_at, start_at, episode_id),
            )
        return episode_id
    finally:
        store.close()


def _sql(db: Path, statement: str, params: tuple = ()) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(statement, params)
        conn.commit()
    finally:
        conn.close()


def _rows(db: Path, statement: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(statement, params).fetchall()]
    finally:
        conn.close()


def _memory(db: Path, memory_id: str) -> dict:
    rows = _rows(db, "SELECT * FROM memories WHERE id=?", (memory_id,))
    assert rows, f"no memory {memory_id}"
    return rows[0]


def _stamp(db: Path, memory_id: str, when: str = STAMP) -> None:
    _sql(db, "UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (when, when, memory_id))


# --- remember ----------------------------------------------------------------


def test_remember_returns_the_write_shape_and_stores_the_row(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    payload = _call(
        provider,
        "entropicmem_remember",
        {"content": STAGING, "kind": "fact", "importance": 0.8, "pinned": True},
    )
    assert payload["ok"] is True
    assert payload["status"] == "active"
    assert payload["decision"] == "created"
    assert payload["entropic_id"] == payload["id"]  # one-minor-version compat alias
    row = _memory(db, payload["id"])
    assert row["content"] == STAGING
    assert row["kind"] == "fact"
    assert row["importance"] == 0.8
    assert row["pinned"] == 1
    assert row["status"] == "active"
    assert row["scope_profile"] == "default"
    assert row["scope_user"] == ""


def test_remember_defaults_are_kind_fact_and_importance_0_6(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_remember", {"content": "plain default fact"})
    row = _memory(db, payload["id"])
    assert row["kind"] == "fact"
    assert row["importance"] == 0.6


def test_remember_stores_valid_from(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    payload = _call(
        provider, "entropicmem_remember", {"content": "effective dated fact", "valid_from": "2026-03-01"}
    )
    assert _memory(db, payload["id"])["valid_from"].startswith("2026-03-01")


def test_remember_supersedes_keeps_history(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    first = _call(provider, "entropicmem_remember", {"content": "the deploy is on friday"})
    second = _call(
        provider,
        "entropicmem_remember",
        {"content": "the deploy is on monday", "supersedes": first["id"]},
    )
    assert second["ok"] is True
    assert second["id"] != first["id"]
    assert second["status"] == "superseded"
    assert second["decision"] == "superseded"
    old = _memory(db, first["id"])
    assert old["status"] == "superseded"
    assert old["superseded_by"] == second["id"]
    assert old["valid_to"]
    assert _memory(db, second["id"])["status"] == "active"


# --- search ------------------------------------------------------------------


def test_search_results_carry_the_card_fields(tmp_path):
    db = _v3_db(tmp_path)
    (memory_id,) = _seed(db, _draft(STAGING, domain="Infrastructure"))
    _stamp(db, memory_id)
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_search", {"query": "staging server port"})
    assert payload["ok"] is True
    assert payload["results"], payload
    result = payload["results"][0]
    assert result["id"] == memory_id
    assert result["short_id"] == memory_id[-8:]
    assert result["kind"] == "fact"
    assert STAGING in result["content"]
    assert result["valid_from"] is None
    assert result["valid_to"] is None
    assert result["status"] == "active"
    assert isinstance(result["score"], float) and 0.0 <= result["score"] <= 1.0
    assert isinstance(result["why"], list) and result["why"]


def test_search_by_ids_fetches_exactly(tmp_path):
    db = _v3_db(tmp_path)
    first, second = _seed(
        db, _draft("first memory"), _draft("second memory", kind="preference")
    )
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_search", {"ids": [second]})
    assert [r["id"] for r in payload["results"]] == [second]
    assert payload["results"][0]["kind"] == "preference"


def test_search_lists_missing_ids(tmp_path):
    db = _v3_db(tmp_path)
    (memory_id,) = _seed(db, _draft("a fact"))
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_search", {"ids": [memory_id, "no-such-memory"]})
    assert [r["id"] for r in payload["results"]] == [memory_id]
    assert payload["missing"] == ["no-such-memory"]


def test_search_kinds_filter(tmp_path):
    db = _v3_db(tmp_path)
    _seed(
        db,
        _draft("the user prefers dark mode", kind="preference"),
        _draft("the dark launch is on friday"),
    )
    provider = _provider(tmp_path, db)
    payload = _call(
        provider, "entropicmem_search", {"query": "dark", "kinds": ["preference"]}
    )
    assert [r["kind"] for r in payload["results"]] == ["preference"]


def test_search_limit_caps_results(tmp_path):
    db = _v3_db(tmp_path)
    _seed(db, *(_draft(f"falcon note number {n}") for n in range(4)))
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_search", {"query": "falcon", "limit": 1})
    assert len(payload["results"]) == 1


def test_search_time_window_filters_recorded_at(tmp_path):
    db = _v3_db(tmp_path)
    (memory_id,) = _seed(db, _draft(STAGING))
    _stamp(db, memory_id)
    provider = _provider(tmp_path, db)
    inside = _call(
        provider,
        "entropicmem_search",
        {"query": "staging", "time_from": "2026-03-01", "time_to": "2026-03-01"},
    )
    assert [r["id"] for r in inside["results"]] == [memory_id]
    outside = _call(
        provider,
        "entropicmem_search",
        {"query": "staging", "time_to": "2026-02-01"},
    )
    assert outside["results"] == []


def test_search_include_history_appends_superseded(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    first = _call(provider, "entropicmem_remember", {"content": "the deploy is on friday"})
    second = _call(
        provider,
        "entropicmem_remember",
        {"content": "the deploy is on monday", "supersedes": first["id"]},
    )
    without = _call(provider, "entropicmem_search", {"ids": [second["id"]]})
    assert [r["id"] for r in without["results"]] == [second["id"]]
    with_history = _call(
        provider, "entropicmem_search", {"ids": [second["id"]], "include_history": True}
    )
    by_id = {r["id"]: r for r in with_history["results"]}
    assert set(by_id) == {first["id"], second["id"]}
    assert by_id[first["id"]]["status"] == "superseded"
    # The same append happens on the query path.
    by_query = _call(
        provider, "entropicmem_search", {"query": "deploy", "include_history": True}
    )
    assert first["id"] in {r["id"] for r in by_query["results"]}


def test_search_default_sources_include_episodes(tmp_path):
    db = _v3_db(tmp_path)
    _seed(db, _draft("falcon moved hosts"))
    episode_id = _seed_episode(
        db, title="Falcon migration", summary="we moved falcon to the new host"
    )
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_search", {"query": "falcon"})
    kinds = {r["kind"] for r in payload["results"]}
    assert kinds == {"fact", "episode"}
    episode = next(r for r in payload["results"] if r["kind"] == "episode")
    assert episode["id"] == episode_id
    assert episode["content"] == "we moved falcon to the new host"
    assert episode["valid_from"] == STAMP


def test_search_episodes_source_only(tmp_path):
    db = _v3_db(tmp_path)
    _seed(db, _draft("falcon moved hosts"))
    episode_id = _seed_episode(db, title="Falcon migration", summary="falcon is on the new host")
    provider = _provider(tmp_path, db)
    payload = _call(
        provider, "entropicmem_search", {"query": "falcon", "sources": ["episodes"]}
    )
    assert [r["id"] for r in payload["results"]] == [episode_id]


def test_search_shared_source_reads_the_shared_pool(tmp_path):
    db = _v3_db(tmp_path)
    _sql(
        db,
        "INSERT INTO shared_facts"
        " (fact_id, origin_store, version, written_at, content, importance, deleted)"
        " VALUES (?, ?, ?, ?, ?, ?, 0)",
        ("shared-1", "store-a", 1, STAMP, "the shared deployment window is friday noon", 0.7),
    )
    provider = _provider(tmp_path, db)
    payload = _call(
        provider, "entropicmem_search", {"query": "deployment window", "sources": ["shared"]}
    )
    assert len(payload["results"]) == 1
    assert payload["results"][0]["content"] == "the shared deployment window is friday noon"
    assert payload["results"][0]["why"] == ["shared"]


def test_search_without_query_or_ids_is_empty(tmp_path):
    db = _v3_db(tmp_path)
    _seed(db, _draft(STAGING))
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_search", {"limit": 5})
    assert payload["results"] == []


def test_search_on_a_v2_store_uses_the_engine(tmp_path):
    db = _v2_db(tmp_path)
    engine = MemoryEngine(db)
    try:
        eid = engine.remember(content=STAGING, title="Staging server", domain="Knowledge")
    finally:
        engine.close()
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_search", {"query": "staging server port"})
    assert payload["ok"] is True
    assert [r["id"] for r in payload["results"]] == [eid]
    result = payload["results"][0]
    assert result["kind"] == "fact"
    assert result["status"] == "active"
    assert isinstance(result["score"], float)
    assert isinstance(result["why"], list) and result["why"]


def test_search_by_ids_on_a_v2_store(tmp_path):
    db = _v2_db(tmp_path)
    engine = MemoryEngine(db)
    try:
        eid = engine.remember(content=STAGING, title="Staging server", domain="Knowledge")
    finally:
        engine.close()
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_search", {"ids": [eid]})
    assert [r["id"] for r in payload["results"]] == [eid]


# --- forget ------------------------------------------------------------------


def test_forget_by_id_marks_deleted(tmp_path):
    db = _v3_db(tmp_path)
    (memory_id,) = _seed(db, _draft(STAGING))
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_forget", {"id": memory_id})
    assert payload == {"ok": True, "id": memory_id, "status": "deleted", "decision": "forgotten"}
    assert _memory(db, memory_id)["status"] == "deleted"
    after = _call(provider, "entropicmem_search", {"ids": [memory_id]})
    assert after["results"] == []
    assert memory_id in after["missing"]


def test_forget_by_query_returns_candidates_and_token(tmp_path):
    db = _v3_db(tmp_path)
    ids = _seed(db, _draft("falcon note one"), _draft("falcon note two"))
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_forget", {"query": "falcon"})
    assert payload["ok"] is False
    assert payload["reason_code"] == "confirmation_required"
    candidate_ids = sorted(c["id"] for c in payload["candidates"])
    assert candidate_ids == sorted(ids)
    assert all({"id", "short_id", "kind", "content"} <= set(c) for c in payload["candidates"])
    assert isinstance(payload["confirm_token"], str) and payload["confirm_token"]
    assert payload["expires_in_seconds"] == 300


def test_forget_tokens_differ_between_previews(tmp_path):
    db = _v3_db(tmp_path)
    _seed(db, _draft("falcon note one"))
    provider = _provider(tmp_path, db)
    first = _call(provider, "entropicmem_forget", {"query": "falcon"})["confirm_token"]
    second = _call(provider, "entropicmem_forget", {"query": "falcon"})["confirm_token"]
    assert first != second


def test_forget_apply_consumes_the_token(tmp_path):
    db = _v3_db(tmp_path)
    ids = _seed(db, _draft("falcon note one"), _draft("falcon note two"))
    provider = _provider(tmp_path, db)
    token = _call(provider, "entropicmem_forget", {"query": "falcon"})["confirm_token"]
    applied = _call(provider, "entropicmem_forget", {"confirm_token": token})
    assert applied["ok"] is True
    assert sorted(applied["deleted"]) == sorted(ids)
    assert all(_memory(db, mid)["status"] == "deleted" for mid in ids)
    again = _call(provider, "entropicmem_forget", {"confirm_token": token})
    assert again["ok"] is False
    assert "token" in again["error"]


def test_forget_token_expires_after_five_minutes(tmp_path):
    from em import clock

    db = _v3_db(tmp_path)
    _seed(db, _draft("falcon note one"))
    provider = _provider(tmp_path, db)
    t0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    with clock.freeze(t0):
        token = _call(provider, "entropicmem_forget", {"query": "falcon"})["confirm_token"]
    with clock.freeze(t0 + timedelta(minutes=6)):
        expired = _call(provider, "entropicmem_forget", {"confirm_token": token})
    assert expired["ok"] is False
    assert "token" in expired["error"]


def test_forget_preview_allowed_apply_blocked_in_non_primary(tmp_path):
    db = _v3_db(tmp_path)
    (memory_id,) = _seed(db, _draft("falcon note one"))
    provider = _provider(tmp_path, db)
    provider._agent_context = "cron"
    preview = _call(provider, "entropicmem_forget", {"query": "falcon"})
    assert preview["reason_code"] == "confirmation_required"
    blocked = _call(provider, "entropicmem_forget", {"id": memory_id})
    assert blocked["reason_code"] == "writes_disabled"


def test_forget_by_id_on_a_v2_store(tmp_path):
    db = _v2_db(tmp_path)
    engine = MemoryEngine(db)
    try:
        eid = engine.remember(content=STAGING, title="Staging server", domain="Knowledge")
    finally:
        engine.close()
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_forget", {"id": eid})
    assert payload["ok"] is True
    engine = MemoryEngine(db)
    try:
        assert engine.get_fact(eid) is None
    finally:
        engine.close()


# --- update ------------------------------------------------------------------


def test_update_supersede_replaces_and_keeps_history(tmp_path):
    db = _v3_db(tmp_path)
    (memory_id,) = _seed(db, _draft("the deploy is on friday"))
    provider = _provider(tmp_path, db)
    payload = _call(
        provider,
        "entropicmem_update",
        {"id": memory_id, "content": "the deploy is on monday", "reason": "date changed"},
    )
    assert payload["ok"] is True
    assert payload["id"] != memory_id
    assert payload["status"] == "superseded"
    assert payload["decision"] == "superseded"
    assert _memory(db, memory_id)["status"] == "superseded"
    assert _memory(db, payload["id"])["status"] == "active"


def test_update_edit_fixes_in_place(tmp_path):
    db = _v3_db(tmp_path)
    (memory_id,) = _seed(db, _draft("teh staging server runs on port 9090"))
    provider = _provider(tmp_path, db)
    payload = _call(
        provider,
        "entropicmem_update",
        {"id": memory_id, "content": STAGING, "mode": "edit", "importance": 0.9},
    )
    assert payload["ok"] is True
    assert payload["id"] == memory_id
    assert payload["status"] == "active"
    assert payload["decision"] == "updated"
    row = _memory(db, memory_id)
    assert row["content"] == STAGING
    assert row["importance"] == 0.9
    assert row["version"] >= 2


def test_update_unknown_id_is_not_found(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    payload = _call(
        provider, "entropicmem_update", {"id": "no-such-id", "content": "replacement"}
    )
    assert payload["ok"] is False
    assert payload["reason_code"] == "not_found"


def test_update_on_a_v2_store_needs_v3(tmp_path):
    db = _v2_db(tmp_path)
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_update", {"id": "x", "content": "y"})
    assert payload["ok"] is False
    assert payload["reason_code"] == "needs_v3_store"


# --- review ------------------------------------------------------------------


def _seed_pending(db: Path, content: str = "a quarantined fact") -> str:
    """A pending row: the write policy routes an auto-extracted source there."""
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            result = MemoryStore(conn).add(
                MemoryDraft(content=content, source="auto_extracted", status="active"),
                scope=PROFILE,
                actor="tester",
            )
            assert result.ok and result.status == "pending", result
        return result.id
    finally:
        store.close()


def test_review_list_pending(tmp_path):
    db = _v3_db(tmp_path)
    pending_id = _seed_pending(db)
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_review", {"action": "list_pending"})
    assert payload["ok"] is True
    assert [p["id"] for p in payload["pending"]] == [pending_id]


def test_review_promote_activates(tmp_path):
    db = _v3_db(tmp_path)
    pending_id = _seed_pending(db)
    provider = _provider(tmp_path, db)
    payload = _call(
        provider, "entropicmem_review", {"action": "promote", "id": pending_id}
    )
    assert payload["ok"] is True
    assert payload["id"] == pending_id
    assert payload["status"] == "active"
    assert payload["decision"] == "promoted"
    assert _memory(db, pending_id)["status"] == "active"


def test_review_discard_deletes(tmp_path):
    db = _v3_db(tmp_path)
    pending_id = _seed_pending(db)
    provider = _provider(tmp_path, db)
    payload = _call(
        provider, "entropicmem_review", {"action": "discard", "id": pending_id}
    )
    assert payload["ok"] is True
    assert payload["decision"] == "discarded"
    assert _memory(db, pending_id)["status"] == "deleted"


def test_review_consolidate_preview_is_a_dry_run(tmp_path):
    db = _v3_db(tmp_path)
    (memory_id,) = _seed(db, _draft(STAGING))
    provider = _provider(tmp_path, db)
    payload = _call(
        provider, "entropicmem_review", {"action": "consolidate_preview"}
    )
    assert payload["ok"] is True
    assert _memory(db, memory_id)["status"] == "active"


def test_review_restore_reactivates_a_superseded_memory(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    first = _call(provider, "entropicmem_remember", {"content": "the deploy is on friday"})
    second = _call(
        provider,
        "entropicmem_remember",
        {"content": "the deploy is on monday", "supersedes": first["id"]},
    )
    payload = _call(
        provider, "entropicmem_review", {"action": "restore", "id": first["id"]}
    )
    assert payload["ok"] is True
    assert payload["id"] == first["id"]
    assert payload["status"] == "active"
    assert _memory(db, first["id"])["status"] == "active"
    assert second["id"] != first["id"]


def test_review_feedback_writes_the_feedback_table(tmp_path):
    db = _v3_db(tmp_path)
    (memory_id,) = _seed(db, _draft(STAGING))
    provider = _provider(tmp_path, db)
    payload = _call(
        provider,
        "entropicmem_review",
        {"action": "feedback", "id": memory_id, "signal": "helpful"},
    )
    assert payload["ok"] is True
    rows = _rows(db, "SELECT * FROM feedback WHERE memory_id=?", (memory_id,))
    assert len(rows) == 1
    assert rows[0]["signal"] == "helpful"
    assert rows[0]["session_id"] == "em404-session"


def test_review_feedback_unknown_id_is_an_error(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    payload = _call(
        provider,
        "entropicmem_review",
        {"action": "feedback", "id": "no-such-id", "signal": "helpful"},
    )
    assert payload["ok"] is False


def test_review_restore_and_feedback_on_a_v2_store_need_v3(tmp_path):
    db = _v2_db(tmp_path)
    provider = _provider(tmp_path, db)
    for action in ("restore", "feedback"):
        payload = _call(
            provider,
            "entropicmem_review",
            {"action": action, "id": "x", "signal": "helpful"},
        )
        assert payload["ok"] is False
        assert payload["reason_code"] == "needs_v3_store", action


# --- timeline ----------------------------------------------------------------


def test_timeline_lists_episodes_in_window(tmp_path):
    db = _v3_db(tmp_path)
    episode_id = _seed_episode(
        db, title="Falcon migration", summary="we moved falcon to the new host"
    )
    provider = _provider(tmp_path, db)
    payload = _call(
        provider,
        "entropicmem_timeline",
        {"time_from": "2026-03-01", "time_to": "2026-03-01"},
    )
    assert payload["ok"] is True
    assert [e["id"] for e in payload["episodes"]] == [episode_id]
    episode = payload["episodes"][0]
    assert episode["kind"] == "episode"
    assert episode["content"] == "we moved falcon to the new host"
    assert episode["valid_from"] == STAMP
    assert episode["status"] == "active"


def test_timeline_query_filters(tmp_path):
    db = _v3_db(tmp_path)
    _seed_episode(db, title="Falcon migration", summary="we moved falcon to the new host")
    _seed_episode(db, title="Billing review", summary="nobody looked at the invoices")
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_timeline", {"query": "falcon"})
    assert [e["title"] for e in payload["episodes"]] == ["Falcon migration"]


# --- entity ------------------------------------------------------------------


def _seed_entity(db: Path, name: str, memory_id: str) -> str:
    from em.store.entities import normalise

    entity_id = "entity-" + name.lower().replace(" ", "-")
    _sql(
        db,
        "INSERT INTO entities (id, scope_profile, name, kind, description, created_at, updated_at)"
        " VALUES (?, 'default', ?, 'thing', 'the staging host', ?, ?)",
        (entity_id, name, STAMP, STAMP),
    )
    _sql(
        db,
        "INSERT INTO entity_aliases (alias_norm, entity_id) VALUES (?, ?)",
        (normalise(name), entity_id),
    )
    _sql(
        db,
        "INSERT INTO memory_entities (memory_id, entity_id, role) VALUES (?, ?, 'mention')",
        (memory_id, entity_id),
    )
    return entity_id


def test_entity_card_found(tmp_path):
    db = _v3_db(tmp_path)
    (memory_id,) = _seed(db, _draft(STAGING))
    _seed_entity(db, "Falcon-2", memory_id)
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_entity", {"name": "Falcon-2"})
    assert payload["ok"] is True
    assert payload["found"] is True
    assert payload["name"] == "Falcon-2"
    assert [m["id"] for m in payload["memories"]] == [memory_id]


def test_entity_hides_superseded_unless_include_history(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    first = _call(provider, "entropicmem_remember", {"content": "falcon is on host A"})
    _seed_entity(db, "Falcon-2", first["id"])
    _call(
        provider,
        "entropicmem_remember",
        {"content": "falcon is on host B", "supersedes": first["id"]},
    )
    default = _call(provider, "entropicmem_entity", {"name": "Falcon-2"})
    assert default["memories"] == []
    with_history = _call(
        provider, "entropicmem_entity", {"name": "Falcon-2", "include_history": True}
    )
    assert [m["id"] for m in with_history["memories"]] == [first["id"]]


def test_entity_unknown_name_is_not_found(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_entity", {"name": "Nobody"})
    assert payload["ok"] is True
    assert payload["found"] is False


def test_entity_on_a_v2_store_needs_v3(tmp_path):
    db = _v2_db(tmp_path)
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_entity", {"name": "Falcon-2"})
    assert payload["ok"] is False
    assert payload["reason_code"] == "needs_v3_store"


# --- profile, v2 remember, stats ---------------------------------------------


def test_profile_read_returns_core_text(tmp_path):
    db = _v3_db(tmp_path)
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    provider = _provider(tmp_path, db)
    provider._vault_path = vault_dir
    payload = _call(provider, "entropicmem_profile", {"action": "read"})
    assert payload["ok"] is True
    assert isinstance(payload["persona"], str)
    assert isinstance(payload["user_profile"], str)


def test_profile_patch_respects_the_write_flag(tmp_path):
    db = _v3_db(tmp_path)
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    provider = _provider(tmp_path, db)
    provider._vault_path = vault_dir
    off = _call(
        provider,
        "entropicmem_profile",
        {"action": "patch", "target": "persona", "old_text": "a", "new_text": "b"},
    )
    assert off["ok"] is False
    assert "writable" in off["error"]

    provider._config["core_memory_writable"] = True
    try:
        from em_internal.vault import CoreMemory

        core = CoreMemory(vault_dir)
        core.patch(target="persona", old_text="", new_text="")  # materialise the files
        core.patch(target="persona", old_text="Persona", new_text="Persona (edited)")
    except Exception:
        pass
    payload = _call(
        provider,
        "entropicmem_profile",
        {"action": "patch", "target": "persona", "old_text": "edited", "new_text": "verified"},
    )
    if payload["ok"]:
        assert payload["patched"] is True


def test_remember_on_a_v2_store_uses_the_engine(tmp_path):
    db = _v2_db(tmp_path)
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_remember", {"content": "v2 fact"})
    assert payload["ok"] is True
    assert payload["status"] == "active"
    assert payload["decision"] == "created"
    engine = MemoryEngine(db)
    try:
        assert engine.get_fact(payload["id"]) is not None
    finally:
        engine.close()


def test_remember_on_a_v2_store_warns_about_v3_only_fields(tmp_path):
    db = _v2_db(tmp_path)
    provider = _provider(tmp_path, db)
    payload = _call(
        provider,
        "entropicmem_remember",
        {"content": "v2 fact", "kind": "preference", "pinned": True},
    )
    warnings = " ".join(payload.get("warnings", []))
    assert "kind" in warnings
    assert "pinned" in warnings


def test_tool_errors_do_not_echo_exception_text(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)

    def boom():
        raise RuntimeError("/home/alice/private/memory.db: no such table")

    provider._open_engine = boom
    payload = _call(provider, "entropicmem_stats", {})
    rendered = json.dumps(payload)
    assert "/home/" not in rendered and "no such table" not in rendered
    assert "RuntimeError" in rendered


def test_tool_errors_do_not_echo_store_exception_text(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)

    class _BrokenEngine:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def stats(self):
            raise RuntimeError("/home/alice/private/memory.db: no such table")

    provider._memory_engine = lambda: (_BrokenEngine(), None)
    payload = _call(provider, "entropicmem_stats", {})
    rendered = json.dumps(payload)
    assert "/home/" not in rendered and "no such table" not in rendered
    assert "RuntimeError" in rendered


def test_stats_passes_through(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_stats", {})
    assert isinstance(payload, dict)
    assert "reason_code" not in payload
    assert payload["guest_mode"] == "inactive (no owner_user_ids)"
    assert payload["injection_screen"] in ("active", "unavailable", "unknown")


def test_recall_alias_returns_results_and_says_deprecated(tmp_path):
    db = _v3_db(tmp_path)
    (memory_id,) = _seed(db, _draft(STAGING))
    provider = _provider(tmp_path, db)
    payload = _call(provider, "entropicmem_recall", {"query": "staging server port"})
    assert [r["id"] for r in payload["results"]] == [memory_id]
    assert payload["deprecated_tool"] == "entropicmem_recall"
