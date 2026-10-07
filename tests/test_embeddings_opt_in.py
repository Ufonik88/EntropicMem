"""Vector embeddings are opt-in: no model is built (downloaded) by default.

Having sentence-transformers importable in the host venv used to be enough:
``remember`` built ``SentenceTransformer("all-MiniLM-L6-v2")`` with no config
gate, so the first write downloaded a model from Hugging Face (network egress
from a plugin disclosed as local-only). Reported in the Hermes catalog review
of 2.8.0. These tests use a fake model class that records construction, so
"nothing is downloaded" is asserted directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "plugins" / "entropicmem" / "scripts"))

import em_internal.embeddings as embeddings  # noqa: E402
import memory_engine  # noqa: E402
from memory_engine import MemoryEngine  # noqa: E402


class _FakeModel:
    built = 0

    def __init__(self, name):
        type(self).built += 1

    def encode(self, text, normalize_embeddings=True):
        class _V(list):
            def tolist(self):
                return list(self)

        return _V([0.1] * 384)


@pytest.fixture(autouse=True)
def _fake_embedder(monkeypatch):
    """Pretend sentence-transformers is installed, with a model that counts
    constructions instead of downloading anything."""
    _FakeModel.built = 0
    monkeypatch.setattr(embeddings, "EMBEDDER_AVAILABLE", True)
    monkeypatch.setattr(embeddings, "SentenceTransformer", _FakeModel, raising=False)
    monkeypatch.setattr(embeddings, "_model_instance", None)
    monkeypatch.delenv(embeddings.EMBEDDINGS_ENV, raising=False)
    embeddings.set_enabled(None)
    yield
    embeddings.set_enabled(None)


# --- the gate ---------------------------------------------------------------


def test_default_is_off_and_nothing_is_built():
    assert embeddings.embeddings_enabled() is False
    assert embeddings.get_embedder() is None
    assert embeddings.embed_text("Acme uses blue-green deploys.") is None
    assert _FakeModel.built == 0


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_environment_opt_in_for_the_cli(monkeypatch, value):
    monkeypatch.setenv(embeddings.EMBEDDINGS_ENV, value)
    assert embeddings.get_embedder() is not None
    assert _FakeModel.built == 1


def test_config_overrides_the_environment(monkeypatch):
    monkeypatch.setenv(embeddings.EMBEDDINGS_ENV, "1")
    embeddings.set_enabled(False)
    assert embeddings.get_embedder() is None
    embeddings.set_enabled(True)
    monkeypatch.delenv(embeddings.EMBEDDINGS_ENV)
    assert embeddings.get_embedder() is not None


# --- the engine -------------------------------------------------------------


@pytest.fixture
def engine(tmp_path, monkeypatch):
    # The engine's own availability flag needs numpy too; pretend both exist
    # and route storage to a recorder so no real vector code runs.
    stored = []
    monkeypatch.setattr(memory_engine, "EMBEDDINGS_AVAILABLE", True)
    monkeypatch.setattr(memory_engine, "store_embedding", lambda db, fid, vec: stored.append(fid), raising=False)
    eng = MemoryEngine(tmp_path / "memory.db", profile_id="default", hermes_home=tmp_path / "hermes")
    eng.stored = stored
    with eng:
        yield eng


def test_remember_downloads_nothing_by_default(engine):
    engine.remember(content="Globex keeps staging in Frankfurt.")
    assert _FakeModel.built == 0
    assert engine.stored == []


def test_recall_hybrid_embeds_no_query_by_default(engine, monkeypatch):
    engine.remember(content="Initech rotates credentials every ninety days.")
    calls = []
    monkeypatch.setattr(memory_engine, "embed_text", lambda t: calls.append(t) or None)
    results = engine.recall_hybrid("credentials rotation", top_k=3)
    assert calls == []
    assert results and "Initech" in results[0].content


def test_opted_in_remember_encodes_outside_the_write_lock(engine, monkeypatch):
    """Encoding can take seconds (a first use downloads the model); holding
    the engine's write lock meanwhile would stall every other writer."""
    embeddings.set_enabled(True)
    seen = []

    def fake_embed(text):
        seen.append(engine._write_locked)
        return [0.1] * 384

    monkeypatch.setattr(memory_engine, "embed_text", fake_embed)
    fid = engine.remember(content="Bob Example owns the backup verification job.")
    assert seen == [False], "embed_text ran while the write lock was held"
    assert engine.stored == [fid]


def test_rebuild_and_stats_explain_how_to_enable(engine):
    assert "disabled" in engine.rebuild_embeddings()["message"]
    assert _FakeModel.built == 0


# --- the provider -------------------------------------------------------------


def test_provider_config_drives_the_gate(tmp_path, monkeypatch):
    for var in ("ENTROPICMEM_VAULT_PATH", "ENTROPICMEM_INDEX_DB", "ENTROPICMEM_MEMORY_DB"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    import plugins.entropicmem as plugin_mod

    assert plugin_mod.SMART_CONTEXT_DEFAULTS["embeddings_enabled"] is False
    prov = plugin_mod.EntropicMemMemoryProvider()
    prov.initialize("sess-embed", hermes_home=str(tmp_path))
    assert embeddings.embeddings_enabled() is False

    prov = plugin_mod.EntropicMemMemoryProvider(config={"embeddings_enabled": True})
    prov.initialize("sess-embed", hermes_home=str(tmp_path))
    assert embeddings.embeddings_enabled() is True
