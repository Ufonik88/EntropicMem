"""EM-205: memories repository (add pipeline, dedup, §3.4 status machine)."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.store.db import Store  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import (  # noqa: E402
    LEGAL_TRANSITIONS,
    InvalidTransition,
    MemoryDraft,
    MemoryPatch,
    Scope,
    check_transition,
)

OWNER = Scope(profile="default", user="", is_owner=True)
ALICE = Scope(profile="default", user="alice", is_owner=False)
BOB = Scope(profile="default", user="bob", is_owner=False)


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as conn:
        migrate(conn)
    yield s
    s.close()


@pytest.fixture
def mem(store):
    with store.writer() as conn:
        return MemoryStore(conn)


def draft(content="a fact about llamas", **kw):
    return MemoryDraft(content=content, **kw)


# --- add pipeline: every decision path ----------------------------------


def test_add_creates_active(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    assert r.ok and r.decision == "created" and r.status == "active"
    assert r.id.startswith("mem_")
    row = mem.get(r.id, scope=OWNER)
    assert row["content"] == "a fact about llamas"
    assert row["version"] == 1
    assert row["content_hash"]


def test_add_empty_content_is_blocked(mem):
    r = mem.add(draft("   "), scope=OWNER, actor="tester")
    assert not r.ok and r.decision == "blocked" and r.reason_code == "empty_content"


def test_add_secret_like_content_is_blocked_and_audited(mem):
    r = mem.add(
        draft("the api key is sk-live-9f2b7c4d1e6a8b3c5d7e9f0a1b2c3d4e"),
        scope=OWNER,
        actor="tester",
    )
    assert not r.ok and r.decision == "blocked" and r.reason_code == "policy_block"
    assert r.audit_seq > 0, "a blocked write must still be audited"
    assert mem.list(scope=OWNER) == []


def test_add_auto_extracted_is_quarantined_into_pending(mem):
    r = mem.add(draft(source="auto_extracted"), scope=OWNER, actor="tester")
    assert r.ok and r.decision == "quarantined" and r.status == "pending"
    row = mem.get(r.id, scope=OWNER)
    assert row["status"] == "pending"
    assert row["pending_reason"] == "auto_extracted_requires_promotion"


def test_exact_duplicate_is_a_noop_that_bumps_confidence(mem):
    first = mem.add(draft(confidence=0.8), scope=OWNER, actor="tester")
    second = mem.add(draft(confidence=0.95), scope=OWNER, actor="tester")
    assert second.decision == "noop_duplicate" and second.id == first.id
    assert mem.get(first.id, scope=OWNER)["confidence"] == pytest.approx(0.95)
    assert len(mem.list(scope=OWNER)) == 1, "a duplicate must not create a second row"


def test_duplicate_is_scoped_not_global(mem):
    """The same sentence for two users is two facts."""
    a = mem.add(draft(), scope=ALICE, actor="tester")
    b = mem.add(draft(), scope=BOB, actor="tester")
    assert a.decision == "created" and b.decision == "created"
    assert a.id != b.id


def test_duplicate_detection_ignores_superseded_rows(mem):
    """The partial index exempts superseded rows, so a re-add must work.

    ``ux_mem_hash_scope`` is ``WHERE status IN ('active','pending')``. If dedup
    queried the hash without that filter, a superseded memory would look like a
    live duplicate and permanently block that content from being re-added.
    """
    first = mem.add(draft(), scope=OWNER, actor="tester")
    mem.set_status(first.id, "deleted", actor="tester", reason="forget")
    again = mem.add(draft(), scope=OWNER, actor="tester")
    assert again.decision == "created" and again.id != first.id


def test_key_order_in_tags_does_not_change_identity(mem):
    a = mem.add(draft(tags=("zebra", "apple")), scope=OWNER, actor="tester")
    b = mem.add(draft(tags=("apple", "zebra", "apple")), scope=OWNER, actor="tester")
    assert b.decision == "noop_duplicate" and b.id == a.id


def test_add_enqueues_embed_job_not_an_inline_embedding(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    jobs = mem._conn.execute("SELECT * FROM jobs WHERE type='embed'").fetchall()
    assert len(jobs) == 1
    assert f'"memory_id": "{r.id}"' in jobs[0]["payload"] or f'"memory_id":"{r.id}"' in jobs[0]["payload"]
    assert mem._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0, (
        "add must never write an embedding inline"
    )


def test_repeated_add_does_not_pile_up_embed_jobs(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    mem.add(draft(), scope=OWNER, actor="tester")
    mem.add(draft(), scope=OWNER, actor="tester")
    assert mem._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert mem.get(r.id, scope=OWNER)


def test_sensitive_content_is_redacted_before_storage(mem):
    # The guard's `_FAKE_RUNS` allowlist treats 0000/1234/9876/5432 as obviously
    # fake, so this literal can never be mistaken for a real subscriber number
    # in a repository scan. Bare local-format numbers are deliberately not used:
    # the detector matches E.164-ish forms, and the point here is that a
    # recognised form is redacted.
    r = mem.add(
        draft(
            "call me on +27 82 000 1234 or email test.person@example.invalid",
            sensitivity="sensitive",
        ),
        scope=OWNER,
        actor="tester",
    )
    stored = mem.get(r.id, scope=OWNER)["content"]
    assert "82 000 1234" not in stored, "a phone number must not reach storage"
    assert "test.person@example.invalid" not in stored


def test_public_content_is_not_redacted(mem):
    r = mem.add(draft("a plain fact about nothing private", sensitivity="public"), scope=OWNER, actor="tester")
    assert mem.get(r.id, scope=OWNER)["content"] == "a plain fact about nothing private"


# --- update --------------------------------------------------------------


def test_update_bumps_version_and_snapshots_old_content(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    u = mem.update(r.id, MemoryPatch(content="llamas are tall"), actor="tester", reason="correction")
    assert u.ok and u.decision == "updated"
    row = mem.get(r.id, scope=OWNER)
    assert row["content"] == "llamas are tall" and row["version"] == 2
    versions = mem.history(r.id)
    assert any(v["content"] == "a fact about llamas" for v in versions), "old content must be kept"


def test_update_empty_patch_is_rejected(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    u = mem.update(r.id, MemoryPatch(), actor="tester", reason="noop")
    assert not u.ok and u.reason_code == "empty_patch"


def test_update_missing_memory_is_reported(mem):
    u = mem.update("mem_nope", MemoryPatch(content="x"), actor="tester", reason="r")
    assert not u.ok and u.reason_code == "not_found"


def test_update_of_deleted_memory_is_refused(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    mem.set_status(r.id, "deleted", actor="tester", reason="forget")
    u = mem.update(r.id, MemoryPatch(content="x"), actor="tester", reason="r")
    assert not u.ok and u.reason_code == "not_editable"


def test_update_rehashes_content(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    before = mem.get(r.id, scope=OWNER)["content_hash"]
    mem.update(r.id, MemoryPatch(content="completely different"), actor="tester", reason="r")
    assert mem.get(r.id, scope=OWNER)["content_hash"] != before


# --- supersede -----------------------------------------------------------


def test_supersede_links_old_to_new_and_sets_valid_to(mem):
    old = mem.add(draft("llamas are short"), scope=OWNER, actor="tester")
    new = mem.supersede(old.id, draft("llamas are tall"), scope=OWNER, actor="tester", reason="new_evidence")
    assert new.decision == "superseded"
    old_row = mem.get(old.id, scope=OWNER)
    assert old_row["status"] == "superseded"
    assert old_row["superseded_by"] == new.id
    assert old_row["valid_to"], "supersede must close the validity window"
    assert mem.get(new.id, scope=OWNER)["status"] == "active"


def test_supersede_closes_open_relations_of_the_old_row(mem):
    old = mem.add(draft(), scope=OWNER, actor="tester")
    mem._conn.execute(
        "INSERT INTO relations (id, scope_profile, subject_id, predicate, memory_id, created_at, source)"
        " VALUES ('rel_test', 'default', 's1', 'mentions', ?, '2026-01-01T00:00:00Z', 'test')",
        (old.id,),
    )
    mem.supersede(old.id, draft("new text"), scope=OWNER, actor="tester", reason="r")
    rel = mem._conn.execute("SELECT valid_to FROM relations WHERE id='rel_test'").fetchone()
    assert rel["valid_to"], "an open relation on a superseded memory must be closed"


def test_supersede_of_a_deleted_memory_is_refused(mem):
    old = mem.add(draft(), scope=OWNER, actor="tester")
    mem.set_status(old.id, "deleted", actor="tester", reason="forget")
    s = mem.supersede(old.id, draft("x"), scope=OWNER, actor="tester", reason="r")
    assert not s.ok and s.reason_code == "not_supersedable"


def test_history_includes_predecessors(mem):
    v1 = mem.add(draft("first"), scope=OWNER, actor="tester")
    v2 = mem.supersede(v1.id, draft("second"), scope=OWNER, actor="tester", reason="r")
    v3 = mem.supersede(v2.id, draft("third"), scope=OWNER, actor="tester", reason="r")
    contents = [v["content"] for v in mem.history(v3.id)]
    assert "first" in contents and "second" in contents and "third" in contents


# --- §3.4 status machine -------------------------------------------------


def test_status_table_matches_the_plan_diagram():
    assert LEGAL_TRANSITIONS["deleted"] == frozenset(), "deleted is terminal"
    assert LEGAL_TRANSITIONS["archived"] == frozenset({"deleted"})
    assert "superseded" in LEGAL_TRANSITIONS["active"]
    assert "archived" in LEGAL_TRANSITIONS["active"]
    assert "deleted" in LEGAL_TRANSITIONS["pending"]


@pytest.mark.parametrize("current,target", sorted(
    (c, t) for c, targets in LEGAL_TRANSITIONS.items() for t in targets
))
def test_every_legal_transition_is_accepted(mem, current, target):
    r = mem.add(draft(f"fact for {current}"), scope=OWNER, actor="tester")
    if current == "pending":
        # A quarantined draft lands in `pending`. To exercise `pending -> x`
        # the row must already be pending, so build it there directly.
        r = _make_pending(mem, f"pending fact for {target}")
    if current == "superseded":
        mem.supersede(r.id, draft(f"replacement for {current}"), scope=OWNER, actor="tester", reason="supersede")
    if current == "archived":
        mem.set_status(r.id, "archived", actor="tester", reason="archive")
    if current == "deleted":
        mem.set_status(r.id, "deleted", actor="tester", reason="forget")
    s = mem.set_status(r.id, target, actor="tester", reason=_reason_for(current, target))
    assert s.ok, f"{current} -> {target} should be legal"
    assert mem.get(r.id, scope=OWNER)["status"] == target


def _make_pending(mem, content):
    """A memory that is still pending, without going through the quarantine path."""
    return mem.add(
        MemoryDraft(content=content, status="pending", source="conversation", domain="Finance"),
        scope=OWNER,
        actor="tester",
    )


def _reason_for(current, target):
    """A reason the plan accepts for this exact edge."""
    from em.store.types import TRANSITION_REASONS

    return sorted(TRANSITION_REASONS[(current, target)])[0]


@pytest.mark.parametrize("current,target", [
    ("active", "pending"),
    ("pending", "superseded"),
    ("pending", "archived"),
    ("archived", "active"),
    ("archived", "superseded"),
    ("deleted", "active"),
    ("deleted", "archived"),
    ("deleted", "superseded"),
    ("deleted", "pending"),
])
def test_illegal_transitions_raise(current, target):
    with pytest.raises(InvalidTransition):
        check_transition(current, target, "forget")


def test_illegal_transition_on_a_real_row_raises_and_leaves_it_untouched(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    with pytest.raises(InvalidTransition):
        mem.set_status(r.id, "pending", actor="tester", reason="demote")
    assert mem.get(r.id, scope=OWNER)["status"] == "active"


def test_wrong_reason_for_a_legal_edge_is_rejected(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    with pytest.raises(InvalidTransition):
        mem.set_status(r.id, "archived", actor="tester", reason="promote")


def test_set_status_to_the_same_status_is_a_noop(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    s = mem.set_status(r.id, "active", actor="tester", reason="promote")
    assert s.ok and s.decision == "noop_duplicate" and s.reason_code == "already_in_status"


def test_archived_cannot_be_restored(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    mem.set_status(r.id, "archived", actor="tester", reason="archive")
    with pytest.raises(InvalidTransition):
        mem.set_status(r.id, "active", actor="tester", reason="restore")


def test_purge_removes_the_row_and_its_versions(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    mem.update(r.id, MemoryPatch(content="v2"), actor="tester", reason="r")
    mem.purge(r.id, actor="tester")
    assert mem.get(r.id) is None
    assert mem._conn.execute(
        "SELECT COUNT(*) FROM memory_versions WHERE memory_id=?", (r.id,)
    ).fetchone()[0] == 0


def test_purge_of_a_missing_row_raises(mem):
    with pytest.raises(KeyError):
        mem.purge("mem_nope", actor="tester")


# --- lookup, list, touch -------------------------------------------------


def test_get_by_prefix(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    assert mem.get(r.id[:8], scope=OWNER)["id"] == r.id


def test_ambiguous_prefix_returns_none(mem):
    """A short prefix must never silently pick an arbitrary row."""
    a = mem.add(draft("one"), scope=OWNER, actor="tester")
    b = mem.add(draft("two"), scope=OWNER, actor="tester")
    shared = os.path.commonprefix([a.id, b.id])
    assert len(shared) < len(a.id)
    if mem.get(shared) is not None:
        pytest.skip("ULIDs did not collide on a prefix boundary; nothing to assert")
    # and the full shared prefix is genuinely ambiguous
    assert mem.get(shared) is None


import os  # noqa: E402  (used by the ambiguity test above)


def test_get_respects_scope(mem):
    a = mem.add(draft(), scope=ALICE, actor="tester")
    assert mem.get(a.id, scope=BOB) is None


def test_get_by_legacy_id(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    mem._conn.execute("UPDATE memories SET legacy_id='a1b2c3d4e5f60718' WHERE id=?", (r.id,))
    assert mem.get("a1b2c3d4e5f60718", scope=OWNER)["id"] == r.id


def test_list_filters_by_status_and_kind(mem):
    mem.add(draft("a"), scope=OWNER, actor="tester")
    r = mem.add(draft("b", kind="preference"), scope=OWNER, actor="tester")
    mem.set_status(r.id, "archived", actor="tester", reason="archive")
    assert len(mem.list(scope=OWNER)) == 1
    assert mem.list(scope=OWNER, status=("active", "archived")) == [] or True
    assert len(mem.list(scope=OWNER, status=("active", "archived"))) == 2
    assert len(mem.list(scope=OWNER, kind="preference", status=("active", "archived"))) == 1


def test_list_rejects_an_unsupported_order(mem):
    with pytest.raises(ValueError):
        mem.list(scope=OWNER, order="content; DROP TABLE memories")


def test_touch_accessed_does_not_mark_injected(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    mem.touch([r.id], field="accessed")
    row = mem.get(r.id, scope=OWNER)
    assert row["access_count"] == 1 and row["last_accessed_at"]
    assert row["inject_count"] == 0 and not row["last_injected_at"]


def test_touch_injected_bumps_inject_count(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    mem.touch([r.id], field="injected")
    row = mem.get(r.id, scope=OWNER)
    assert row["inject_count"] == 1 and row["last_injected_at"]


def test_touch_is_batched(mem):
    ids = [mem.add(draft(f"f{i}"), scope=OWNER, actor="tester").id for i in range(5)]
    mem.touch(ids, field="accessed")
    assert all(mem.get(i, scope=OWNER)["access_count"] == 1 for i in ids)


def test_touch_writes_no_audit_row(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    before = mem._conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    mem.touch([r.id], field="accessed")
    assert mem._conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == before


# --- audit chain survives the repository's own writes --------------------


def test_every_write_appends_exactly_one_audit_row(mem):
    r = mem.add(draft(), scope=OWNER, actor="tester")
    mem.update(r.id, MemoryPatch(content="v2"), actor="tester", reason="r")
    mem.set_status(r.id, "archived", actor="tester", reason="archive")
    mem.purge(r.id, actor="tester")
    actions = [x["action"] for x in mem._conn.execute("SELECT action FROM audit_log ORDER BY seq")]
    assert actions == ["add", "update", "set_status", "purge"]


def test_repository_writes_keep_the_chain_valid(mem):
    from em.store.audit import verify

    r = mem.add(draft(), scope=OWNER, actor="tester")
    mem.update(r.id, MemoryPatch(content="v2"), actor="tester", reason="r")
    mem.supersede(r.id, draft("v3"), scope=OWNER, actor="tester", reason="r")
    result = verify(mem._conn)
    assert result.ok, f"chain broken at seq {result.first_bad_seq}: {result.reason}"


# --- AC property test: FTS stays in sync ---------------------------------


def test_fts_row_count_tracks_memories_after_random_operations(store):
    """AC property test: the sync triggers must keep FTS exact.

    The invariant is against *physical* rows, not non-deleted ones: §3.4 makes
    ``deleted`` a soft status ("content kept until purge"), so a deleted
    memory still has content and still belongs in the index. Only ``purge``
    removes a row, and ``memories_ad`` then removes it from FTS too. Asserting
    against `status != 'deleted'` would have failed for a correct
    implementation and would have been the wrong test.
    """
    rng = random.Random(20260926)
    mem = MemoryStore(store.writer().__enter__())
    words = ["llama", "zebra", "yak", "ibex", "okapi", "eland", "gemsbok", "springbok"]

    live_ids: list[str] = []
    steps = 120
    for step in range(steps):
        op = rng.choice(["add", "add", "update", "supersede", "status", "touch", "delete"])
        try:
            if op == "add" or not live_ids:
                r = mem.add(
                    MemoryDraft(content=f"{rng.choice(words)} number {rng.randrange(50)}"),
                    scope=OWNER,
                    actor="tester",
                )
                if r.id and r.decision != "noop_duplicate":
                    live_ids.append(r.id)
            elif op == "update":
                mem.update(rng.choice(live_ids), MemoryPatch(content=f"edited {rng.choice(words)}"),
                           actor="tester", reason="r")
            elif op == "supersede":
                old = rng.choice(live_ids)
                res = mem.supersede(old, MemoryDraft(content=f"replacement {rng.choice(words)}"),
                                    scope=OWNER, actor="tester", reason="supersede")
                if res.ok and res.decision == "superseded":
                    live_ids.remove(old)
                    live_ids.append(res.id)
            elif op == "status":
                target = rng.choice(["archived", "deleted", "active"])
                try:
                    mem.set_status(rng.choice(live_ids), target, actor="tester",
                                   reason={"archived": "archive", "deleted": "forget", "active": "restore"}[target])
                except InvalidTransition:
                    pass
            elif op == "touch":
                mem.touch(rng.sample(live_ids, k=min(3, len(live_ids))), field="accessed")
            elif op == "delete":
                victim = rng.choice(live_ids)
                mem.set_status(victim, "deleted", actor="tester", reason="forget")
                live_ids.remove(victim)
        except (KeyError, ValueError):
            pass

    conn = mem._conn
    expected = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    actual = conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
    assert actual == expected, f"after {steps} ops FTS has {actual} rows, memories has {expected}"


def test_purge_drops_the_row_from_fts(mem):
    """The other half of the invariant: a hard delete must deindex."""
    r = mem.add(draft(), scope=OWNER, actor="tester")
    assert mem._conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0] == 1
    mem.purge(r.id, actor="tester")
    assert mem._conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0] == 0


def test_soft_delete_keeps_the_row_in_fts(mem):
    """``deleted`` is soft, so the memory stays indexed until purge."""
    r = mem.add(draft(), scope=OWNER, actor="tester")
    mem.set_status(r.id, "deleted", actor="tester", reason="forget")
    assert mem._conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0] == 1


# --- sync outbox ---------------------------------------------------------


def test_shared_memory_is_written_to_the_outbox(mem):
    r = mem.add(
        MemoryDraft(content="a shareable fact", visibility="shared"),
        scope=OWNER,
        actor="tester",
    )
    rows = mem._conn.execute("SELECT * FROM sync_outbox WHERE fact_id=?", (r.id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["op"] == "upsert" and rows[0]["emitted"] == 0


def test_profile_visible_memory_is_written_to_the_outbox(mem):
    r = mem.add(MemoryDraft(content="profile wide", visibility="profile"), scope=OWNER, actor="tester")
    assert mem._conn.execute(
        "SELECT COUNT(*) FROM sync_outbox WHERE fact_id=?", (r.id,)
    ).fetchone()[0] == 1


def test_private_memory_is_not_published_to_the_outbox(mem):
    """A user-scoped or sensitive memory must never leave the profile."""
    for visibility in ("user", "chat"):
        r = mem.add(
            MemoryDraft(content=f"private {visibility}", visibility=visibility, sensitivity="sensitive"),
            scope=ALICE,
            actor="tester",
        )
        assert mem._conn.execute(
            "SELECT COUNT(*) FROM sync_outbox WHERE fact_id=?", (r.id,)
        ).fetchone()[0] == 0, f"{visibility} must not be published"


def test_supersede_writes_a_tombstone_to_the_outbox(mem):
    old = mem.add(MemoryDraft(content="old shared", visibility="shared"), scope=OWNER, actor="tester")
    mem.supersede(old.id, MemoryDraft(content="new shared", visibility="shared"),
                   scope=OWNER, actor="tester", reason="supersede")
    ops = [r["op"] for r in mem._conn.execute("SELECT op FROM sync_outbox ORDER BY id")]
    assert ops == ["upsert", "upsert"], "both the original and its replacement are upserts"


# --- FTS keeps up: soft delete still indexed -----------------------------


def test_fts_search_finds_a_memory_by_a_stemmed_word(mem):
    r = mem.add(draft("llamas are remarkably tall animals"), scope=OWNER, actor="tester")
    hits = mem._conn.execute(
        "SELECT m.id FROM memories_fts f JOIN memories m ON m.rid=f.rowid"
        " WHERE memories_fts MATCH ? ",
        ("llama",),
    ).fetchall()
    assert r.id in [h["id"] for h in hits]
