"""Chunk 38 — the `remember` content ceiling: a raised cap and a fatal refusal.

The defect this card fixes is **silent data loss** (found 2026-10-17 by a live
incident): `REMEMBER_SCHEMA`/`UPDATE_SCHEMA` pinned `content` at `maxLength:
4000`, and `jsonschema_lite.validate_arguments` implemented that cap as
*clamp-with-a-warning* — the value was truncated in place and then persisted, so
a 4,314-character summary registered `active/created` with its tail gone. `full`
and `cut` became indistinguishable at recall time, forever.

The fix moves exactly two fields:

* one shared `CONTENT_MAX_CHARS = 8_000` in `em/provider/tools.py`, which both
  schemas build their `maxLength` from, so the number exists once;
* a keyword-only `fatal_length_keys` mode on `validate_arguments` — for the keys
  named, over-long input **raises** (the same fatal shape used for types and
  enums) instead of clamping — and `handle_tool_call` passes the map for
  `remember`/`update` `content`, so the refusal rides the existing
  `ArgumentError -> invalid_arguments` branch **before any store write**.

The validator's default two-argument call is byte-identical; every other field,
tool and cap is untouched. Rules: invented data only.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for entry in (str(REPO), str(SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

from em.facade.engine import V3Engine  # noqa: E402
from em.provider.prefetch_service import PrefetchService  # noqa: E402
from em.provider.tools import (  # noqa: E402
    CONTENT_MAX_CHARS,
    FATAL_LENGTH_KEYS,
    REMEMBER_SCHEMA,
    UPDATE_SCHEMA,
)
from em.retrieval.packer import PackItem, estimate_tokens, pack  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import Scope  # noqa: E402

SCOPE = Scope(profile="default")

#: The one guidance sentence the two `content` descriptions carry (the card's
#: section C). Pinned word for word; the refusal is the backstop, this is the
#: teacher the model reads while composing the call.
GUIDANCE = (
    "Beyond the embedding window — long documents belong in the vault; "
    "store the fact or a pointer to the note."
)
REMEMBER_DESCRIPTION = (
    "Self-contained statement, full detail for technical facts. " + GUIDANCE
)


# --- fixtures ----------------------------------------------------------------


def _v3_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    V3Engine(db).close()
    return db


def _provider(tmp_path: Path, db: Path) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(
        config={"core_memory_enabled": False, "touch_on_inject": False}
    )
    provider.initialize("ceiling-session", hermes_home=str(tmp_path), agent_identity="default")
    provider._scripts_dir = SCRIPTS
    provider._memory_db = db
    provider._profile_id = "default"
    return provider


def _call(provider: EntropicMemMemoryProvider, name: str, args: dict) -> dict:
    out = provider.handle_tool_call(name, args)
    assert isinstance(out, str)
    return json.loads(out)


def _rows(db: Path, statement: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(statement, params).fetchall()]
    finally:
        conn.close()


def _counts(db: Path) -> tuple[int, int]:
    """``(memories, audit rows)`` — the pair a refused write must not move."""
    return (
        _rows(db, "SELECT count(*) AS n FROM memories")[0]["n"],
        _rows(db, "SELECT count(*) AS n FROM audit_log")[0]["n"],
    )


# --- 4. one constant, two schemas, one map -----------------------------------


def test_the_ceiling_is_a_single_shared_constant():
    assert CONTENT_MAX_CHARS == 8_000
    remember = REMEMBER_SCHEMA["parameters"]["properties"]["content"]
    update = UPDATE_SCHEMA["parameters"]["properties"]["content"]
    assert remember["maxLength"] == CONTENT_MAX_CHARS
    assert update["maxLength"] == CONTENT_MAX_CHARS


def test_the_fatal_length_map_covers_exactly_remember_and_update_content():
    assert FATAL_LENGTH_KEYS == {
        "entropicmem_remember": frozenset({"content"}),
        "entropicmem_update": frozenset({"content"}),
    }
    # No other tool's fields are fatal-capped: the map is the whole deviation.
    assert set(FATAL_LENGTH_KEYS) <= {"entropicmem_remember", "entropicmem_update"}


# --- 1 & 2. remember: at the ceiling stores, over it refuses -----------------


def test_remember_at_the_ceiling_stores_the_content_byte_for_byte(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    content = "f" * CONTENT_MAX_CHARS
    try:
        payload = _call(provider, "entropicmem_remember", {"content": content})
        assert payload.get("ok") is True, payload
        stored = _rows(db, "SELECT content FROM memories WHERE id=?", (payload["id"],))
        assert stored, payload
        assert stored[0]["content"] == content, "the stored content was not byte-equal"
        assert len(stored[0]["content"]) == CONTENT_MAX_CHARS
    finally:
        provider.shutdown()


def test_remember_over_the_ceiling_is_refused_and_writes_nothing(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    content = "f" * (CONTENT_MAX_CHARS + 1)
    before = _counts(db)
    try:
        payload = _call(provider, "entropicmem_remember", {"content": content})
        assert payload["ok"] is False
        assert payload["reason_code"] == "invalid_arguments"
        message = payload["error"]
        assert "content" in message
        assert str(CONTENT_MAX_CHARS) in message
        assert str(len(content)) in message
        assert _counts(db) == before, "a refused remember wrote a row or an audit entry"
    finally:
        provider.shutdown()


# --- 3. update inherits the fix ----------------------------------------------


def test_update_at_the_ceiling_stores_the_content_byte_for_byte(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        first = _call(provider, "entropicmem_remember", {"content": "the falcon port is 9090"})
        assert first.get("ok") is True, first
        content = "u" * CONTENT_MAX_CHARS
        payload = _call(
            provider,
            "entropicmem_update",
            {"id": first["id"], "content": content, "mode": "supersede"},
        )
        assert payload.get("ok") is True, payload
        stored = _rows(db, "SELECT content FROM memories WHERE id=?", (payload["id"],))
        assert stored and stored[0]["content"] == content
    finally:
        provider.shutdown()


def test_update_over_the_ceiling_is_refused_in_both_modes(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        first = _call(provider, "entropicmem_remember", {"content": "the falcon port is 9090"})
        assert first.get("ok") is True, first
        over = "u" * (CONTENT_MAX_CHARS + 1)
        for mode in ("supersede", "edit"):
            before = _counts(db)
            payload = _call(
                provider,
                "entropicmem_update",
                {"id": first["id"], "content": over, "mode": mode},
            )
            assert payload["reason_code"] == "invalid_arguments", (mode, payload)
            assert "content" in payload["error"]
            assert _counts(db) == before, f"a refused {mode} update wrote something"
    finally:
        provider.shutdown()


# --- 8. the wording is consistent --------------------------------------------


def test_the_refusal_message_has_one_pinned_shape():
    """The message names the field, the limit and what arrived — the same fatal
    shape types and enums already use, so a model reads one sentence and fixes
    the call."""
    from em.util.jsonschema_lite import ArgumentError, validate_arguments  # noqa: PLC0415

    schema = REMEMBER_SCHEMA
    try:
        validate_arguments(schema, {"content": "x" * (CONTENT_MAX_CHARS + 1)}, fatal_length_keys={"content"})
    except ArgumentError as exc:
        assert str(exc) == f"`content` must be at most {CONTENT_MAX_CHARS} characters, got {CONTENT_MAX_CHARS + 1}"
    else:  # pragma: no cover - the raise is the point
        raise AssertionError("over-long content did not raise")


def test_the_guidance_sentence_is_pinned_on_both_content_descriptions():
    remember = REMEMBER_SCHEMA["parameters"]["properties"]["content"]["description"]
    update = UPDATE_SCHEMA["parameters"]["properties"]["content"]["description"]
    assert remember == REMEMBER_DESCRIPTION
    assert GUIDANCE in update


# --- 6. the packer still packs by budget at the raised cap -------------------


def _cost(chosen) -> int:
    """The rendered block's cost, near enough: bodies plus a citation per row."""
    return sum(estimate_tokens(c.body) + 5 for c in chosen)


