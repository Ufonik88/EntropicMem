"""EM-104 (R2): shared FTS5 query builder — term quality and safe quoting.

Pins the build_fts_query() rules:
  1. English stopwords live in scripts/stopwords.py (frozenset STOPWORDS).
  2. Stopword tokens and tokens shorter than 2 characters are dropped.
  3. The prefix '*' goes only on tokens of 4+ characters; shorter tokens are
     exact terms.
  4. When every token was dropped (e.g. "who am I"), the raw tokens come back
     with rules 2-3's length rules applied as far as possible without
     emptying the query.
  5. The max_terms cap selects non-stopwords first, then longest first.
  6. Every term is safely quoted for FTS5 (double quotes, embedded quotes
     doubled) so user punctuation can never break MATCH syntax.
  7. '' (no terms at all) means 'no matches': the recall paths return [] and
     never fall through to a match-everything sweep.
"""

import re
import sqlite3

import pytest

from memory_engine import MemoryEngine, build_fts_query
from stopwords import STOPWORDS

# Pinned reference output (EM-104/EM-105): "what"/"is"/"a"/"to"/"do"/"it" are
# stopwords; terms of 3+ chars get the prefix star ("good"*, "way"*),
# longest-first order.
PINNED_REFERENCE_QUERY = '{title tags body}: "good"* OR {title tags body}: "way"*'

_TERM_RE = re.compile(r'\{[^}]+\}: "([^"]|"")*"\*?')


@pytest.fixture
def engine(tmp_path):
    eng = MemoryEngine(tmp_path / "memory.db")
    yield eng
    eng.close()


class TestBuildFtsQuery:
    def test_pinned_string_for_reference_query(self):
        assert build_fts_query("what is a good way to do it") == PINNED_REFERENCE_QUERY

    def test_stopwords_and_short_tokens_are_dropped(self):
        q = build_fts_query("zzqx nonsense a")
        assert '"nonsense"*' in q and '"zzqx"*' in q
        assert '"a"' not in q  # 1-char stopword never becomes a term
        assert ": *" not in q  # never a bare star term

    def test_prefix_star_only_for_long_tokens(self):
        q = build_fts_query("hi said")
        assert '"hi"' in q and '"hi"*' not in q  # 2 chars -> exact term
        assert '"said"*' in q  # 4 chars -> prefix term

    def test_all_stopword_fallback_is_usable(self):
        # "who am I" drops to nothing as stopwords -> raw tokens come back,
        # then the length rules drop only "I" (would empty nothing else).
        assert build_fts_query("who am I") == '{title tags body}: "who"* OR {title tags body}: "am"'

    def test_max_terms_cap_prefers_non_stopwords_then_longest(self):
        # long stopwords ("through", "against") must not crowd out real terms
        assert build_fts_query("through against cat dog", max_terms=2) == \
            '{title tags body}: "cat"* OR {title tags body}: "dog"*'
        # and among real terms the longest (most discriminative) win
        assert build_fts_query("algorithm banana cherry", max_terms=2) == \
            '{title tags body}: "algorithm"* OR {title tags body}: "banana"*'

    def test_punctuation_never_breaks_match_syntax(self):
        hostile = [
            'he said "hi',
            'a"b:c (d^) *',
            "(((",
            "NEAR/2 (a b",
            "AND OR NOT",
            "100% _under_",
            '^cat: "x"',
        ]
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE VIRTUAL TABLE t USING fts5(title, tags, body, "
            "tokenize='porter unicode61')"
        )
        conn.execute("INSERT INTO t VALUES ('hello', '', 'hello world')")
        try:
            for q in hostile:
                expr = build_fts_query(q)
                if not expr:
                    continue  # rule 7: '' means 'no matches'; callers skip MATCH
                try:
                    conn.execute("SELECT * FROM t WHERE t MATCH ?", (expr,)).fetchall()
                except sqlite3.OperationalError as exc:  # pragma: no cover
                    pytest.fail(f"build_fts_query({q!r}) -> {expr!r} broke MATCH: {exc}")
        finally:
            conn.close()

    def test_every_term_is_a_safely_quoted_phrase(self):
        for q in ('he said "hi', "who am I", "zzqx nonsense a"):
            for term in build_fts_query(q).split(" OR "):
                assert _TERM_RE.fullmatch(term), f"unsafe FTS term: {term!r}"

    def test_empty_result_for_termless_query(self):
        assert build_fts_query("") == ""
        assert build_fts_query("(((") == ""
        assert STOPWORDS and "what" in STOPWORDS and "good" not in STOPWORDS


class TestRecallTreatsEmptyBuildAsNoMatches:
    def test_junk_query_returns_no_trivial_matches(self, engine):
        engine.remember("The user works at a large company as a manager.", domain="Work")
        # sanity: the seed really is searchable
        assert engine.recall("company manager")
        # the junk query must not trivially match it
        assert engine.recall("zzqx nonsense a") == []
        assert engine.recall_with_relevance("zzqx nonsense a") == []

    def test_termless_query_never_matches_everything(self, engine):
        engine.remember("An ordinary fact about widget throughput.", domain="Work")
        assert engine.recall("(((") == []
        assert engine.recall_with_relevance("(((") == []
        assert engine.recall("") == []  # LIKE '%%' sweep is exactly the bug
        # even when the term-less query would substring-match: punctuation
        # is not a search term, '' means 'no matches' (rule 7)
        engine.remember("bracketed (gamma) content", domain="Work")
        assert engine.recall("()") == []
        assert engine.recall_with_relevance("()") == []
