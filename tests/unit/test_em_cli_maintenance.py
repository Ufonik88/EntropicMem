"""EM-211 Chunk 10.2: the facade's CLI-compatibility maintenance calls.

Same rule as 10.1 — return what the CLI prints — but these change state, so the
tests assert the **transition** (through `get_fact`/`stats`, or the store's own
rows) rather than trusting a return value, and the CLI's keys where it prints a
dict.

`promote_pending`/`discard_pending` are where v3's model differs most from v2's
and the difference is deliberate: v2 kept a quarantine row *and* wrote a separate
durable fact, so promotion produced a new id; on v3 the pending row **is** the
memory, so promotion is the `pending -> active` edge and the id is unchanged.

Rules: invented data only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.facade.engine import V3Engine  # noqa: E402


@pytest.fixture
def engine(tmp_path):
    eng = V3Engine(tmp_path / "memory.db")
    yield eng
    eng.close()


def pending(engine, content="Acme used a legacy deploy script.", **kw):
    """A quarantined row: the write policy routes an auto_extracted source there."""
    return engine.remember(content=content, source="auto_extracted", **kw)


def status_of(engine, mid):
    return engine.store.reader().execute(
        "SELECT status FROM memories WHERE id=?", (mid,)
    ).fetchone()["status"]


def access_count(engine, mid):
    return engine.store.reader().execute(
        "SELECT access_count FROM memories WHERE id=?", (mid,)
    ).fetchone()["access_count"]


# --- promote_pending ----------------------------------------------------------


def test_promote_pending_activates_the_same_row(engine):
    """One row, one history: v3 promotion is a transition, not a second write."""
    mid = pending(engine)
    assert status_of(engine, mid) == "pending"
    assert engine.stats()["fact_count"] == 0, "pending rows are not live"

    assert engine.promote_pending(mid) == mid, "the id is unchanged"
    assert status_of(engine, mid) == "active"
    assert engine.get_fact(mid) is not None
    assert engine.stats()["fact_count"] == 1


def test_promote_pending_refuses_a_row_that_is_not_pending(engine):
    mid = engine.remember(content="Acme ships on Tuesdays.")
    assert engine.promote_pending(mid) is None
    assert status_of(engine, mid) == "active", "and it changes nothing"


def test_promote_pending_of_an_unknown_id_is_none(engine):
    assert engine.promote_pending("mem_does_not_exist") is None


def test_promote_pending_writes_an_audit_row(engine):
    mid = pending(engine)
    engine.promote_pending(mid)
    actions = [r["action"] for r in engine.store.reader().execute(
        "SELECT action FROM audit_log ORDER BY seq")]
    assert "set_status" in actions


# --- discard_pending ----------------------------------------------------------


def test_discard_pending_returns_true_and_deletes(engine):
    mid = pending(engine)
    assert engine.discard_pending(mid) is True
    assert status_of(engine, mid) == "deleted"
    assert engine.get_fact(mid) is None, "a discarded row reads as absent"


def test_discard_pending_refuses_a_row_that_is_not_pending(engine):
    mid = engine.remember(content="Globex ships on Tuesdays.")
    assert engine.discard_pending(mid) is False
    assert status_of(engine, mid) == "active"


def test_discard_pending_of_an_unknown_id_is_false(engine):
    assert engine.discard_pending("mem_does_not_exist") is False


# --- reinforce ----------------------------------------------------------------


def test_reinforce_bumps_the_access_clock_and_counter(engine):
    """v2's UPDATE: last_accessed to now, access_count + 1."""
    mid = engine.remember(content="Acme deploys the billing service.")
    assert access_count(engine, mid) == 0
    before = engine.get_fact(mid).last_accessed

    assert engine.reinforce(mid) is True
    assert access_count(engine, mid) == 1
    assert engine.get_fact(mid).last_accessed != before


def test_reinforce_of_an_unknown_id_is_false(engine):
    assert engine.reinforce("mem_does_not_exist") is False


# --- rebuild_fts --------------------------------------------------------------


def test_rebuild_fts_reports_v2_keys_and_touches_nothing(engine):
    """v3's FTS is trigger-maintained, so this is a report, not a repair."""
    engine.remember(content="Acme deploys the billing service.")
    engine.remember(content="Globex ships on Tuesdays.")

    report = engine.rebuild_fts()
    assert set(report) == {"fts_before", "fts_after", "facts"}
    assert report["facts"] == 2
    assert report["fts_before"] == report["fts_after"] == 2, (
        "the index already matches the rows; nothing is dropped and rebuilt"
    )
    # and it is idempotent
    assert engine.rebuild_fts() == report
    assert engine.stats()["fact_count"] == 2


# --- timeline -----------------------------------------------------------------


def test_timeline_is_chronological_and_filtered(engine):
    engine.remember(content="Acme ships on Tuesdays.", domain="Knowledge")
    engine.remember(content="Alice Example prefers Fridays.", domain="People")

    everything = engine.timeline()
    assert [f.content for f in everything] == [
        "Acme ships on Tuesdays.",
        "Alice Example prefers Fridays.",
    ], "creation order, oldest first"
    assert all(f.id for f in everything), "StoredFact shape, as memory list needs"

    people = engine.timeline(domain="People")
    assert [f.content for f in people] == ["Alice Example prefers Fridays."]
    assert len(engine.timeline(limit=1)) == 1


def test_timeline_honours_the_date_window(engine):
    """A row created today is inside a window that starts yesterday, outside one that ends last year."""
    engine.remember(content="Acme ships on Tuesdays.")
    from em.clock import utc_now

    today = utc_now().strftime("%Y-%m-%d")
    assert len(engine.timeline(from_date=today)) == 1
    assert engine.timeline(to_date="2000-01-01") == []


# --- recall_episodes ----------------------------------------------------------


def test_recall_episodes_finds_by_text_with_v2_keys(engine):
    engine.add_episode(title="Frankfurt region review", summary="Discussed the Globex move.",
                       source_session="s1", episode_id="ep_s1_w1")
    engine.add_episode(title="Billing sync", summary="Acme rollout notes.",
                       source_session="s1", episode_id="ep_s1_w2")

    found = engine.recall_episodes("Frankfurt")
    assert len(found) == 1
    assert found[0]["title"] == "Frankfurt region review"
    assert set(found[0]) >= {"episode_id", "title", "summary", "start_ts", "created_at", "kind"}


def test_recall_episodes_honours_the_window_and_limit(engine):
    engine.add_episode(title="January planning", summary="body", source_session="s1",
                       episode_id="ep_a_w1", start_ts="2026-01-15T00:00:00.000Z")
    engine.add_episode(title="February planning", summary="body", source_session="s1",
                       episode_id="ep_b_w1", start_ts="2026-02-15T00:00:00.000Z")

    assert [e["title"] for e in engine.recall_episodes("planning",
             from_date="2026-01-01", to_date="2026-01-31")] == ["January planning"]
    assert len(engine.recall_episodes("planning", limit=1)) == 1


def test_recall_episodes_with_no_match_is_empty(engine):
    engine.add_episode(title="Frankfurt", summary="body", source_session="s1")
    assert engine.recall_episodes("zzqx nonexistent vocabulary") == []
