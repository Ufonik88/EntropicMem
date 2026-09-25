"""EM-107 (R6/R7): prefetch packing fixes.

(a) ``context_query_mode`` default ``current``: the enhanced query must not
    concatenate prior user turns (F-006); ``concat`` keeps the old behaviour.
(b) ``progressive_disclosure`` default off: a full high-relevance set is never
    collapsed to 2 (F-007/R7).
(c) Token budget sorted by combined score; never truncates mid-fact.
(d) No second 300-char truncation in ``_format_block``.
(e) Each bullet carries ``(domain · YYYY-MM-DD)``.
"""

from plugins.entropicmem import EntropicMemMemoryProvider

from memory_engine import StoredFact


def _fact(i, content, *, importance=0.5, relevance=0.9, domain="Work",
          created="2026-09-01T10:00:00+00:00"):
    return StoredFact(
        id=f"{i:016x}", content=content, importance=importance,
        domain=domain, created_at=created, relevance_score=relevance,
    )


class TestContextQueryMode:
    def test_default_current_ignores_history(self):
        p = EntropicMemMemoryProvider(config={})
        p._conversation_history = [
            {"role": "user", "content": "earlier question about kubernetes"},
            {"role": "assistant", "content": "answer"},
        ]
        assert p._build_context_query("what is the deadline") == "what is the deadline"

    def test_concat_keeps_old_behaviour(self):
        p = EntropicMemMemoryProvider(config={"context_query_mode": "concat"})
        p._conversation_history = [
            {"role": "user", "content": "earlier question about kubernetes"},
            {"role": "assistant", "content": "answer"},
        ]
        out = p._build_context_query("what is the deadline")
        assert "kubernetes" in out and "what is the deadline" in out

    def test_current_needs_no_history(self):
        p = EntropicMemMemoryProvider(config={})
        assert p._build_context_query("plain") == "plain"


class TestProgressiveDisclosure:
    def test_default_off_keeps_full_set(self):
        p = EntropicMemMemoryProvider(config={})
        facts = [_fact(i, f"fact {i}", relevance=0.95) for i in range(5)]
        assert len(p._apply_progressive_disclosure(facts)) == 5

    def test_enabled_still_caps_high_at_2(self):
        p = EntropicMemMemoryProvider(config={"progressive_disclosure": True})
        facts = [_fact(i, f"fact {i}", relevance=0.95) for i in range(5)]
        assert len(p._apply_progressive_disclosure(facts)) == 2


class TestTokenBudget:
    def test_sorted_by_combined_not_importance(self):
        p = EntropicMemMemoryProvider(config={"prefetch_token_budget": 1000})
        low_imp_high_rel = _fact(1, "a" * 10, importance=0.1, relevance=0.99)
        high_imp_low_rel = _fact(2, "b" * 10, importance=0.9, relevance=0.30)
        out = p._apply_token_budget([high_imp_low_rel, low_imp_high_rel])
        assert [f.id for f in out] == [low_imp_high_rel.id, high_imp_low_rel.id]

    def test_never_truncates_mid_fact_and_continues(self):
        p = EntropicMemMemoryProvider(config={"prefetch_token_budget": 120})
        big = _fact(1, "word " * 40, relevance=0.99)  # 200 chars > budget
        small = _fact(2, "tiny fact", relevance=0.5)
        out = p._apply_token_budget([big, small])
        # the oversized fact is skipped whole, never cut mid-fact; the small
        # one still packs
        assert [f.id for f in out] == [small.id]
        assert all(len(f.content) in (len("word " * 40), len("tiny fact")) for f in out)


class TestFormatBlock:
    def test_no_300_char_truncation(self):
        p = EntropicMemMemoryProvider(config={})
        long_content = ("neque porro quisquam est qui dolorem ipsum quia "
                        "dolor sit amet ") * 6  # ~420 chars
        block = p._format_block([_fact(1, long_content)])
        assert long_content in block
        assert "..." not in block

    def test_line_carries_domain_and_date(self):
        p = EntropicMemMemoryProvider(config={})
        block = p._format_block([
            _fact(1, "hello world", domain="People", created="2026-09-01T10:00:00+00:00"),
        ])
        assert "(People · 2026-09-01)" in block

    def test_bullet_never_ends_mid_word(self):
        p = EntropicMemMemoryProvider(config={})
        # content deliberately ends mid-word: the line must still contain the
        # whole fact body and close with the metadata suffix, never a cut word
        content = "antidisestablishmentarianism" * 12
        block = p._format_block([_fact(1, content, domain="Work")])
        line = block.splitlines()[1]
        assert content in line
        # the line closes with a complete metadata suffix (provenance paren
        # and/or score tag), never a cut word
        assert "(Work · " in line
        assert line.rstrip().endswith((")", "]"))
