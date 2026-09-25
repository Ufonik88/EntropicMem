"""Adapter embedding lockdown (EM-001 maintainer correction).

The v2 adapter must be able to force the engine's embedding path off for the
ci suite even when sentence-transformers IS installed. These tests exercise
the mechanism directly (no corpus), so they stay within the pytest budget.
"""
import importlib
import sys
import types

import pytest
from evals.adapters import engine_v2
from evals.adapters.engine_v2 import (
    EngineV2Adapter,
    _MLBlocker,
    force_no_embeddings,
    restore_embeddings,
)

_LOCKED = ("sentence_transformers", "torch", "embeddings", "memory_engine")


@pytest.fixture()
def clean_ml_state():
    """Snapshot/restore the sys.modules and sys.meta_path state the
    lockdown touches, so sibling tests see the interpreter they expect."""
    saved = {m: (sys.modules[m] if m in sys.modules else "<absent>") for m in _LOCKED}
    saved_path = list(sys.meta_path)
    saved_patched = dict(engine_v2._PATCHED)
    saved_holders = engine_v2._LOCK_HOLDERS
    yield
    sys.meta_path[:] = saved_path
    engine_v2._PATCHED.clear()
    engine_v2._PATCHED.update(saved_patched)
    engine_v2._LOCK_HOLDERS = saved_holders
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


def _blocker_installed() -> bool:
    return any(isinstance(f, _MLBlocker) for f in sys.meta_path)


@pytest.fixture()
def ml_installed(clean_ml_state):
    """embeddings/memory_engine loaded with their flags set as they would be
    on an interpreter with the ML stack installed; attributes restored after.
    Yields (embeddings, memory_engine, sentinel embed_text)."""
    restore_embeddings()
    engine_v2._LOCK_HOLDERS = 0
    embeddings = importlib.import_module("embeddings")
    memory_engine = importlib.import_module("memory_engine")
    attrs = [(embeddings, "EMBEDDER_AVAILABLE"),
             (memory_engine, "EMBEDDINGS_AVAILABLE"),
             (memory_engine, "EMBEDDINGS_IMPORTABLE"),
             (memory_engine, "embed_text")]
    saved = [(mod, name, getattr(mod, name)) for mod, name in attrs]
    sentinel = object()
    embeddings.EMBEDDER_AVAILABLE = True
    memory_engine.EMBEDDINGS_AVAILABLE = True
    memory_engine.EMBEDDINGS_IMPORTABLE = True
    memory_engine.embed_text = sentinel
    try:
        yield embeddings, memory_engine, sentinel
    finally:
        restore_embeddings()
        for mod, name, value in saved:
            setattr(mod, name, value)


def test_lockdown_refuses_when_ml_already_imported(clean_ml_state):
    """A real, already-imported ML module cannot be un-imported: fail loudly
    instead of pretending the run is ML-free."""
    restore_embeddings()
    sys.modules["torch"] = types.ModuleType("torch")
    with pytest.raises(RuntimeError, match="torch already imported"):
        force_no_embeddings()
    assert not _blocker_installed()
    assert not engine_v2._PATCHED


def test_restore_embeddings_undoes_lockdown(ml_installed):
    embeddings, memory_engine, sentinel = ml_installed
    assert force_no_embeddings() is True
    assert _blocker_installed()
    assert memory_engine.embed_text("x") is None

    assert restore_embeddings() is True
    assert not _blocker_installed()
    assert embeddings.EMBEDDER_AVAILABLE is True
    assert memory_engine.EMBEDDINGS_AVAILABLE is True
    assert memory_engine.EMBEDDINGS_IMPORTABLE is True
    assert memory_engine.embed_text is sentinel
    assert restore_embeddings() is False  # idempotent


def test_adapter_shutdown_restores_interpreter(ml_installed):
    """The last locking adapter to shut down removes the blocker and restores
    the patched engine/embeddings flags; earlier shutdowns keep the lock."""
    embeddings, memory_engine, sentinel = ml_installed
    a = EngineV2Adapter()
    b = EngineV2Adapter()
    try:
        assert _blocker_installed()
        assert memory_engine.EMBEDDINGS_AVAILABLE is False
        a.shutdown()
        assert _blocker_installed(), "lock released while another adapter holds it"
        b.shutdown()
        assert not _blocker_installed()
        assert embeddings.EMBEDDER_AVAILABLE is True
        assert memory_engine.EMBEDDINGS_AVAILABLE is True
        assert memory_engine.embed_text is sentinel
        a.shutdown()  # idempotent, must not underflow
        assert engine_v2._LOCK_HOLDERS == 0
    finally:
        a.shutdown()
        b.shutdown()
