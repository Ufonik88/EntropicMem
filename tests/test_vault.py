"""
test_vault.py — Tests for vault.py, index.py, and retrieval.py.

Uses temporary directories — NEVER touches the live vault.
"""

import os
import sys
import tempfile
import pytest
from pathlib import Path

# Ensure the scripts dir is importable
_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "entropicmem" / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

from vault import (
    DEFAULT_DOMAINS,
    PROTECTED_PREFIXES,
    Note,
    Vault,
    resolve_vault_path,
)
from index import VaultIndex


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_vault():
    """Create a fresh temp vault with 10 test notes across 3 domains."""
    with tempfile.TemporaryDirectory() as td:
        vault_path = Path(td) / "vault"
        index_path = Path(td) / "index.db"
        vault = Vault(vault_path)
        vault.root.mkdir(parents=True, exist_ok=True)

        # Seed the vault files
        for fname in ["AGENTS.md", "SCHEMA.md", "index.md", "log.md"]:
            (vault.root / fname).write_text(f"# {fname}\n\nSeed file.", encoding="utf-8")

        # Create domain dirs
        for domain in DEFAULT_DOMAINS:
            (vault.root / domain).mkdir(exist_ok=True)

        # Create 10 test notes
        notes_data = [
            ("Infrastructure", "Hermes Agent Architecture",
             "Hermes Agent runs agent loop. Uses [[VaultKnox Policy Engine]] and [[Mnemosyne BEAM Memory]].",
             ["infrastructure", "hermes"]),
            ("Infrastructure", "VaultKnox Policy Engine",
             "VaultKnox evaluates security policies. Connected to [[Hermes Agent Architecture]].",
             ["infrastructure", "vaultknox", "security"]),
            ("Infrastructure", "Mnemosyne BEAM Memory",
             "Mnemosyne uses BEAM architecture. Works with [[Hermes Agent Architecture]].",
             ["infrastructure", "mnemosyne", "memory"]),
            ("Infrastructure", "EntropicMem Design",
             "EntropicMem is a durable knowledge layer. Built on [[Mnemosyne BEAM Memory]] and [[Obsidian Vault Pattern]].",
             ["infrastructure", "entropicmem"]),
            ("Infrastructure", "Obsidian Vault Pattern",
             "Vault uses wikilinks and domain folders. See [[EntropicMem Design]] for agent adaptation.",
             ["infrastructure", "vault"]),
            ("Ajax Systems", "Hub Plus 2.4GHz Migration",
             "Migration from Jeweller to Wings. Requires [[Ajax SDK Integration]] and [[Hub Plus Firmware Update]].",
             ["ajax-systems", "migration"]),
            ("Ajax Systems", "Ajax SDK Integration",
             "Ajax SDK provides REST API. Used in [[Hub Plus 2.4GHz Migration]]. Works with [[VaultKnox Policy Engine]].",
             ["ajax-systems", "sdk"]),
            ("Ajax Systems", "Hub Plus Firmware Update",
             "Firmware v6.0 enables Wings. See [[Hub Plus 2.4GHz Migration]].",
             ["ajax-systems", "firmware"]),
            ("Finance", "Budget Spreadsheet Architecture",
             "Budget uses FNB transaction exports. Documented in [[Obsidian Vault Pattern]].",
             ["finance", "budget"]),
            ("Finance", "Wedding Budget 2026",
             "Wedding tracked via [[Budget Spreadsheet Architecture]]. Key items: venue, catering.",
             ["finance", "wedding"]),
        ]

        for domain, title, body, tags in notes_data:
            path = vault.write_note(domain, title, body, tags=tags, domain=domain)

        yield vault, index_path


@pytest.fixture
def temp_vault_indexed(temp_vault):
    """Build index with edges for the temp vault."""
    vault, index_path = temp_vault
    index = VaultIndex(index_path)
    index.rebuild(vault)
    # rebuild() already handles edges via _rebuild_edges
    yield vault, index
    index.close()


# ── vault tests ─────────────────────────────────────────────────────────────

