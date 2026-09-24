"""EM-109 (L1): stop silent fuzzy overwrites.

Fuzzy update-in-place is allowed ONLY when Jaccard >= 0.95 AND the
numbers/versions/IPs/dates are identical AND the negation tokens are
identical. Otherwise the new write inserts as a separate fact and the pair
is audited as `possible_duplicate` (both ids). An allowed fuzzy update is
audited as `fuzzy_update` with the before-content hash.
"""

import hashlib
import json

import pytest

from memory_engine import MemoryEngine


@pytest.fixture
def engine(tmp_path):
    eng = MemoryEngine(tmp_path / "m.db", profile_id="test")
    yield eng
    eng.close()


def _contents(engine):
    return [r[0] for r in engine.db.execute("SELECT content FROM facts")]


def _audits(engine, action):
    rows = engine.db.execute(
        "SELECT fact_id, detail FROM audit_log WHERE action=?", (action,)
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


class TestNoSilentOverwrite:
    def test_number_words_must_match(self, engine):
        engine.remember(
            content="The project dashboard refresh interval is set to five minutes",
            domain="Infrastructure", importance=0.8,
        )
        engine.remember(
            content="The project dashboard refresh interval is set to ten minutes",
            domain="Infrastructure", importance=0.8,
        )
        contents = _contents(engine)
        assert any("five minutes" in c for c in contents) and \
            any("ten minutes" in c for c in contents), (
            f"numeric difference was silently overwritten: {contents}"
        )

    def test_identifiers_must_match(self, engine):
        engine.remember(
            content="The primary application server hostname is set to alpha-seven.internal now",
            domain="Infrastructure", importance=0.9,
        )
        engine.remember(
            content="The primary application server hostname is set to beta-nine.internal now",
            domain="Infrastructure", importance=0.9,
        )
        contents = _contents(engine)
        assert any("alpha-seven" in c for c in contents) and \
            any("beta-nine" in c for c in contents), (
            f"identifier change was silently overwritten: {contents}"
        )

    def test_negation_must_match(self, engine):
        engine.remember(
            content="the backup service is enabled on the storage node",
            domain="Infrastructure", importance=0.8,
        )
        engine.remember(
            content="the backup service is not enabled on the storage node",
            domain="Infrastructure", importance=0.8,
        )
        contents = _contents(engine)
        assert any("not enabled" in c for c in contents) and \
            any(" is enabled" in c for c in contents), (
            f"negation flip was silently overwritten: {contents}"
        )


class TestAudits:
    def test_possible_duplicate_audited_with_both_ids(self, engine):
        engine.remember(
            content="The project dashboard refresh interval is set to five minutes",
            domain="Infrastructure", importance=0.8,
        )
        eid2 = engine.remember(
            content="The project dashboard refresh interval is set to ten minutes",
            domain="Infrastructure", importance=0.8,
        )
        audits = _audits(engine, "possible_duplicate")
        assert audits, "near-duplicate insert left no possible_duplicate audit"
        fact_id, detail = audits[0]
        assert fact_id == eid2
        ids_in_detail = json.loads(detail)
        assert eid2 in str(ids_in_detail)
        first_id = engine.db.execute(
            "SELECT id FROM facts WHERE content LIKE '%five minutes%'"
        ).fetchone()[0]
        assert first_id in str(ids_in_detail), (
            f"audit detail must carry BOTH ids: {detail}"
        )

    def test_safe_fuzzy_update_audited_with_before_hash(self, engine):
        old = "The user prefers Visual Studio Code as the primary editor for daily work."
        new = "the user prefers Visual Studio Code as the primary editor for daily work."
        eid1 = engine.remember(content=old, domain="Work", importance=0.8)
        engine.remember(content=new, domain="Work", importance=0.8)
        # Jaccard 1.0 (case-only re-format), numbers and negations identical
        # -> fuzzy update allowed
        assert _contents(engine) == [new], (
            f"safe near-identical write should update in place: {_contents(engine)}"
        )
        audits = _audits(engine, "fuzzy_update")
        assert audits, "allowed fuzzy update left no fuzzy_update audit"
        fact_id, detail = audits[0]
        assert fact_id == eid1
        expected = hashlib.sha256(old.encode("utf-8")).hexdigest()
        assert expected in detail, (
            f"fuzzy_update audit must carry the before-content hash: {detail}"
        )

    def test_no_possible_duplicate_audit_on_plain_insert(self, engine):
        engine.remember(content="the office coffee machine uses dark roast beans",
                         domain="Work", importance=0.5)
        engine.remember(content="the quarterly budget review moved to friday morning",
                         domain="Work", importance=0.5)
        assert _audits(engine, "possible_duplicate") == []
        assert _audits(engine, "fuzzy_update") == []
