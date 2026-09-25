"""EM-112 (L5): non-destructive cadence digests.

Cadence flushes write ``ep_sess_{sid}_w{n}`` with n monotonically
increasing per session; the session-end digest is the single
``ep_sess_{sid}`` covering the tail. Digest timestamps are UTC.
"""

import time

from fake_host import FakeHost

SESSION = "sess-harness-1"  # FakeHost's session id (provider._session_id)


def _provider(make_provider, home_a, **cfg):
    cfg.setdefault("turn_cadence_flush_turns", 40)
    cfg.setdefault("turn_cadence_min_interval_sec", 0)
    provider = make_provider(cfg)
    host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
    host.start()
    return provider, host


def _episodes(provider):
    engine, err = provider._memory_engine()
    assert err is None, err
    with engine:
        rows = engine.db.execute(
            "SELECT episode_id, summary, source FROM episodes ORDER BY rowid"
        ).fetchall()
    return [tuple(r) for r in rows]


class TestNonDestructiveWaves:
    def test_100_turn_session_w1_w2_final(self, make_provider, home_a):
        # AC: 100-turn harness session with cadence 40 -> w1, w2, final episode;
        # none overwritten.
        provider, host = _provider(make_provider, home_a)
        for i in range(1, 101):
            provider.sync_turn(
                f"user line {i} about topic-{i}", f"assistant answer {i}",
                session_id=SESSION,
            )
            provider.on_turn_start(i, f"user line {i} about topic-{i}")
        provider.on_session_end([{"role": "user", "content": "closing the session now"}])
        rows = _episodes(provider)
        host.shutdown()
        ids = [r[0] for r in rows]
        assert ids == [f"ep_sess_{SESSION}_w1", f"ep_sess_{SESSION}_w2",
                       f"ep_sess_{SESSION}"], (
            f"cadence waves overwritten or mis-numbered: {ids}"
        )
        summaries = [r[1] for r in rows]
        assert len(set(summaries)) == 3, (
            f"digest rows share a summary (overwrite): {summaries}"
        )

    def test_wave_numbers_monotonic(self, make_provider, home_a):
        provider, host = _provider(
            make_provider, home_a, turn_cadence_flush_turns=2,
        )
        for i in range(1, 7):
            provider.sync_turn(f"user line {i}", f"assistant answer {i}", session_id=SESSION)
            provider.on_turn_start(i, f"user line {i}")
        rows = _episodes(provider)
        host.shutdown()
        ids = [r[0] for r in rows]
        assert ids == [f"ep_sess_{SESSION}_w1", f"ep_sess_{SESSION}_w2",
                       f"ep_sess_{SESSION}_w3"], (
            f"waves are not monotonically numbered: {ids}"
        )

    def test_session_end_id_stays_idempotent(self, make_provider, home_a):
        provider, host = _provider(make_provider, home_a)
        msgs = [{"role": "user", "content": "the final tail message of the session"}]
        provider.on_session_end(msgs)
        provider.on_session_end(msgs)
        rows = _episodes(provider)
        host.shutdown()
        ids = [r[0] for r in rows]
        assert ids == [f"ep_sess_{SESSION}"], (
            f"session-end re-fire must replace the same row, not duplicate: {ids}"
        )


class TestTimestampsUtc:
    def test_digest_timestamps_are_utc(self, make_provider, home_a):
        provider, host = _provider(make_provider, home_a)
        now = time.time()
        provider.sync_turn("hello there", "hi, how can I help?", session_id=SESSION)
        provider.on_session_end([
            {"role": "user", "content": "hello there", "timestamp": now},
            {"role": "assistant", "content": "hi, how can I help?", "timestamp": now + 5},
        ])
        engine, err = provider._memory_engine()
        assert err is None, err
        with engine:
            row = engine.db.execute(
                "SELECT start_ts, end_ts FROM episodes WHERE episode_id=?",
                (f"ep_sess_{SESSION}",),
            ).fetchone()
        host.shutdown()
        assert row is not None, "no session-end episode written"
        for ts in row:
            assert ts is None or ts.endswith("+00:00") or ts.endswith("Z"), (
                f"digest timestamp is not UTC: {ts!r}"
            )
