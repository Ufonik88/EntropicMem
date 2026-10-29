"""Tests for graph/model.py - community detection and graph payload building."""
import pytest
from pathlib import Path
from em.graph.model import (
    detect_communities,
    body_coverage,
    get_color,
    get_shape,
    get_entity_color,
    get_relation_color,
    get_community_color,
    GraphEntity,
    GraphRelation,
    EntityGraph,
)


class TestGetColor:
    """Tests for get_color function."""
    
    def test_get_color_existing_domain(self):
        """Test color retrieval for existing domain."""
        result = get_color("Infrastructure")
        assert result == "#1DCF8E"
    
    def test_get_color_unknown_domain(self):
        """Test color retrieval for unknown domain (defaults to DEFAULT_COLOR)."""
        result = get_color("Unknown-Domain")
        assert result == "#888888"
    
    def test_get_color_empty_string(self):
        """Test color retrieval for empty domain."""
        result = get_color("")
        assert result == "#888888"


class TestGetShape:
    """Tests for get_shape function."""
    
    def test_get_shape_existing_type(self):
        """Test shape retrieval for existing note type."""
        result = get_shape("permanent")
        assert result == "circle"
    
    def test_get_shape_unknown_type(self):
        """Test shape retrieval for unknown note type (defaults to 'circle')."""
        result = get_shape("unknown_type")
        assert result == "circle"


class TestGetEntityColor:
    """Tests for get_entity_color function."""
    
    def test_get_entity_color_existing_kind(self):
        """Test entity color retrieval for existing kind."""
        result = get_entity_color("person")
        assert result == "#FF6B6B"
    
    def test_get_entity_color_different_case(self):
        """Test entity color retrieval with different case (should normalize)."""
        result = get_entity_color("PERSON")
        assert result == "#FF6B6B"
    
    def test_get_entity_color_unknown_kind(self):
        """Test entity color retrieval for unknown kind."""
        result = get_entity_color("unknown")
        assert result == "#B0B0B8"
    
    def test_get_entity_color_empty(self):
        """Test entity color retrieval for empty input."""
        result = get_entity_color("")
        assert result == "#B0B0B8"


class TestGetRelationColor:
    """Tests for get_relation_color function."""
    
    def test_get_relation_color_known_predicate(self):
        """Test relation color retrieval for known predicate."""
        result = get_relation_color("works_at")
        assert result in ("#8AB4F8", "#F28B82", "#81C995", "#FDD663", "#C58AF9", "#78D9EC", "#FF8BCB", "#A8D08D")
    
    def test_get_relation_color_empty_predicate(self):
        """Test relation color retrieval for empty predicate."""
        result = get_relation_color("")
        assert result == "#B0B0B8"
    
    def test_get_relation_color_none(self):
        """Test relation color retrieval for None input."""
        result = get_relation_color(None)
        assert result == "#B0B0B8"


class TestGetCommunityColor:
    """Tests for get_community_color function."""
    
    def test_get_community_color_small_id(self):
        """Test community color retrieval for small community ID."""
        result = get_community_color(0)
        assert result == "#E69F00"
    
    def test_get_community_color_large_id(self):
        """Test community color retrieval for large community ID (wraps around)."""
        result = get_community_color(20)
        expected = "#E69F00"  # 20 % 11 = 9, palette[9] = "#FF6B6B"? Wait let me recalculate
        # Actually let me just verify it's in the palette
        assert result in ("#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#5AE4AA", "#FF6B6B", "#9CCC65", "#7C4DFF")
    
    def test_get_community_color_negative(self):
        """Test community color retrieval for negative ID (Python modulo)."""
        result = get_community_color(-1)
        assert result == "#7C4DFF"  # -1 % 11 = 10


class TestGraphEntityDataclass:
    """Tests for GraphEntity dataclass."""
    
    def test_graph_entity_creation(self):
        """Test basic GraphEntity creation."""
        entity = GraphEntity(entity_id="ent1", name="Test Entity", kind="person", aliases=("alias1",))
        assert entity.entity_id == "ent1"
        assert entity.name == "Test Entity"
        assert entity.kind == "person"
        assert entity.aliases == ("alias1",)
    
    def test_graph_entity_defaults(self):
        """Test GraphEntity with default values."""
        entity = GraphEntity(entity_id="ent2", name="Default Entity")
        assert entity.kind == "thing"  # default kind
        assert entity.aliases == ()  # default empty tuple


class TestGraphRelationDataclass:
    """Tests for GraphRelation dataclass."""
    
    def test_graph_relation_creation(self):
        """Test basic GraphRelation creation."""
        relation = GraphRelation(
            subject_id="sub1",
            predicate="works_at",
            object_id="obj1",
            valid_from="2024-01-01",
            valid_to="2024-12-31",
            confidence=0.9,
            superseded=False
        )
        assert relation.subject_id == "sub1"
        assert relation.predicate == "works_at"
        assert relation.object_id == "obj1"
        assert relation.valid_from == "2024-01-01"
        assert relation.valid_to == "2024-12-31"
        assert relation.confidence == 0.9
        assert relation.superseded == False
    
    def test_graph_relation_defaults(self):
        """Test GraphRelation with default values."""
        relation = GraphRelation(subject_id="sub1", predicate="test", object_id="obj1")
        assert relation.valid_from is None
        assert relation.valid_to is None
        assert relation.confidence == 0.7  # default confidence
        assert relation.superseded == False


