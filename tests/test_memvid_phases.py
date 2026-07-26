"""Tests for Phase 7–10 modules: embeddings, temporal, pii, graph_query."""

import sqlite3
import pytest
from pathlib import Path

# ── temporal ─────────────────────────────────────────────────────────────────

from temporal import parse_temporal_query, extract_temporal_filter


class TestTemporalParsing:
    def test_last_tuesday(self):
        result = parse_temporal_query("last Tuesday")
        assert result is not None
        start, end = result
        assert start <= end

    def test_last_week(self):
        result = parse_temporal_query("last week")
        assert result is not None
        start, end = result
        assert start < end

    def test_yesterday(self):
        result = parse_temporal_query("yesterday")
        assert result is not None
        start, end = result
        assert start == end  # single day

    def test_two_weeks_ago(self):
        result = parse_temporal_query("2 weeks ago")
        assert result is not None

    def test_in_march(self):
        result = parse_temporal_query("in March")
        assert result is not None
        start, end = result
        assert "-03-" in start

    def test_no_temporal(self):
        result = parse_temporal_query("what is python")
        assert result is None

    def test_extract_preserves_query(self):
        query, date_range = extract_temporal_filter("meetings last Tuesday")
        assert "meetings" in query
        assert date_range is not None

    def test_extract_no_temporal(self):
        query, date_range = extract_temporal_filter("python decorators")
        assert query == "python decorators"
        assert date_range is None


# ── pii ──────────────────────────────────────────────────────────────────────

from pii import scan_pii, redact_pii, check_pii, PIIFinding


class TestPIIDetection:
    def test_email_detection(self):
        findings = scan_pii("contact me at john@example.com please")
        assert len(findings) >= 1
        assert any(f.pii_type == "email" for f in findings)

    def test_phone_detection(self):
        findings = scan_pii("call me on 0821234567")
        assert len(findings) >= 1
        assert any("phone" in f.pii_type for f in findings)

    def test_api_key_detection(self):
        findings = scan_pii("use sk-abc123def456ghi789jkl012mno345")
        assert len(findings) >= 1
        assert any(f.pii_type == "api_key" for f in findings)

    def test_no_pii(self):
        findings = scan_pii("the weather is nice today")
        assert len(findings) == 0

    def test_redact(self):
        redacted = redact_pii("email john@example.com now")
        assert "[REDACTED]" in redacted
        assert "john@example.com" not in redacted

    def test_check_pii_warn(self):
        result = check_pii("my email is test@test.com", mode="warn")
        assert result["has_pii"] is True
        assert result["text"] == "my email is test@test.com"  # unchanged

    def test_check_pii_redact(self):
        result = check_pii("my email is test@test.com", mode="redact")
        assert result["has_pii"] is True
        assert "test@test.com" not in result["text"]

    def test_check_pii_clean(self):
        result = check_pii("nothing sensitive here", mode="warn")
        assert result["has_pii"] is False

    def test_ip_address(self):
        findings = scan_pii("server at 192.168.1.100")
        assert any(f.pii_type == "ip_address" for f in findings)

    def test_password_pattern(self):
        findings = scan_pii("password=supersecret123")
        assert any(f.pii_type == "password" for f in findings)


# ── graph_query ──────────────────────────────────────────────────────────────

from graph_query import (
    extract_wikilinks,
    extract_links_with_context,
    init_links_schema,
    store_links,
    get_outgoing_links,
    get_incoming_links,
    get_connected_notes,
    graph_stats,
)


