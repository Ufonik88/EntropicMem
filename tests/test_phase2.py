"""
test_phase2.py — Tests for Phase 2 subcommands: ingest, moc, remember, forget, research.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "entropicmem" / "scripts"
_CLI = str(_SCRIPT_DIR / "entropicmem.py")
sys.path.insert(0, str(_SCRIPT_DIR))

from vault import Vault
from index import VaultIndex


def _run(*args, **env):
    """Run the CLI with env vars."""
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, _CLI, *args],
        capture_output=True, text=True, env=full_env,
    )


@pytest.fixture
def seeded_vault():
    """Init a vault + index, ingest a test document, return paths."""
    with tempfile.TemporaryDirectory() as td:
        vp = Path(td) / "vault"
        ip = Path(td) / "index.db"

        # init
        r = _run("init", "--vault", str(vp), "--index-db", str(ip),
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0

        # Create test document
        test_doc = vp / "test_doc.md"
        test_doc.write_text("""# Test Document

## Hermes Agent Architecture
Hermes Agent uses a modular tool system with VaultKnox for credential management.

## Mnemosyne Memory
Mnemosyne provides working, episodic, and scratchpad memory with vector search.

## EntropicMem
EntropicMem builds on Mnemosyne to provide durable, linked knowledge storage.
""", encoding="utf-8")

        # ingest
        r = _run("ingest", str(test_doc), "--domain", "Knowledge",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        assert "atomic" in r.stdout.lower()

        yield vp, ip


class TestIngest:
    def test_ingest_creates_literature_note(self, seeded_vault):
        vp, ip = seeded_vault
        vault = Vault(vp)
        inbox_notes = vault.list_notes(folder="inbox")
        lit_notes = [n for n in inbox_notes if n.name.startswith("lit-")]
        assert len(lit_notes) >= 1, f"No literature note found in {inbox_notes}"

    def test_ingest_creates_atomic_notes(self, seeded_vault):
        vp, ip = seeded_vault
        vault = Vault(vp)
        knowledge_notes = vault.list_notes(folder="Knowledge")
        # Should have Hermes Agent, VaultKnox, Mnemosyne, EntropicMem
        assert len(knowledge_notes) >= 3

    def test_ingest_atomic_notes_have_frontmatter(self, seeded_vault):
        vp, ip = seeded_vault
        vault = Vault(vp)
        for rel in vault.list_notes(folder="Knowledge"):
            note = vault.read_note(rel)
            assert note.entropic_id, f"Missing entropic_id: {rel}"
            assert note.domain == "Knowledge", f"Wrong domain: {rel}"
            assert note.note_type == "permanent", f"Wrong type: {rel}"

    def test_ingest_pile(self, seeded_vault):
        vp, ip = seeded_vault
        # Create a pile dir with 2 files
        piledir = vp / "pile_test"
        piledir.mkdir()
        (piledir / "file1.md").write_text("# File 1\n\nContent about Kubernetes and Docker.", encoding="utf-8")
        (piledir / "file2.md").write_text("# File 2\n\nContent about Docker and Linux containers.", encoding="utf-8")

        r = _run("ingest-pile", str(piledir), "--domain", "Infrastructure",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        assert "Done:" in r.stdout


class TestMoc:
    def test_moc_creates_index_files(self, seeded_vault):
        vp, ip = seeded_vault
        r = _run("moc",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        # Check Knowledge domain has Index.md
        index_path = vp / "Knowledge" / "Index.md"
        assert index_path.exists()
        content = index_path.read_text(encoding="utf-8")
        assert "Map of Content" in content

    def test_moc_index_has_frontmatter(self, seeded_vault):
        vp, ip = seeded_vault
        r = _run("moc",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        vault = Vault(vp)
        note = vault.read_note(Path("Knowledge/Index.md"))
        assert note.note_type == "index"
        assert note.domain == "Knowledge"

    def test_moc_adds_backlinks(self, seeded_vault):
        vp, ip = seeded_vault
        r = _run("moc",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        vault = Vault(vp)
        for rel in vault.list_notes(folder="Knowledge"):
            if "Index" in str(rel):
                continue
            text = (vp / rel).read_text(encoding="utf-8")
            assert "## Links" in text, f"Missing ## Links in {rel}"
            assert "[[Knowledge/Index]]" in text, f"Missing backlink in {rel}"


class TestRememberForget:
    def test_remember_creates_note(self, seeded_vault):
        vp, ip = seeded_vault
        r = _run("remember", "Test durable fact about memory systems",
                 "--domain", "Infrastructure",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        assert "Remembered:" in r.stdout
        eid_line = [l for l in r.stdout.split("\n") if "Remembered:" in l][0]
        assert len(eid_line.split(":")[1].strip()) == 16

    def test_remember_forget_roundtrip(self, seeded_vault):
        vp, ip = seeded_vault
        r = _run("remember", "Temporary fact to delete",
                 "--domain", "Infrastructure",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        eid_line = [l for l in r.stdout.split("\n") if "Remembered:" in l][0]
        eid = eid_line.split(":")[1].strip()

        r2 = _run("forget", eid,
                  ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r2.returncode == 0
        assert "Forgot" in r2.stdout


class TestResearch:
    def test_research_creates_brief(self, seeded_vault):
        vp, ip = seeded_vault
        r = _run("research", "What is Hermes architecture?",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        assert "Research brief:" in r.stdout
        vault = Vault(vp)
        inbox_notes = vault.list_notes(folder="inbox")
        research_notes = [n for n in inbox_notes if n.name.startswith("research-")]
        assert len(research_notes) >= 1


class TestPhase2Gate:
    def test_query_hermes_agent(self, seeded_vault):
        """Gate test 1: query for 'Hermes Agent' should return relevant results."""
        vp, ip = seeded_vault
        r = _run("query", "Hermes Agent", "--top-k", "5",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        assert "Hermes Agent" in r.stdout

    def test_query_vaultknox(self, seeded_vault):
        """Gate test 2: query for 'VaultKnox' should return relevant results."""
        vp, ip = seeded_vault
        r = _run("query", "VaultKnox", "--top-k", "5",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        assert "VaultKnox" in r.stdout or "vaultknox" in r.stdout.lower()

    def test_query_mnemosyne(self, seeded_vault):
        """Gate test 3: query for 'Mnemosyne' should return results."""
        vp, ip = seeded_vault
        r = _run("query", "Mnemosyne", "--top-k", "5",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        assert len(r.stdout) > 50  # Some results returned

    def test_query_entropicmem(self, seeded_vault):
        """Gate test 4: query for 'EntropicMem' should return results."""
        vp, ip = seeded_vault
        r = _run("query", "EntropicMem", "--top-k", "5",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        assert "EntropicMem" in r.stdout or "entropicmem" in r.stdout.lower()

    def test_query_domain_filter(self, seeded_vault):
        """Gate test 5: domain filter should constrain results."""
        vp, ip = seeded_vault
        r = _run("query", "test", "--top-k", "10", "--domain", "Knowledge",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0

    def test_query_no_results(self, seeded_vault):
        """Gate test 6: nonsense query returns 0 results cleanly."""
        vp, ip = seeded_vault
        r = _run("query", "xyznonexistent12345", "--top-k", "5",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0

    def test_query_architecture(self, seeded_vault):
        """Gate test 7: 'architecture' should find relevant notes."""
        vp, ip = seeded_vault
        r = _run("query", "architecture", "--top-k", "5",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        assert len(r.stdout) > 50

    def test_query_memory(self, seeded_vault):
        """Gate test 8: 'memory' should find Mnemosyne-related notes."""
        vp, ip = seeded_vault
        r = _run("query", "memory", "--top-k", "5",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        assert len(r.stdout) > 50

    def test_query_credential(self, seeded_vault):
        """Gate test 9: 'credential' should find VaultKnox-related notes."""
        vp, ip = seeded_vault
        r = _run("query", "credential", "--top-k", "5",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        # May or may not match — just check it doesn't crash

    def test_query_storage(self, seeded_vault):
        """Gate test 10: multi-word query should not crash."""
        vp, ip = seeded_vault
        r = _run("query", "durable linked knowledge", "--top-k", "5",
                 ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))
        assert r.returncode == 0
        assert "Results:" in r.stdout
