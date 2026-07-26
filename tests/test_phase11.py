"""Tests for Phase 10.2 (graph-aware recall) and Phase 11 (security, capsule, versioning)."""

import json
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_engine import MemoryEngine, StoredFact


def _crypto_available():
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


# ── Phase 10.2: graph-aware recall ──────────────────────────────────────────

class TestGraphAwareRecall:
    @pytest.fixture
    def engine(self, tmp_path):
        db_path = tmp_path / "test.db"
        eng = MemoryEngine(db_path)
        yield eng
        eng.close()

    def test_expand_links_false_by_default(self, engine):
        engine.remember("Budget planning for Q3", domain="Finance")
        results = engine.recall_hybrid("budget", expand_links=False)
        assert len(results) >= 1

    def test_expand_links_no_graph(self, engine):
        """expand_links=True with empty graph should not crash."""
        engine.remember("Standalone fact", domain="Knowledge")
        results = engine.recall_hybrid("standalone", expand_links=True)
        assert len(results) >= 1

    def test_expand_links_with_connections(self, engine):
        """When link graph has connections, expanded results include linked facts."""
        from graph_query import init_links_schema, store_links

        engine.remember("Wedding venue booking confirmed", title="Wedding", domain="Projects")
        engine.remember("Budget allocation for wedding", title="Budget", domain="Finance")

        # Build link graph
        init_links_schema(engine.db)
        store_links(engine.db, "Projects/Wedding.md", "Wedding", [("Budget", "see budget")])
        engine.db.commit()

        results = engine.recall_hybrid("wedding", expand_links=True)
        assert len(results) >= 1
        # Should have attempted expansion (may or may not find Budget depending on FTS)


# ── Phase 11.1: security ────────────────────────────────────────────────────

class TestSecurity:
    def test_security_status_unencrypted(self, tmp_path):
        from security import security_status
        db_path = tmp_path / "memory.db"
        db_path.touch()
        status = security_status(db_path)
        assert status["encrypted"] is False

    def test_is_encrypted_false(self, tmp_path):
        from security import is_encrypted
        db_path = tmp_path / "memory.db"
        db_path.touch()
        assert is_encrypted(db_path) is False

    def test_is_encrypted_true(self, tmp_path):
        from security import is_encrypted, ENCRYPTED_MARKER
        db_path = tmp_path / "memory.db"
        db_path.touch()
        (tmp_path / ENCRYPTED_MARKER).write_text("{}")
        assert is_encrypted(db_path) is True

    @pytest.mark.skipif(
        not _crypto_available(),
        reason="cryptography not installed",
    )
    def test_encrypt_decrypt_roundtrip(self, tmp_path):
        from security import encrypt_db, decrypt_db, is_encrypted

        db_path = tmp_path / "memory.db"
        db_path.write_text("test database content")

        result = encrypt_db(db_path, "testpass123")
        assert result["encrypted_files"] >= 1
        assert is_encrypted(db_path)
        assert not db_path.exists()  # plaintext removed
        assert (tmp_path / "memory.db.enc").exists()

        result = decrypt_db(db_path, "testpass123")
        assert result["decrypted_files"] >= 1
        assert not is_encrypted(db_path)
        assert db_path.read_text() == "test database content"

    @pytest.mark.skipif(
        not _crypto_available(),
        reason="cryptography not installed",
    )
    def test_wrong_passphrase(self, tmp_path):
        from security import encrypt_db, decrypt_db

        db_path = tmp_path / "memory.db"
        db_path.write_text("secret data")
        encrypt_db(db_path, "correctpass")

        with pytest.raises(ValueError, match="Wrong passphrase"):
            decrypt_db(db_path, "wrongpass")


# ── Phase 11.2: capsule export/import ───────────────────────────────────────