class TestVault:
    def test_resolve_path_default(self, monkeypatch):
        """resolve_vault_path should find ~/Documents/Obsidian Vault if AGENTS.md exists."""
        monkeypatch.delenv("ENTROPICMEM_VAULT_PATH", raising=False)
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        path = resolve_vault_path()
        # Should exist (our dev machine has the vault)
        assert "Obsidian Vault" in str(path) or "entropicmem" in str(path)

    def test_resolve_path_explicit(self, monkeypatch):
        """Explicit env var should win."""
        monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", "/tmp/test-vault")
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/tmp/other")
        path = resolve_vault_path()
        assert str(path) == "/tmp/test-vault"

    def test_write_and_read_note(self, temp_vault):
        vault, _ = temp_vault
        path = vault.write_note(
            "Infrastructure", "Test Note",
            "This is a test body with [[Some Link]].",
            tags=["test", "infrastructure"],
            domain="Infrastructure",
        )
        assert path.suffix == ".md"
        note = vault.read_note(path)
        assert note.title == "Test Note"
        assert "test body" in note.body
        assert note.tags == ["test", "infrastructure"]
        assert note.domain == "Infrastructure"
        assert note.agent is True
        assert note.entropic_id
        assert len(note.entropic_id) == 16

    def test_sanitize(self, temp_vault):
        vault, _ = temp_vault
        assert vault.sanitize("Hello World!") == "hello-world"
        assert vault.sanitize("  Spaces  Test  ") == "spaces-test"
        assert vault.sanitize("Special@Chars#$%") == "specialchars"

    def test_protected_prefixes(self, temp_vault):
        vault, _ = temp_vault
        for prefix in PROTECTED_PREFIXES:
            assert vault._is_protected(Path(prefix + "test.md")) is True
        assert vault._is_protected(Path("Infrastructure/test.md")) is False

    def test_write_protected_raises(self, temp_vault):
        vault, _ = temp_vault
        with pytest.raises(ValueError, match="write-protected"):
            vault.write_note("_archive", "Test", "body")

    def test_list_notes(self, temp_vault):
        vault, _ = temp_vault
        notes = vault.list_notes()
        assert len(notes) >= 10
        # Should include infrastructure notes
        infra = [n for n in notes if str(n).startswith("Infrastructure/")]
        assert len(infra) >= 5

    def test_linkify(self, temp_vault):
        vault, _ = temp_vault
        # Known titles: "Hermes Agent Architecture" exists
        text = "Hermes Agent Architecture is the core."
        result = vault.linkify(text)
        assert "[[Hermes Agent Architecture]]" in result

    def test_extract_wikilinks(self, temp_vault):
        vault, _ = temp_vault
        text = "See [[Note One]] and [[Note Two]] for details. Also [[Note One]] again."
        links = vault.extract_wikilinks(text)
        assert len(links) == 3  # includes duplicate
        assert "Note One" in links
        assert "Note Two" in links

    def test_frontmatter_roundtrip(self, temp_vault):
        vault, _ = temp_vault
        path = vault.write_note(
            "Knowledge", "Frontmatter Test",
            "Body text here.",
            tags=["test"],
            domain="Knowledge",
            note_type="literature",
            source="url",
            source_url="https://example.com",
        )
        note = vault.read_note(path)
        assert note.note_type == "literature"
        assert note.source == "url"
        assert note.source_url == "https://example.com"

    def test_delete_note(self, temp_vault):
        vault, _ = temp_vault
        path = vault.write_note("Knowledge", "To Delete", "Body", domain="Knowledge")
        assert (vault.root / path).exists()
        vault.delete_note(path)
        assert not (vault.root / path).exists()

    def test_note_to_markdown(self, temp_vault):
        vault, _ = temp_vault
        note = Note(
            path=Path("Infrastructure/test.md"),
            title="Test Title",
            body="Test body content.",
            tags=["tag1"],
            domain="Infrastructure",
            note_type="permanent",
            source="agent",
        )
        md = note.to_markdown()
        assert md.startswith("---")
        assert "title: \"Test Title\"" in md
        assert "entropic_id:" in md
        assert md.endswith("Test body content.\n")

    def test_is_safe_mode(self, temp_vault):
        vault, _ = temp_vault
        # AGENTS.md was seeded
        assert vault.is_safe_mode() is True


# ── index tests ─────────────────────────────────────────────────────────────

