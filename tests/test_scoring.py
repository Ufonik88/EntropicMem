"""EM-105 (R1/R4): absolute relevance scoring — lexical coverage + rank bonus.

Replaces min-max normalisation (which gave junk queries relevance 1.0) with
an absolute, explainable score:

    relevance = 0.75 * coverage(query_terms, text) + 0.25 * rank_bonus
    rank_bonus = 1 / (1 + 0.15 * bm25_rank_index)
    combined = clip(relevance * decay_factor * (0.85 + 0.3 * importance), 0, 1)
"""

from memory_engine import coverage, coverage_terms


class TestCoverage:
    def test_full_match(self):
        assert coverage(["pasta"], "The user has a pasta allergy") == 1.0

    def test_partial_match_is_absolute(self):
        terms = ["homemade", "italian", "pasta", "recipe", "ideas"]
        assert coverage(terms, "The user has a pasta allergy") == 0.2

    def test_stemmed_match(self):
        assert coverage(["ideas"], "The user has one idea") == 1.0
        assert coverage(["buses"], "the bus schedule") == 1.0
        assert coverage(["quickly"], "a quick decision") == 1.0

    def test_case_insensitive(self):
        assert coverage(["PASTA"], "pasta") == 1.0

    def test_no_terms_is_zero(self):
        assert coverage([], "anything at all") == 0.0

    def test_unrelated_text_scores_zero(self):
        assert coverage(["kubernetes", "deployment"], "The user likes tea") == 0.0


class TestCoverageTerms:
    def test_stopwords_and_short_tokens_dropped(self):
        assert coverage_terms("what is a good way to do it") == ["good", "way"]

    def test_empty_query_gives_no_terms(self):
        assert coverage_terms("   ") == []