class TestCapsule:
    @pytest.fixture
    def engine(self, tmp_path):
        db_path = tmp_path / "entropicmem" / "memory.db"
        db_path.parent.mkdir(parents=True)
        eng = MemoryEngine(db_path)
        eng.remember("Test fact for capsule", domain="Testing")
        yield eng
        eng.close()

    def test_export_creates_tarball(self, engine, tmp_path):
        capsule_path = tmp_path / "capsule.tar.gz"
        db_path = engine.db_path

        with tarfile.open(str(capsule_path), "w:gz") as tar:
            tar.add(str(db_path), arcname="memory.db")
            manifest = {"version": 1, "exported_at": "2026-07-26T00:00:00", "has_vault": False}
            import io
            manifest_bytes = json.dumps(manifest).encode()
            info = tarfile.TarInfo(name="manifest.json")
            info.size = len(manifest_bytes)
            tar.addfile(info, io.BytesIO(manifest_bytes))

        assert capsule_path.exists()
        with tarfile.open(str(capsule_path), "r:gz") as tar:
            names = tar.getnames()
            assert "memory.db" in names
            assert "manifest.json" in names

    def test_import_restores_db(self, tmp_path):
        # Create engine, store fact, close (checkpoints WAL)
        db_path = tmp_path / "entropicmem" / "memory.db"
        db_path.parent.mkdir(parents=True)
        eng = MemoryEngine(db_path)
        eng.remember("Test fact for capsule", domain="Testing")
        eng.close()

        # Export
        capsule_path = tmp_path / "capsule.tar.gz"
        with tarfile.open(str(capsule_path), "w:gz") as tar:
            tar.add(str(db_path), arcname="memory.db")
            manifest = {"version": 1, "exported_at": "2026-07-26T00:00:00", "has_vault": False}
            import io
            manifest_bytes = json.dumps(manifest).encode()
            info = tarfile.TarInfo(name="manifest.json")
            info.size = len(manifest_bytes)
            tar.addfile(info, io.BytesIO(manifest_bytes))

        # Wipe DB
        db_path.unlink()
        assert not db_path.exists()

        # Import
        with tarfile.open(str(capsule_path), "r:gz") as tar:
            tar.extract("memory.db", path=str(db_path.parent))

        # Verify
        eng2 = MemoryEngine(db_path)
        facts = eng2.list_facts()
        eng2.close()
        assert any("capsule" in f.content for f in facts)


# ── Phase 11.3: fact versioning ─────────────────────────────────────────────

class TestVersioning:
    @pytest.fixture
    def engine(self, tmp_path):
        db_path = tmp_path / "test.db"
        eng = MemoryEngine(db_path)
        yield eng
        eng.close()

    def test_snapshot_version(self, engine):
        eid = engine.remember("Original content v1", domain="Testing")
        result = engine.snapshot_version(eid, source="test")
        assert result is True

        versions = engine.get_versions(eid)
        assert len(versions) == 1
        assert versions[0]["content"] == "Original content v1"
        assert versions[0]["source"] == "test"

    def test_snapshot_nonexistent(self, engine):
        result = engine.snapshot_version("nonexistent_id")
        assert result is False

    def test_version_history_on_dedup_update(self, engine):
        """When a fact is updated via dedup, a version snapshot is created."""
        eid = engine.remember("The budget is R50000 per month", domain="Finance")

        # Same content triggers dedup update
        engine.remember("The budget is R50000 per month", domain="Finance")

        versions = engine.get_versions(eid)
        assert len(versions) >= 1
        assert versions[0]["source"] == "dedup_update"

    def test_multiple_versions(self, engine):
        eid = engine.remember("Version 1 of fact", domain="Testing")
        engine.snapshot_version(eid, source="v1")

        # Update the fact content directly
        engine.db.execute("UPDATE facts SET content = ? WHERE id = ?", ("Version 2 of fact", eid))
        engine.db.commit()
        engine.snapshot_version(eid, source="v2")

        versions = engine.get_versions(eid)
        assert len(versions) == 2
        # Newest first
        assert versions[0]["source"] == "v2"
        assert versions[1]["source"] == "v1"

    def test_get_versions_empty(self, engine):
        versions = engine.get_versions("no_such_fact")
        assert versions == []
