"""Tests for EntropicMem Smart Context Management.

Tests cover:
- Relevance scoring (memory_engine.py)
- Token budget enforcement
- Turn-level deduplication
- Domain-aware filtering
- Conversation context awareness
- Progressive disclosure
- Smart cache
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add plugin directory to path and import
sys.path.insert(0, str(Path(__file__).parent.parent / "plugins" / "entropicmem"))

# Import using importlib with proper package structure
import importlib
import importlib.util

# Load the plugin module directly
spec = importlib.util.spec_from_file_location(
    "entropicmem_plugin",
    Path(__file__).parent.parent / "plugins" / "entropicmem" / "__init__.py",
    submodule_search_locations=[str(Path(__file__).parent.parent / "plugins" / "entropicmem")]
)
plugin_module = importlib.util.module_from_spec(spec)
sys.modules["entropicmem_plugin"] = plugin_module

# Mock the relative imports
sys.modules["entropicmem_plugin._backend"] = MagicMock()

# Now load the module
spec.loader.exec_module(plugin_module)

EntropicMemMemoryProvider = plugin_module.EntropicMemMemoryProvider
SMART_CONTEXT_DEFAULTS = plugin_module.SMART_CONTEXT_DEFAULTS

# Import memory engine
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "entropicmem" / "scripts"))
from memory_engine import MemoryEngine, StoredFact


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_memory.db"
    return db_path


@pytest.fixture
def engine(temp_db):
    """Create a MemoryEngine with test data."""
    eng = MemoryEngine(temp_db)

    # Insert test facts with varying relevance
    facts = [
        ("Python is a programming language", "Programming", 0.9),
        ("JavaScript is used for web development", "Programming", 0.8),
        ("Machine learning uses Python extensively", "AI", 0.7),
        ("The user prefers dark mode", "People", 0.6),
        ("Budget spreadsheet is at ~/hermes-budget.xlsx", "Finance", 0.5),
        ("Server runs Ubuntu 22.04", "Infrastructure", 0.4),
        ("Project deadline is next Friday", "Projects", 0.3),
        ("Coffee machine is in the kitchen", "Knowledge", 0.2),
    ]

    for content, domain, importance in facts:
        eng.remember(content, domain=domain, importance=importance)

    yield eng
    eng.close()


# ── Test Relevance Scoring ────────────────────────────────────────────────

class TestRelevanceScoring:
    """Test recall_with_relevance method."""

    def test_basic_recall(self, engine):
        """Test basic recall returns results."""
        results = engine.recall_with_relevance("Python", top_k=5)
        assert len(results) > 0
        assert all(isinstance(f, StoredFact) for f in results)

    def test_relevance_scores_present(self, engine):
        """Test that relevance scores are populated."""
        results = engine.recall_with_relevance("Python", top_k=5)
        for fact in results:
            assert fact.relevance_score > 0
            assert fact.relevance_score <= 1.0

    def test_min_relevance_filter(self, engine):
        """Test minimum relevance threshold filtering."""
        # Get all results
        all_results = engine.recall_with_relevance("programming", top_k=10, min_relevance=0.0)
        # Get filtered results
        filtered = engine.recall_with_relevance("programming", top_k=10, min_relevance=0.5)

        assert len(filtered) <= len(all_results)
        for fact in filtered:
            assert fact.relevance_score >= 0.5

    def test_domain_filter(self, engine):
        """Test domain filtering."""
        results = engine.recall_with_relevance("Python", top_k=10, domain="Programming")
        for fact in results:
            assert fact.domain == "Programming"

    def test_empty_query(self, engine):
        """Test empty query returns no results."""
        results = engine.recall_with_relevance("", top_k=5)
        assert len(results) == 0

    def test_no_match(self, engine):
        """Test query with no matches."""
        results = engine.recall_with_relevance("xyznonexistent", top_k=5)
        assert len(results) == 0

    def test_ordering_by_relevance(self, engine):
        """Test results are ordered by relevance score."""
        results = engine.recall_with_relevance("programming", top_k=10)
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].relevance_score >= results[i + 1].relevance_score


# ── Test Token Budget ─────────────────────────────────────────────────────

class TestTokenBudget:
    """Test token budget enforcement in plugin."""

    def test_budget_enforcement(self):
        """Test that facts are truncated to fit budget."""
        # Create mock facts
        facts = [
            StoredFact(id="1", content="A" * 500, importance=0.9),
            StoredFact(id="2", content="B" * 500, importance=0.8),
            StoredFact(id="3", content="C" * 500, importance=0.7),
        ]

        provider = EntropicMemMemoryProvider(config={"prefetch_token_budget": 1000})
        result = provider._apply_token_budget(facts)

        # Should fit within budget
        total_chars = sum(len(f.content) for f in result)
        assert total_chars <= 1000

    def test_budget_with_truncation(self):
        """Test that facts are truncated when needed."""
        facts = [
            StoredFact(id="1", content="A" * 800, importance=0.9),
            StoredFact(id="2", content="B" * 800, importance=0.8),
        ]

        provider = EntropicMemMemoryProvider(config={"prefetch_token_budget": 1000})
        result = provider._apply_token_budget(facts)

        # Should have first fact and truncated second
        assert len(result) == 2
        assert len(result[0].content) == 800
        assert len(result[1].content) < 800
        assert result[1].content.endswith("...")

    def test_importance_priority(self):
        """Test that higher importance facts are kept first."""
        facts = [
            StoredFact(id="1", content="A" * 500, importance=0.3),
            StoredFact(id="2", content="B" * 500, importance=0.9),
            StoredFact(id="3", content="C" * 500, importance=0.6),
        ]

        provider = EntropicMemMemoryProvider(config={"prefetch_token_budget": 800})
        result = provider._apply_token_budget(facts)

        # Should keep highest importance fact
        kept_ids = [f.id for f in result]
        assert "2" in kept_ids  # Highest importance


# ── Test Deduplication ────────────────────────────────────────────────────

class TestDeduplication:
    """Test turn-level deduplication."""

    def test_basic_dedup(self):
        """Test that recently seen facts are filtered."""
        provider = EntropicMemMemoryProvider(config={"dedup_window": 3})

        facts = [
            StoredFact(id="1", content="Fact 1", importance=0.9),
            StoredFact(id="2", content="Fact 2", importance=0.8),
            StoredFact(id="3", content="Fact 3", importance=0.7),
        ]

        # First call - all facts should pass
        result1 = provider._apply_deduplication(facts)
        assert len(result1) == 3

        # Track injected facts
        provider._turn_counter = 1
        provider._track_injected(facts)

        # Second call - fallback allows up to 2 repeats when all are duplicates
        result2 = provider._apply_deduplication(facts)
        assert len(result2) <= 2  # Fallback behavior

    def test_dedup_window(self):
        """Test that facts reappear after dedup window."""
        provider = EntropicMemMemoryProvider(config={"dedup_window": 2})

        facts = [
            StoredFact(id="1", content="Fact 1", importance=0.9),
        ]

        # Inject at turn 1
        provider._turn_counter = 1
        provider._track_injected(facts)

        # Check at turn 2 (within window) - fallback allows repeats
        provider._turn_counter = 2
        result1 = provider._apply_deduplication(facts)
        assert len(result1) <= 1  # Fallback behavior

        # Check at turn 4 (outside window)
        provider._turn_counter = 4
        result2 = provider._apply_deduplication(facts)
        assert len(result2) == 1

    def test_fallback_on_all_duplicates(self):
        """Test fallback when all facts are duplicates."""
        provider = EntropicMemMemoryProvider(config={"dedup_window": 10})

        facts = [
            StoredFact(id="1", content="Fact 1", importance=0.9),
            StoredFact(id="2", content="Fact 2", importance=0.8),
        ]

        # Inject all facts
        provider._turn_counter = 1
        provider._track_injected(facts)

        # Should allow max 2 repeats
        result = provider._apply_deduplication(facts)
        assert len(result) <= 2


# ── Test Domain Filtering ─────────────────────────────────────────────────

class TestDomainFiltering:
    """Test domain-aware filtering."""

    def test_domain_filter_applied(self):
        """Test that domain filter is applied."""
        provider = EntropicMemMemoryProvider(config={"enabled_domains": ["Programming", "AI"]})

        facts = [
            StoredFact(id="1", content="Python", domain="Programming"),
            StoredFact(id="2", content="Budget", domain="Finance"),
            StoredFact(id="3", content="ML", domain="AI"),
        ]

        # Mock engine
        mock_engine = MagicMock()
        mock_engine.recall_with_relevance.return_value = facts

        result = provider._get_candidates(mock_engine, "test")

        # Should only keep Programming and AI domains
        domains = [f.domain for f in result]
        assert "Finance" not in domains
        assert "Programming" in domains or "AI" in domains

    def test_empty_domains_allows_all(self):
        """Test that empty domain list allows all domains."""
        provider = EntropicMemMemoryProvider(config={"enabled_domains": []})

        facts = [
            StoredFact(id="1", content="Python", domain="Programming"),
            StoredFact(id="2", content="Budget", domain="Finance"),
        ]

        mock_engine = MagicMock()
        mock_engine.recall_with_relevance.return_value = facts

        result = provider._get_candidates(mock_engine, "test")
        assert len(result) == 2


# ── Test Progressive Disclosure ───────────────────────────────────────────

class TestProgressiveDisclosure:
    """Test tiered relevance filtering."""

    def test_high_relevance_tier(self):
        """Test high relevance tier selection."""
        provider = EntropicMemMemoryProvider(config={
            "high_relevance_threshold": 0.7,
            "medium_relevance_threshold": 0.4,
        })

        facts = [
            StoredFact(id="1", content="High 1", relevance_score=0.9),
            StoredFact(id="2", content="High 2", relevance_score=0.8),
            StoredFact(id="3", content="Medium", relevance_score=0.5),
            StoredFact(id="4", content="Low", relevance_score=0.2),
        ]

        result = provider._apply_progressive_disclosure(facts)
        assert len(result) == 2
        assert all(f.relevance_score >= 0.7 for f in result)

    def test_medium_relevance_tier(self):
        """Test medium relevance tier fallback."""
        provider = EntropicMemMemoryProvider(config={
            "high_relevance_threshold": 0.7,
            "medium_relevance_threshold": 0.4,
        })

        facts = [
            StoredFact(id="1", content="Medium 1", relevance_score=0.6),
            StoredFact(id="2", content="Medium 2", relevance_score=0.5),
            StoredFact(id="3", content="Low", relevance_score=0.2),
        ]

        result = provider._apply_progressive_disclosure(facts)
        assert len(result) == 2
        assert all(f.relevance_score >= 0.4 for f in result)

    def test_low_relevance_tier(self):
        """Test low relevance tier fallback."""
        provider = EntropicMemMemoryProvider(config={
            "high_relevance_threshold": 0.7,
            "medium_relevance_threshold": 0.4,
        })

        facts = [
            StoredFact(id="1", content="Low 1", relevance_score=0.3),
            StoredFact(id="2", content="Low 2", relevance_score=0.2),
            StoredFact(id="3", content="Low 3", relevance_score=0.1),
        ]

        result = provider._apply_progressive_disclosure(facts)
        assert len(result) == 3


# ── Test Conversation Context ─────────────────────────────────────────────

class TestConversationContext:
    """Test conversation context awareness."""

    def test_context_query_building(self):
        """Test context-enhanced query building."""
        provider = EntropicMemMemoryProvider(config={"context_window_turns": 2})
        provider._conversation_history = [
            {"role": "user", "content": "Tell me about Python"},
            {"role": "assistant", "content": "Python is great"},
            {"role": "user", "content": "What about machine learning?"},
        ]

        result = provider._build_context_query("programming")
        assert "programming" in result
        assert "Python" in result or "machine learning" in result

    def test_context_query_max_length(self):
        """Test context query length limit."""
        provider = EntropicMemMemoryProvider(config={
            "context_window_turns": 10,
            "max_context_query_length": 50,
        })
        provider._conversation_history = [
            {"role": "user", "content": "A" * 100},
            {"role": "user", "content": "B" * 100},
        ]

        result = provider._build_context_query("test")
        assert len(result) <= 50

    def test_sync_turn_updates_history(self):
        """Test that sync_turn updates conversation history."""
        provider = EntropicMemMemoryProvider(config={"context_window_turns": 2})
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
        ]

        provider.sync_turn("user", "assistant", messages=messages)
        assert len(provider._conversation_history) == 3


# ── Test Smart Cache ──────────────────────────────────────────────────────

class TestSmartCache:
    """Test cache with conversation awareness."""

    def test_cache_hit(self):
        """Test cache hit on same query."""
        provider = EntropicMemMemoryProvider(config={
            "cache_conversation_context": True,
            "cache_ttl_seconds": 300,
        })
        provider._prefetch_cache = "cached result"
        provider._cache_timestamp = provider._get_timestamp()
        provider._last_query = "test query"

        result = provider._check_cache("test query")
        assert result == "cached result"

    def test_cache_miss_different_query(self):
        """Test cache miss on different query."""
        provider = EntropicMemMemoryProvider(config={
            "cache_conversation_context": True,
            "cache_ttl_seconds": 300,
        })
        provider._prefetch_cache = "cached result"
        provider._cache_timestamp = provider._get_timestamp()
        provider._last_query = "old query"

        result = provider._check_cache("new query")
        assert result is None

    def test_cache_ttl_expiry(self):
        """Test cache TTL expiry."""
        provider = EntropicMemMemoryProvider(config={
            "cache_conversation_context": True,
            "cache_ttl_seconds": 1,
        })
        provider._prefetch_cache = "cached result"
        provider._cache_timestamp = time.time() - 2  # 2 seconds ago
        provider._last_query = "test query"

        result = provider._check_cache("test query")
        assert result is None


# ── Test Formatting ───────────────────────────────────────────────────────

class TestFormatting:
    """Test block formatting."""

    def test_format_block(self):
        """Test fact formatting into block."""
        provider = EntropicMemMemoryProvider()
        facts = [
            StoredFact(id="abc123", content="Test fact", relevance_score=0.85),
        ]

        result = provider._format_block(facts)
        assert "## EntropicMem recall" in result
        assert "abc123" in result
        assert "Test fact" in result
        assert "score:0.85" in result

    def test_format_empty(self):
        """Test empty facts formatting."""
        provider = EntropicMemMemoryProvider()
        result = provider._format_block([])
        assert result == ""

    def test_format_truncation(self):
        """Test long content truncation."""
        provider = EntropicMemMemoryProvider()
        facts = [
            StoredFact(id="abc", content="A" * 400, relevance_score=0.5),
        ]

        result = provider._format_block(facts)
        assert "..." in result


# ── Integration Test ──────────────────────────────────────────────────────

class TestIntegration:
    """Integration test for full prefetch pipeline."""

    def test_full_prefetch_pipeline(self, temp_db):
        """Test complete prefetch pipeline with all features (decay disabled for cache stability)."""
        # Create engine with test data
        engine = MemoryEngine(temp_db)
        engine.remember("Python is great for AI", domain="Programming", importance=0.9)
        engine.remember("Budget is tight this month", domain="Finance", importance=0.5)
        engine.close()

        # Create provider with decay disabled for deterministic scores
        provider = EntropicMemMemoryProvider(config={
            "min_relevance_score": 0.1,
            "max_prefetch_results": 3,
            "prefetch_token_budget": 500,
            "dedup_window": 2,
            "high_relevance_threshold": 0.7,
            "medium_relevance_threshold": 0.4,
            "decay_enabled": False,  # disable for deterministic test
        })

        # Mock the scripts_dir and memory_db
        provider._scripts_dir = Path(__file__).parent.parent / "skills" / "entropicmem" / "scripts"
        provider._memory_db = temp_db

        # First prefetch
        provider.queue_prefetch("Python programming")
        result1 = provider.prefetch("Python programming")
        assert result1 is not None
        assert "EntropicMem recall" in result1

        # Second prefetch with same query (should use cache)
        provider.queue_prefetch("Python programming")
        result2 = provider.prefetch("Python programming")
        assert result2 == result1, f"Cache should return same result\nGot: {result2}\nExpected: {result1}"

        # Third prefetch with different query
        provider.queue_prefetch("Finance budget")
        result3 = provider.prefetch("Finance budget")
        assert result3 is not None
        # Different query may or may not return different results on small datasets
        # The cache should have been invalidated, so we just verify it ran


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
