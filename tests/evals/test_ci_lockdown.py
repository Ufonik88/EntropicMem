"""Adapter embedding lockdown (EM-001 maintainer correction).

The v2 adapter must be able to force the engine's embedding path off for the
ci suite even when sentence-transformers IS installed. These tests exercise
the mechanism directly (no corpus), so they stay within the pytest budget.
"""
import importlib
import sys

import pytest
from evals.adapters.engine_v2 import EngineV2Adapter, force_no_embeddings

_LOCKED = ("sentence_transformers", "torch", "embeddings", "memory_engine")


@pytest.fixture()
def clean_ml_state():
    """Snapshot/restore the sys.modules and sys.meta_path state the
    lockdown touches, so sibling tests see the interpreter they expect."""
    saved = {m: (sys.modules[m] if m in sys.modules else "<absent>") for m in _LOCKED}
    saved_path = list(sys.meta_path)
    yield
    sys.meta_path[:] = saved_path
    for m, v in saved.items():
        if v == "<absent>":
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = v


def test_lockdown_blocks_ml_import(clean_ml_state):
    """After lockdown, importing sentence_transformers raises ImportError and
    leaves no sys.modules entry — so memory_engine's optional-embedding probe
    takes the False branch."""
    for m in _LOCKED:
        sys.modules.pop(m, None)
    force_no_embeddings()

    with pytest.raises(ImportError):
        importlib.import_module("sentence_transformers")
    with pytest.raises(ImportError):
        importlib.import_module("torch")
    assert "sentence_transformers" not in sys.modules
    assert "torch" not in sys.modules


def test_memory_engine_imports_with_embeddings_off(clean_ml_state):
    for m in _LOCKED:
        sys.modules.pop(m, None)
    force_no_embeddings()

    memory_engine = importlib.import_module("memory_engine")
    assert memory_engine.EMBEDDINGS_AVAILABLE is False


def test_lockdown_overrides_already_loaded_engine(clean_ml_state):
    """If embeddings/memory_engine got imported before the lockdown, the
    adapter still flips the live module flags off (maintainer directive: set
    EMBEDDINGS_AVAILABLE = False / stub embed_text before load)."""
    embeddings = importlib.import_module("embeddings")
    memory_engine = importlib.import_module("memory_engine")
    orig_emb_avail = embeddings.EMBEDDER_AVAILABLE
    orig_me_avail = memory_engine.EMBEDDINGS_AVAILABLE
    orig_importable = memory_engine.EMBEDDINGS_IMPORTABLE
    orig_embed_text = memory_engine.embed_text

    try:
        force_no_embeddings()
        assert embeddings.EMBEDDER_AVAILABLE is False
        assert memory_engine.EMBEDDINGS_AVAILABLE is False
        assert memory_engine.embed_text("hello") is None
    finally:
        embeddings.EMBEDDER_AVAILABLE = orig_emb_avail
        memory_engine.EMBEDDINGS_AVAILABLE = orig_me_avail
        memory_engine.EMBEDDINGS_IMPORTABLE = orig_importable
        memory_engine.embed_text = orig_embed_text


def test_adapter_default_locks_embeddings():
    """EngineV2Adapter() (the ci path) defaults to the lockdown; suite `full`
    opts out with disable_embeddings=False."""
    a_ci = EngineV2Adapter()
    a_full = EngineV2Adapter(disable_embeddings=False)
    try:
        assert a_ci.disable_embeddings is True
        assert a_full.disable_embeddings is False
    finally:
        a_ci.shutdown()
        a_full.shutdown()
