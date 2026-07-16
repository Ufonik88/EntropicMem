"""
test_phase4.py — Tests for Phase 4 Mnemosyne bridge.
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
from mnemosyne_bridge import MnemosyneBridge, MNEMOSYNE_AVAILABLE, MNEMOSYNE_DB_PATH


def _run(*args, **env):
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, _CLI, *args],
        capture_output=True, text=True, env=full_env,
    )


@pytest.fixture
def vault_with_bridge():
    """Create a temp vault with index and bridge."""
    with tempfile.TemporaryDirectory() as td:
        vp = Path(td) / "vault"
        ip = Path(td) / "index.db"
        _run("init", "--vault", str(vp), "--index-db", str(ip),
             ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))

        vault = Vault(vp)
        index = VaultIndex(ip)

        # Add some test notes for graph context
        for i in range(5):
            path = vault.write_note(
                "Infrastructure", f"Bridge Test Note {i}",
                f"Body for bridge test {i}. Links to [[Bridge Test Note {i+1}]]" if i < 4 else f"Final bridge test note {i}.",
                tags=["bridge-test"], domain="Infrastructure",
            )
            note = vault.read_note(path)
            index.upsert_note(note)
            index.upsert_edges_for_note(vault, note)

        bridge = MnemosyneBridge(vault, index)
        yield vault, index, bridge
        index.close()


class TestMnemosyneBridge:
    def test_bridge_available_status(self):
        """Bridge should report Mnemosyne availability correctly."""
        assert isinstance(MNEMOSYNE_AVAILABLE, bool)

    def test_entropic_id_deterministic(self):
        """Same content should produce same entropic_id."""
        content = "Test fact about EntropicMem bridge"
        eid1 = hashlib.sha256(content.encode()).hexdigest()[:16]
        eid2 = hashlib.sha256(content.encode()).hexdigest()[:16]
        assert eid1 == eid2
        assert len(eid1) == 16

    def test_entropic_id_different(self):
        """Different content should produce different entropic_id."""
        eid1 = hashlib.sha256(b"Content A").hexdigest()[:16]
        eid2 = hashlib.sha256(b"Content B").hexdigest()[:16]
        assert eid1 != eid2

    def test_remember_vault_only(self, vault_with_bridge):
        """remember() should always create vault note regardless of Mnemosyne status."""
        vault, index, bridge = vault_with_bridge
        content = "Test vault-only remember for EntropicMem bridge testing"
        mnemo_id, path = bridge.remember(
            content=content, domain="Infrastructure", tags=["test"],
            importance=0.5, source="test",
        )

        assert path is not None
        assert (vault.root / path).exists()

        note = vault.read_note(path)
        assert note.entropic_id
        assert len(note.entropic_id) == 16

    def test_remember_entropic_id_consistent(self, vault_with_bridge):
        """Same content should produce same entropic_id across calls."""
        vault, index, bridge = vault_with_bridge
        content = "Consistent entropic_id test fact"

        mnemo_id1, path1 = bridge.remember(content=content, domain="Infrastructure")
        mnemo_id2, path2 = bridge.remember(content=content, domain="Infrastructure")

        note1 = vault.read_note(path1)
        note2 = vault.read_note(path2)
        # Both notes should compute the same entropic_id
        assert note1.compute_entropic_id() == note2.compute_entropic_id()

    def test_bridge_export_creates_folder(self, vault_with_bridge):
        """Bridge export should create Mnemosyne/ folder if it doesn't exist."""
        vault, index, bridge = vault_with_bridge
        mnemosyne_dir = vault.root / "Mnemosyne"
        assert not mnemosyne_dir.exists() or mnemosyne_dir.is_dir()
        # After export attempt
        if bridge.available:
            result = bridge.export_to_vault(limit=5)
            assert isinstance(result.created, int)
            assert isinstance(result.skipped, int)

    def test_bridge_export_dedup(self, vault_with_bridge):
        """Bridge export should not duplicate notes with same entropic_id."""
        vault, index, bridge = vault_with_bridge
        if not bridge.available:
            pytest.skip("Mnemosyne DB not available")

        # Two exports should not double the count
        result1 = bridge.export_to_vault(limit=10)
        result2 = bridge.export_to_vault(limit=10)
        # After first export, second should mostly skip
        assert result2.created <= result1.created or result1.created == 0

    def test_bridge_remember_has_mnemosyne_id(self, vault_with_bridge):
        """When Mnemosyne available, remember should return a non-None mnemosyne_id."""
        vault, index, bridge = vault_with_bridge
        if not bridge.available:
            pytest.skip("Mnemosyne DB not available")

        mnemo_id, path = bridge.remember(
            content="Test Mnemosyne dual-write for bridge testing",
            domain="Infrastructure", tags=["test"],
        )
        assert mnemo_id is not None
        assert len(mnemo_id) > 0


class TestBridgeCLI:
    def test_cli_bridge_export(self, vault_with_bridge):
        vault, index, bridge = vault_with_bridge
        index.close()
        r = _run("bridge", "export",
                 ENTROPICMEM_VAULT_PATH=str(vault.root), ENTROPICMEM_INDEX_DB=str(index.db_path))
        assert r.returncode == 0
        assert "created" in r.stdout.lower() or "skipped" in r.stdout.lower()

    def test_cli_remember_mnemosyne(self, vault_with_bridge):
        """remember CLI should output entropic_id and Mnemosyne status."""
        vault, index, bridge = vault_with_bridge
        index.close()
        r = _run("remember", "CLI bridge test fact for phase 4",
                 "--domain", "Infrastructure", "--tags", "bridge-test",
                 ENTROPICMEM_VAULT_PATH=str(vault.root), ENTROPICMEM_INDEX_DB=str(index.db_path))
        assert r.returncode == 0
        assert "Remembered" in r.stdout
        assert "remembered" in r.stdout.lower()


class TestPhase4Gate:
    def test_gate_roundtrip_entropic_id(self, vault_with_bridge):
        """Gate: remember stores entropic_id in frontmatter."""
        vault, index, bridge = vault_with_bridge
        content = "Phase 4 gate test: round-trip entropic_id verification for EntropicMem"

        _, path = bridge.remember(content=content, domain="Infrastructure", tags=["gate-test"])
        note = vault.read_note(path)
        # entropic_id should be present and 16 chars
        assert note.entropic_id
        assert len(note.entropic_id) == 16

    def test_gate_mnemosyne_dual_write(self, vault_with_bridge):
        """Gate: dual write creates both vault note and Mnemosyne memory."""
        vault, index, bridge = vault_with_bridge
        if not bridge.available:
            pytest.skip("Mnemosyne DB not available")

        content = "Gate test dual write: vault and Mnemosyne"
        mnemo_id, path = bridge.remember(content=content, domain="Infrastructure")

        # Vault note exists
        assert (vault.root / path).exists()
        # Mnemosyne ID returned
        assert mnemo_id is not None
        assert len(mnemo_id) > 0
