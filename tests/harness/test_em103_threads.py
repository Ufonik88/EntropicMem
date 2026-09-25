"""EM-103 (H3): background threads must be spawned via ``_spawn``, which
prefers the host's context-propagating ``spawn_context_thread`` and falls back
to a single plain named daemon thread only when the host primitive cannot be
imported (bare ``threading.Thread`` at call sites silently runs workers under
the default profile in multiplexed gateways).
"""
import sys
import threading
import types
from pathlib import Path

from plugins.entropicmem import EntropicMemMemoryProvider

import memory_engine

ROOT = Path(__file__).resolve().parents[2]


def _make_extract_provider(tmp_path):
    """Provider wired like test_plugin_hardening._make_provider, for _auto_extract."""
    prov = EntropicMemMemoryProvider(config={"memory_db": str(tmp_path / "memory.db")})
    prov._scripts_dir = ROOT / "plugins" / "entropicmem" / "scripts"
    prov._hermes_home = tmp_path
    prov._memory_db = tmp_path / "memory.db"
    prov._session_id = "sess-em103"
    return prov


def test_auto_extract_routes_through_spawn(monkeypatch, tmp_path):
    """_auto_extract must spawn its worker through _spawn (-> host
    spawn_context_thread with matching params), never a bare thread locally."""
    prov = _make_extract_provider(tmp_path)
    via_spawn = []  # (target, name) seen by _spawn
    via_host = []  # (target, name, daemon) seen by the host primitive

    def fake_spawn_context_thread(target, *, name, daemon=True, args=(), kwargs=None):
        via_host.append((target, name, daemon))
        return types.SimpleNamespace(start=lambda: None)

    monkeypatch.setattr(
        sys.modules["agent.memory_provider"], "spawn_context_thread", fake_spawn_context_thread
    )

    orig_spawn = EntropicMemMemoryProvider._spawn

    def spy(self, target, name):
        via_spawn.append((target, name))
        return orig_spawn(self, target, name)

    monkeypatch.setattr(EntropicMemMemoryProvider, "_spawn", spy)

    prov._auto_extract("synthetic user text", "synthetic assistant text", "sess-1")

    assert [name for _, name in via_spawn] == ["entropicmem-extract"]
    assert callable(via_spawn[0][0]), "_spawn must receive the worker target"
    # the single _spawn call reached the host primitive with matching params
    assert [(n, d) for _, n, d in via_host] == [("entropicmem-extract", True)]
    assert callable(via_host[0][0])


def test_spawn_fallback_real_named_daemon_thread_finishes_extraction(monkeypatch, tmp_path):
    """When the host primitive is unimportable (ImportError), _spawn falls back
    to one real named daemon thread that runs the extraction to completion."""
    # Force the fallback: module without spawn_context_thread -> ImportError.
    monkeypatch.setitem(
        sys.modules, "agent.memory_provider", types.ModuleType("agent.memory_provider")
    )

    prov = _make_extract_provider(tmp_path)

    started = []
    real_thread = threading.Thread

    class RecordingThread(real_thread):
        def start(self):
            started.append(self)
            super().start()

    monkeypatch.setattr(threading, "Thread", RecordingThread)

    extracted = []
    orig_extract = memory_engine.MemoryEngine.extract_and_store

    def rec_extract(self, **kwargs):
        extracted.append(kwargs)
        return orig_extract(self, **kwargs)

    monkeypatch.setattr(memory_engine.MemoryEngine, "extract_and_store", rec_extract)

    prov._auto_extract("synthetic user text", "synthetic assistant text", "sess-1")

    assert len(started) == 1, "fallback must start exactly one thread"
    worker = started[0]
    assert worker.name == "entropicmem-extract"
    assert worker.daemon
    worker.join(timeout=30)
    assert not worker.is_alive(), "extraction thread must finish"
    assert [kw.get("source") for kw in extracted] == ["auto_extracted"]
    assert prov._extract_lock.acquire(blocking=False), "worker must release the extract lock"
    prov._extract_lock.release()