class TestGraphQuery:
    @pytest.fixture
    def db(self):
        conn = sqlite3.connect(":memory:")
        init_links_schema(conn)
        yield conn
        conn.close()

    def test_extract_wikilinks(self):
        links = extract_wikilinks("See [[Budget]] and [[Wedding Plan|the wedding]]")
        assert "Budget" in links
        assert "Wedding Plan" in links

    def test_extract_no_links(self):
        links = extract_wikilinks("no links here")
        assert links == []

    def test_extract_with_context(self):
        results = extract_links_with_context("Check the [[Budget]] for details")
        assert len(results) == 1
        assert results[0][0] == "Budget"
        assert "Budget" in results[0][1]

    def test_store_and_retrieve(self, db):
        store_links(db, "Finance/Budget.md", "Budget", [("Wedding", "for the wedding")])
        outgoing = get_outgoing_links(db, "Finance/Budget.md")
        assert len(outgoing) == 1
        assert outgoing[0]["target"] == "Wedding"

    def test_incoming_links(self, db):
        store_links(db, "Finance/Budget.md", "Budget", [("Wedding", "cost")])
        store_links(db, "Projects/Wedding.md", "Wedding", [("Budget", "see budget")])
        incoming = get_incoming_links(db, "Wedding")
        assert len(incoming) == 1
        assert incoming[0]["source_title"] == "Budget"

    def test_connected_notes(self, db):
        store_links(db, "A.md", "A", [("B", "link")])
        store_links(db, "B.md", "B", [("C", "link")])
        result = get_connected_notes(db, "A", depth=1)
        assert "B" in result["outgoing"]

    def test_graph_stats(self, db):
        store_links(db, "A.md", "A", [("B", "link"), ("C", "link")])
        stats = graph_stats(db)
        assert stats["total_links"] == 2
        assert stats["unique_sources"] == 1
        assert stats["unique_targets"] == 2

    def test_duplicate_links_ignored(self, db):
        store_links(db, "A.md", "A", [("B", "link")])
        store_links(db, "A.md", "A", [("B", "link again")])
        stats = graph_stats(db)
        assert stats["total_links"] == 1


# ── embeddings (unit tests without model) ───────────────────────────────────

from embeddings import (
    cosine_similarity,
    hybrid_rank,
    _vec_to_blob,
    _blob_to_vec,
    init_embeddings_schema,
    store_embedding,
    delete_embedding,
    get_embedding,
    embedding_coverage,
)


class TestEmbeddings:
    def test_cosine_similarity_identical(self):
        vec = [1.0, 0.0, 0.0]
        sim = cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 1e-6

    def test_cosine_similarity_orthogonal(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        sim = cosine_similarity(a, b)
        assert abs(sim) < 1e-6

    def test_vec_blob_roundtrip(self):
        vec = [0.1, 0.2, 0.3, 0.4]
        blob = _vec_to_blob(vec)
        restored = _blob_to_vec(blob)
        for a, b in zip(vec, restored):
            assert abs(a - b) < 1e-6

    def test_hybrid_rank_fts_only(self):
        fts = [("id1", 0.9), ("id2", 0.5)]
        result = hybrid_rank(fts, [], fts_weight=0.6, vec_weight=0.4)
        assert result[0][0] == "id1"

    def test_hybrid_rank_vec_only(self):
        vec = [("id3", 0.8)]
        result = hybrid_rank([], vec, fts_weight=0.6, vec_weight=0.4)
        assert result[0][0] == "id3"

    def test_hybrid_rank_fusion(self):
        fts = [("id1", 1.0), ("id2", 0.5)]
        vec = [("id2", 1.0), ("id3", 0.3)]
        result = hybrid_rank(fts, vec, fts_weight=0.6, vec_weight=0.4)
        # id2 appears in both, should rank high
        ids = [fid for fid, _ in result]
        assert "id2" in ids[:2]

    @pytest.fixture
    def emb_db(self):
        conn = sqlite3.connect(":memory:")
        init_embeddings_schema(conn)
        yield conn
        conn.close()

    def test_store_and_get_embedding(self, emb_db):
        vec = [0.1, 0.2, 0.3]
        store_embedding(emb_db, "fact1", vec)
        result = get_embedding(emb_db, "fact1")
        assert result is not None
        assert len(result) == 3

    def test_delete_embedding(self, emb_db):
        store_embedding(emb_db, "fact1", [0.1, 0.2])
        delete_embedding(emb_db, "fact1")
        assert get_embedding(emb_db, "fact1") is None

    def test_embedding_coverage(self, emb_db):
        # Create a facts table for coverage check
        emb_db.execute("CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY)")
        emb_db.execute("INSERT INTO facts (id) VALUES ('f1')")
        emb_db.execute("INSERT INTO facts (id) VALUES ('f2')")
        emb_db.commit()
        store_embedding(emb_db, "f1", [0.1])
        cov = embedding_coverage(emb_db)
        assert cov["total_facts"] == 2
        assert cov["embedded_facts"] == 1