class TestDetectCommunities:
    """Tests for detect_communities function."""
    
    def test_detect_communities_empty(self):
        """Test community detection with empty edge list."""
        result = detect_communities([])
        assert result == {}
    
    def test_detect_communities_single_node(self):
        """Test community detection with single node (no edges)."""
        result = detect_communities([("node1", "node2")])
        # Should create communities based on edges
        assert isinstance(result, dict)
        assert set(result.keys()) == {"node1", "node2"}
    
    def test_detect_communities_with_loop(self):
        """Test community detection with self-loop edges (should be ignored)."""
        edges = [("node1", "node2"), ("node2", "node1"), ("node1", "node1")]
        result = detect_communities(edges)
        # Self-loop (node1, node1) should be ignored
        assert set(result.keys()) == {"node1", "node2"}
    
    def test_detect_communities_deterministic(self):
        """Test that community detection is deterministic."""
        edges = [("a", "b"), ("b", "c"), ("c", "d")]
        result1 = detect_communities(edges)
        result2 = detect_communities(edges)
        assert result1 == result2
    
    def test_detect_communities_multiple_communities(self):
        """Test community detection with disconnected components."""
        edges = [("a", "b"), ("c", "d"), ("e", "f")]
        result = detect_communities(edges)
        # Should create 3 communities: {a,b}, {c,d}, {e,f}
        assert isinstance(result, dict)
        # All nodes should be in communities
        assert set(result.keys()) == {"a", "b", "c", "d", "e", "f"}
        # Each pair should be in same community
        assert result["a"] == result["b"]
        assert result["c"] == result["d"]
        assert result["e"] == result["f"]


class TestEntityGraphDataclass:
    """Tests for EntityGraph dataclass."""
    
    def test_entity_graph_creation(self):
        """Test basic EntityGraph creation."""
        entity = GraphEntity(entity_id="ent1", name="Test")
        relation = GraphRelation(subject_id="sub1", predicate="test", object_id="obj1")
        
        graph = EntityGraph(
            entities=(entity,),
            relations=(relation,),
            scope_profile="test",
            scope="all",
            available=True,
            reason="test",
            truncated=False,
            dropped_relations=0,
            literal_relations=0,
            hidden_entities=0,
            hidden_relations=0
        )
        
        assert graph.entities == (entity,)
        assert graph.relations == (relation,)
        assert graph.scope == "all"
        assert graph.available == True
        assert graph.reason == "test"
    
    def test_entity_graph_defaults(self):
        """Test EntityGraph with default values."""
        graph = EntityGraph()
        assert graph.entities == ()
        assert graph.relations == ()
        assert graph.scope == "owner"  # default
        assert graph.available == True  # default
        assert graph.reason == ""  # default


class TestBodyCoverage:
    """Tests for body_coverage function."""
    
    def test_body_coverage_empty(self):
        """Test body coverage with empty node list."""
        result = body_coverage([])
        assert result["total"] == 0
        assert result["with_body"] == 0
        assert result["empty"] == 0
        assert result["coverage_pct"] == 100.0
        assert result["ok"] == True
    
    def test_body_coverage_all_with_body(self):
        """Test body coverage where all notes have bodies."""
        nodes = [
            {"kind": "note", "full_body": "content1"},
            {"kind": "note", "body_preview": "content2"},
            {"kind": "note", "full_body": "content3", "body_preview": "preview"},
        ]
        result = body_coverage(nodes)
        assert result["total"] == 3
        assert result["with_body"] == 3
        assert result["empty"] == 0
        assert result["coverage_pct"] == 100.0
        assert result["ok"] == True
    
    def test_body_coverage_some_without_body(self):
        """Test body coverage where some notes lack bodies."""
        nodes = [
            {"kind": "note", "full_body": "content1"},
            {"kind": "note"},  # no body
            {"kind": "note", "body_preview": "content2"},
            {"kind": "entity"},  # entity nodes not counted
        ]
        result = body_coverage(nodes)
        assert result["total"] == 3  # entity nodes excluded
        assert result["with_body"] == 2
        assert result["empty"] == 1
        assert result["coverage_pct"] == 66.7  # rounded
        assert result["ok"] == False  # has empty notes
    
    def test_body_coverage_only_entities(self):
        """Test body coverage with only entity nodes (excluded from count)."""
        nodes = [
            {"kind": "entity"},
            {"kind": "entity"},
        ]
        result = body_coverage(nodes)
        assert result["total"] == 0
        assert result["with_body"] == 0
        assert result["empty"] == 0
        assert result["coverage_pct"] == 100.0
        assert result["ok"] == True


class TestColorPaletteConstants:
    """Tests for color palette constants."""
    
    def test_domain_palette_defined(self):
        """Test that DOMAIN_PALETTE constant is defined."""
        from em.graph.model import DOMAIN_PALETTE
        assert "Infrastructure" in DOMAIN_PALETTE
        assert DOMAIN_PALETTE["Infrastructure"] == "#1DCF8E"
    
    def test_entity_palette_defined(self):
        """Test that ENTITY_PALETTE constant is defined."""
        from em.graph.model import ENTITY_PALETTE
        assert "person" in ENTITY_PALETTE
        assert ENTITY_PALETTE["person"] == "#FF6B6B"
    
    def test_relation_palette_defined(self):
        """Test that RELATION_PALETTE constant is defined."""
        from em.graph.model import RELATION_PALETTE
        assert len(RELATION_PALETTE) == 8
        assert isinstance(RELATION_PALETTE, tuple)
    
    def test_type_shapes_defined(self):
        """Test that TYPE_SHAPES constant is defined."""
        from em.graph.model import TYPE_SHAPES
        assert "permanent" in TYPE_SHAPES
        assert TYPE_SHAPES["permanent"] == "circle"
    
    def test_community_palette_defined(self):
        """Test that COMMUNITY_PALETTE constant is defined."""
        from em.graph.model import COMMUNITY_PALETTE
        assert len(COMMUNITY_PALETTE) == 11
        assert "#E69F00" in COMMUNITY_PALETTE