def _ceiling_item(summary: str = "") -> PackItem:
    return PackItem(
        owner_type="memory",
        owner_id="mem_ceiling",
        score=1.0,
        content="c" * CONTENT_MAX_CHARS,
        summary=summary,
    )


def test_a_ceiling_sized_fact_with_a_distinct_summary_renders_the_summary():
    chosen = pack([_ceiling_item("short note about the ceiling")], budget=60, cost=_cost)
    assert len(chosen) == 1
    assert chosen[0].body == "short note about the ceiling"


def test_a_ceiling_sized_fact_without_a_summary_is_skipped_never_cut():
    chosen = pack([_ceiling_item()], budget=60, cost=_cost)
    assert chosen == [], "a fact that does not fit must be skipped, never truncated"


def test_the_block_budget_is_never_stretched_at_the_raised_cap():
    items = [
        _ceiling_item(),  # will not fit
        PackItem(owner_type="memory", owner_id="mem_b", score=0.9, content="a short fact"),
        PackItem(owner_type="memory", owner_id="mem_c", score=0.8, content="another short fact"),
    ]
    budget = 450
    chosen = pack(items, budget=budget, cost=_cost)
    assert _cost(chosen) <= budget
    assert all(c.body in (c.item.content, c.item.summary) for c in chosen)


