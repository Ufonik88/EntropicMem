"""
test_phase4.py — Tests for the standalone MemoryEngine.
"""

import hashlib
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
from memory_engine import MemoryEngine, StoredFact


def _run(*args, **env):
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, _CLI, *args],
        capture_output=True, text=True, env=full_env,
    )


@pytest.fixture
def engine():
    """Create an in-memory MemoryEngine for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)
    eng = MemoryEngine(db_path)
    yield eng
    eng.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def vault_with_engine():
    """Create a temp vault with MemoryEngine."""
    with tempfile.TemporaryDirectory() as td:
        vp = Path(td) / "vault"
        ip = Path(td) / "index.db"
        mp = Path(td) / "memory.db"
        _run("init", "--vault", str(vp), "--index-db", str(ip),
             ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))

        vault = Vault(vp)
        index = VaultIndex(ip)
        engine = MemoryEngine(mp)

        for i in range(5):
            path = vault.write_note(
                "Infrastructure", f"Engine Test Note {i}",
                f"Body for engine test {i}.",
                tags=["engine-test"], domain="Infrastructure",
            )
            note = vault.read_note(path)
            index.upsert_note(note)
            index.upsert_edges_for_note(vault, note)

        yield vault, index, engine
        index.close()
        engine.close()


class TestMemoryEngine:
    def test_remember_returns_id(self, engine):
        eid = engine.remember(content="Test fact for memory engine")
        assert len(eid) == 16

    def test_remember_deterministic(self, engine):
        content = "Test deterministic ID generation"
        eid1 = engine.remember(content=content)
        eid2 = engine.remember(content=content)
        assert eid1 == eid2

    def test_remember_different_content(self, engine):
        eid1 = engine.remember(content="Content A")
        eid2 = engine.remember(content="Content B")
        assert eid1 != eid2

    def test_recall_finds_fact(self, engine):
        engine.remember(content="A unique memory about quantum computing", domain="Knowledge")
        results = engine.recall("quantum")
        assert len(results) > 0
        assert any("quantum" in r.content for r in results)

    def test_recall_domain_filter(self, engine):
        engine.remember(content="Infrastructure fact", domain="Infrastructure")
        engine.remember(content="Finance fact", domain="Finance")
        results = engine.recall("fact", domain="Infrastructure")
        for r in results:
            assert r.domain == "Infrastructure"

    def test_forget_removes_fact(self, engine):
        eid = engine.remember(content="Fact to be forgotten")
        assert engine.forget(eid) is True
        assert engine.get_fact(eid) is None

    def test_forget_returns_false_for_missing(self, engine):
        assert engine.forget("nonexistent_id_") is False

    def test_list_facts(self, engine):
        for i in range(5):
            engine.remember(content=f"Test list fact {i}", domain="Infrastructure")
        facts = engine.list_facts(domain="Infrastructure")
        assert len(facts) >= 5

    def test_stats(self, engine):
        engine.remember(content="Stats test fact", domain="Knowledge")
        s = engine.stats()
        assert s["fact_count"] >= 1
        assert "domains" in s

    def test_project_to_vault(self, vault_with_engine):
        vault, index, engine = vault_with_engine
        engine.remember(content="A projectable fact about infrastructure", domain="Infrastructure")
        r = engine.project_to_vault(vault, index, limit=10)
        assert r["created"] >= 1

    def test_deduplication(self, engine):
        content = "Deduplication test: should not create duplicates"
        eid1 = engine.remember(content=content)
        eid2 = engine.remember(content=content)
        assert eid1 == eid2
        facts = engine.recall("Deduplication")
        count = sum(1 for r in facts if r.id == eid1)
        assert count == 1


class TestMemoryCLI:
    def test_cli_remember(self, vault_with_engine):
        vault, index, engine = vault_with_engine
        engine.close()
        index.close()
        mp = engine.db_path
        r = _run("remember", "CLI memory engine test fact",
                 "--domain", "Infrastructure",
                 ENTROPICMEM_VAULT_PATH=str(vault.root),
                 ENTROPICMEM_INDEX_DB=str(index.db_path),
                 ENTROPICMEM_MEMORY_DB=str(mp))
        assert r.returncode == 0
        assert "Remembered:" in r.stdout

    def test_cli_remember_forget_roundtrip(self, vault_with_engine):
        vault, index, engine = vault_with_engine
        engine.close()
        index.close()
        mp = engine.db_path
        r = _run("remember", "Roundtrip test fact for CLI",
                 "--domain", "Infrastructure",
                 ENTROPICMEM_VAULT_PATH=str(vault.root),
                 ENTROPICMEM_INDEX_DB=str(index.db_path),
                 ENTROPICMEM_MEMORY_DB=str(mp))
        assert r.returncode == 0
        eid_line = [l for l in r.stdout.split("\n") if "Remembered:" in l][0]
        eid = eid_line.split(":")[1].strip()

        r2 = _run("forget", eid,
                  ENTROPICMEM_VAULT_PATH=str(vault.root),
                  ENTROPICMEM_INDEX_DB=str(index.db_path),
                  ENTROPICMEM_MEMORY_DB=str(mp))
        assert r2.returncode == 0

    def test_cli_memory_stats(self, vault_with_engine):
        vault, index, engine = vault_with_engine
        engine.remember(content="Stats CLI test", domain="Knowledge")
        engine.close()
        index.close()
        r = _run("memory", "stats",
                 ENTROPICMEM_VAULT_PATH=str(vault.root),
                 ENTROPICMEM_INDEX_DB=str(index.db_path),
                 ENTROPICMEM_MEMORY_DB=str(engine.db_path))
        assert r.returncode == 0
        assert "Facts:" in r.stdout


class TestPhase4Gate:
    def test_gate_entropic_id_consistent(self, engine):
        content = "Phase 4 gate: standalone memory engine entropic_id verification"
        eid = engine.remember(content=content)
        fact = engine.get_fact(eid)
        assert fact is not None
        assert fact.id == eid
        assert len(eid) == 16

    def test_gate_remember_dual_write(self, vault_with_engine):
        vault, index, engine = vault_with_engine
        content = "Gate test: dual write to memory engine and vault"
        eid = engine.remember(content=content, domain="Infrastructure")
        # Memory engine has it
        assert engine.get_fact(eid) is not None
        # Now project to vault
        r = engine.project_to_vault(vault, index, limit=10)
        assert r["created"] >= 1