class TestIndex:
    def test_rebuild_counts(self, temp_vault_indexed):
        vault, index = temp_vault_indexed
        stats = index.get_stats()
        assert stats["note_count"] >= 10
        assert "Infrastructure" in stats["domains"]
        assert stats["domains"]["Infrastructure"] >= 5

    def test_fts_search(self, temp_vault_indexed):
        vault, index = temp_vault_indexed
        hits = index.search_fts("Hermes", top_k=5)
        assert len(hits) > 0
        titles = [h.title for h in hits]
        assert "Hermes Agent Architecture" in titles

    def test_fts_domain_filter(self, temp_vault_indexed):
        vault, index = temp_vault_indexed
        hits = index.search_fts("Hub Plus", domain="Ajax Systems", top_k=5)
        assert len(hits) >= 2
        for h in hits:
            assert h.domain == "Ajax Systems"

    def test_fts_edge_case_empty(self, temp_vault_indexed):
        vault, index = temp_vault_indexed
        hits = index.search_fts("nonexistentphrase12345", top_k=5)
        assert len(hits) == 0

    def test_graph_edges_exist(self, temp_vault_indexed):
        vault, index = temp_vault_indexed
        edges = index.get_graph_edges()
        assert len(edges) > 0  # at least some wikilinks detected

    def test_get_note(self, temp_vault_indexed):
        vault, index = temp_vault_indexed
        # Find the Hermes note's note_id
        hits = index.search_fts("Hermes Agent Architecture", top_k=1)
        assert len(hits) == 1
        note = index.get_note(hits[0].note_id)
        assert note is not None
        assert note["title"] == "Hermes Agent Architecture"
        assert note["domain"] == "Infrastructure"

    def test_delete_note_from_index(self, temp_vault_indexed):
        vault, index = temp_vault_indexed
        hits = index.search_fts("Wedding", top_k=1)
        assert len(hits) == 1
        note_id = hits[0].note_id
        index.delete_note(note_id)
        assert index.get_note(note_id) is None
        # Re-query
        hits2 = index.search_fts("Wedding", top_k=1)
        assert len(hits2) == 0

    def test_graph_nodes(self, temp_vault_indexed):
        vault, index = temp_vault_indexed
        nodes = index.get_graph_nodes(max_nodes=100)
        assert len(nodes) >= 10
        for node in nodes:
            assert "note_id" in node
            assert "title" in node
            assert "importance" in node

    def test_graph_nodes_domain_filter(self, temp_vault_indexed):
        vault, index = temp_vault_indexed
        nodes = index.get_graph_nodes(domain="Finance", max_nodes=10)
        assert len(nodes) >= 1
        for node in nodes:
            assert node["domain"] == "Finance"


# ── retrieval tests ─────────────────────────────────────────────────────────

class TestRetrieval:
    @pytest.fixture(autouse=True)
    def setup_import(self):
        """Ensure retrieval module is importable."""
        if _SCRIPT_DIR not in sys.path:
            sys.path.insert(0, str(_SCRIPT_DIR))

    def test_retrieve_composed(self, temp_vault_indexed):
        from retrieval import retrieve_composed
        vault, index = temp_vault_indexed
        result = retrieve_composed("Hermes", vault, index, top_k=5)
        assert result.query == "Hermes"
        assert len(result.hits) > 0
        assert result.stats["fts_hits"] > 0
        assert "Hermes Agent Architecture" in [h.title for h in result.hits]

    def test_retrieve_composed_domain(self, temp_vault_indexed):
        from retrieval import retrieve_composed
        vault, index = temp_vault_indexed
        result = retrieve_composed("Hub Plus", vault, index, top_k=5, domain="Ajax Systems")
        assert len(result.hits) >= 2
        for h in result.hits:
            assert h.domain == "Ajax Systems"

    def test_retrieve_composed_no_results(self, temp_vault_indexed):
        from retrieval import retrieve_composed
        vault, index = temp_vault_indexed
        result = retrieve_composed("xyzzy_nonexistent", vault, index, top_k=5)
        assert len(result.hits) == 0

    def test_retrieve_composed_snippets(self, temp_vault_indexed):
        from retrieval import retrieve_composed
        vault, index = temp_vault_indexed
        result = retrieve_composed("VaultKnox", vault, index, top_k=3)
        assert result.query == "VaultKnox"
        # snippets are generated from metadata body_preview
        assert isinstance(result.snippets, list)

    def test_retrieve_composed_to_text(self, temp_vault_indexed):
        from retrieval import retrieve_composed
        vault, index = temp_vault_indexed
        result = retrieve_composed("Budget", vault, index, top_k=3)
        text = result.to_text()
        assert "Budget" in text
        assert "Results:" in text


# ── CLI tests (basic smoke) ─────────────────────────────────────────────────

class TestCLI:
    def test_cli_init_dry_run(self):
        """CLI init --dry-run should not create any files."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(_SCRIPT_DIR / "entropicmem.py"),
             "init", "--vault", "/tmp/test-dryrun-vault",
             "--index-db", "/tmp/test-dryrun-index.db",
             "--dry-run"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "dry-run" in result.stdout.lower()
        assert not Path("/tmp/test-dryrun-vault").exists()

    def test_cli_version(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, str(_SCRIPT_DIR / "entropicmem.py"), "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "entropicmem" in result.stdout

    def test_cli_lint_fresh_vault(self, temp_vault_indexed):
        vault, index = temp_vault_indexed
        index.close()
        import subprocess
        result = subprocess.run(
            [sys.executable, str(_SCRIPT_DIR / "entropicmem.py"), "lint"],
            capture_output=True, text=True,
            env={**os.environ,
                 "ENTROPICMEM_VAULT_PATH": str(vault.root),
                 "ENTROPICMEM_INDEX_DB": str(index.db_path)},
        )
        # Fresh vault with no ops — should have 0 issues
        assert result.returncode == 0 or "0 issues" in result.stdout