# --- 7. containment, measured (a recorded number, not a gate) -----------------


def _spawn(target, name):
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def test_long_content_does_not_stretch_serving(tmp_path):
    """The card's measurement AC: a 20k-fact fixture at ~2,000-character content
    is served inside §4.2's block cap (never stretched), and the run **records**
    the numbers — FTS build seconds, index size, warm p95 — rather than gating a
    new budget. A longer row costs index bytes and the same bounded query, not a
    bigger block; the assertion is the cap, the printed line is the evidence."""
    db = tmp_path / "big.db"
    saved = Store(str(db))
    with saved.writer() as conn:
        migrate(conn)
    filler = (
        "the falcon staging service runs on port 9090 and it is used for integration "
        "builds in the Frankfurt cluster; "
    ) * 20
    stamp = "2026-03-01T10:00:00Z"
    started = time.perf_counter()
    with saved.transaction() as conn:
        conn.executemany(
            "INSERT INTO memories (id, scope_profile, scope_user, visibility, kind, content,"
            " summary, content_hash, source, created_at, updated_at, status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    f"mem_{i:06d}", "default", "", "profile", "fact",
                    (f"build record vulcan{i}: " + filler)[:2000],
                    f"build record vulcan{i} uses port {8000 + (i % 1000)}",
                    f"h{i:06d}", "agent", stamp, stamp, "active",
                )
                for i in range(20_000)
            ],
        )
    fts_seconds = time.perf_counter() - started
    index_mb = os.path.getsize(db) / (1024 * 1024)

    service = PrefetchService(connect=saved.reader, spawn_thread=_spawn, token_budget=450)
    try:
        for i in (0, 1, 2):
            service.prefetch(
                f"what port does build record vulcan{i} use?", scope=SCOPE, session_id="warm"
            )
        samples = []
        for probe in range(10):
            began = time.perf_counter()
            # A distinct record per probe (and its own session): §4.2's dedup is a
            # correctness feature, not the cost being measured — with one query
            # repeated, the warmup's rows are suppressed and the block is
            # legitimately empty.
            result = service.prefetch(
                f"what port does build record vulcan{100 + probe} use?",
                scope=SCOPE,
                session_id=f"probe-{probe}",
            )
            samples.append((time.perf_counter() - began) * 1000.0)
            assert result.text, "the 20k fixture served nothing"
            assert len(result.text) <= 9_000, "§4.2's block cap was stretched"
        samples.sort()
        p95 = samples[max(0, int(0.95 * len(samples)) - 1)]
        print(
            "[ceiling] 20k facts @ ~2,000 chars — "
            f"fts+insert {fts_seconds:.2f}s, index {index_mb:.1f} MB, "
            f"warm p95 {p95:.2f} ms (max {samples[-1]:.2f} ms), cap ≤ 9,000 chars"
        )
    finally:
        service.close()
        saved.close()
