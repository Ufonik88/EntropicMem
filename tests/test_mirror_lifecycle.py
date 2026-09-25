"""EM-110 (L3): mirror built-in replace/remove.

on_memory_write must follow the built-in memory tool's full lifecycle:
add → replace → remove leaves 0 stale mirrors. replace/remove locate the
mirror by make_id(previous_content), falling back to a substring match of
old_text against facts tagged 'mirrored'. Writes with
write_origin == "background_review" are skipped unless
mirror.background_review is enabled.
"""

import pytest
from fake_host import FakeHost

A = "The user prefers window seats on flights"
B = "The user prefers aisle seats on flights"


@pytest.fixture
def provider(make_provider, home_a):
    provider = make_provider()
    host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
    host.start()
    yield provider
    host.shutdown()


def _mirrored(provider):
    engine, err = provider._memory_engine()
    assert err is None, err
    with engine:
        rows = engine.db.execute(
            "SELECT content, tags FROM facts WHERE tags LIKE '%mirrored%'"
        ).fetchall()
    return [(r[0], r[1] or "") for r in rows]


class TestMirrorLifecycle:
    def test_add_creates_mirror(self, provider):
        provider.on_memory_write("add", "user", A)
        rows = _mirrored(provider)
        assert any(A in c for c, _ in rows), f"no mirror created: {rows}"

    def test_replace_updates_mirror_no_stale(self, provider):
        provider.on_memory_write("add", "user", A)
        provider.on_memory_write(
            "replace", "user", B, metadata={"previous_content": A},
        )
        rows = _mirrored(provider)
        assert any(B in c for c, _ in rows), f"replacement not mirrored: {rows}"
        assert not any(A in c for c, _ in rows), f"stale mirror left behind: {rows}"

    def test_replace_falls_back_to_substring_match(self, provider):
        provider.on_memory_write("add", "user", A)
        # no previous_content — only an old_text excerpt
        provider.on_memory_write(
            "replace", "user", B,
            metadata={"old_text": "window seats on flights"},
        )
        rows = _mirrored(provider)
        assert any(B in c for c, _ in rows), f"substring fallback missed: {rows}"
        assert not any(A in c for c, _ in rows), f"stale mirror left behind: {rows}"

    def test_remove_forgets_mirror(self, provider):
        provider.on_memory_write("add", "user", A)
        provider.on_memory_write(
            "remove", "user", "", metadata={"previous_content": A},
        )
        rows = _mirrored(provider)
        assert rows == [], f"mirror survived remove: {rows}"

    def test_remove_without_match_leaves_others(self, provider):
        provider.on_memory_write("add", "user", A)
        provider.on_memory_write(
            "remove", "user", "", metadata={"previous_content": "something unrelated entirely"},
        )
        rows = _mirrored(provider)
        assert any(A in c for c, _ in rows), f"unrelated remove deleted a mirror: {rows}"

    def test_add_replace_remove_zero_stale_mirrors(self, provider):
        # AC: full cycle leaves 0 stale mirrors
        provider.on_memory_write("add", "user", A)
        provider.on_memory_write("replace", "user", B, metadata={"previous_content": A})
        provider.on_memory_write("remove", "user", "", metadata={"previous_content": B})
        assert _mirrored(provider) == []
        engine, err = provider._memory_engine()
        assert err is None, err
        with engine:
            n = engine.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        assert n == 0, f"stale rows after add→replace→remove: {n}"


class TestBackgroundReviewGate:
    def test_background_review_skipped_by_default(self, provider):
        provider.on_memory_write(
            "add", "user", A, metadata={"write_origin": "background_review"},
        )
        assert _mirrored(provider) == [], (
            "background_review write mirrored despite default-off gate"
        )

    def test_background_review_allowed_when_enabled(self, make_provider, home_a):
        provider = make_provider({"mirror": {"background_review": True}})
        host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
        host.start()
        provider.on_memory_write(
            "add", "user", A, metadata={"write_origin": "background_review"},
        )
        rows = _mirrored(provider)
        host.shutdown()
        assert any(A in c for c, _ in rows), f"opt-in mirror missing: {rows}"
