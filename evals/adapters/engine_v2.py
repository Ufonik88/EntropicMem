"""v2 engine adapter: loads scenarios into the real MemoryEngine and drives
the real Hermes provider prefetch pipeline against a temp HERMES_HOME.

This adapter measures the system as shipped — it patches nothing. Known v2
retrieval defects (per-set min-max relevance, decay from last_accessed) must
show up in the scores; that is the point of the S0 "measure before touching"
gate.

Imports are stdlib-only: the provider module is loaded via importlib (same
pattern as tests/test_smart_context.py) so the adapter works on a clean
checkout with no packaging installed.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from evals.adapters.base import AdapterBase, EvalHandle, Hit
from evals.dataset import Scenario
from evals.noise import generate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_DIR = _REPO_ROOT / "plugins" / "entropicmem"
_SCRIPTS = _PLUGIN_DIR / "scripts"

_PLUGIN_MODNAME = "evals_entropicmem_plugin"


def _load_provider_module():
    """Load plugins/entropicmem/__init__.py with its real _backend submodule."""
    if _PLUGIN_MODNAME in sys.modules:
        return sys.modules[_PLUGIN_MODNAME]

    import types
    from unittest.mock import MagicMock

    def _fake_memory_provider_class():
        # A real base class in a real module namespace: the plugin does
        # `from agent.memory_provider import MemoryProvider`.
        mod = sys.modules.get("agent.memory_provider")
        cls = getattr(mod, "MemoryProvider", None)
        if cls is None or isinstance(cls, MagicMock):
            mod = types.ModuleType("agent.memory_provider")
            mod.MemoryProvider = type("MemoryProvider", (), {})
            sys.modules["agent.memory_provider"] = mod
            sys.modules.setdefault("agent", types.ModuleType("agent"))
            sys.modules["agent"].memory_provider = mod
        return mod

    _fake_memory_provider_class()

    spec = importlib.util.spec_from_file_location(
        _PLUGIN_MODNAME,
        _PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(_PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[_PLUGIN_MODNAME] = module

    backend_spec = importlib.util.spec_from_file_location(
        f"{_PLUGIN_MODNAME}._backend", _PLUGIN_DIR / "_backend.py"
    )
    backend = importlib.util.module_from_spec(backend_spec)
    sys.modules[f"{_PLUGIN_MODNAME}._backend"] = backend
    backend_spec.loader.exec_module(backend)

    spec.loader.exec_module(module)
    return module


def _iso_days_ago(days: float) -> str:
    ts = datetime.now(timezone.utc) - timedelta(days=days)
    return ts.isoformat()


_ML_MODULES = ("sentence_transformers", "torch")


class _MLBlocker:
    """sys.meta_path finder that makes `import <ml pkg>` fail with
    ModuleNotFoundError without leaving any entry in sys.modules.

    Returning None would just decline the import and let the normal finder
    load the package; raising is the documented blocking technique.
    ModuleNotFoundError ⊂ ImportError, so `embeddings`' optional-dependency
    try/except takes its designed stdlib fallback path.
    """

    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split(".", 1)[0]
        if root in _ML_MODULES:
            raise ModuleNotFoundError(
                f"No module named {root!r} (blocked: evals ci suite runs "
                "without the ML stack)", name=fullname)
        return None


def force_no_embeddings() -> bool:
    """Block the optional ML stack so the engine takes its FTS-only path.

    Maintainer directive (EM-001, 2026-09-23): suite `ci` carries no ML
    dependencies even in an interpreter where sentence-transformers is
    installed. Two layers, because `import sentence_transformers` can also
    reach us through `embeddings` (via `memory_engine`'s optional probe)
    before we get a chance to patch flags:

    1. Install a sys.meta_path blocker for the ML packages. After this,
       `sentence_transformers` / `torch` are absent from sys.modules —
       exactly the state of a stdlib-only checkout: no model download, no
       torch import.
    2. If ``embeddings`` / ``memory_engine`` are already imported, flip
       ``EMBEDDER_AVAILABLE`` / ``EMBEDDINGS_AVAILABLE`` off and stub
       ``embed_text`` before any corpus is loaded.

    Returns True if anything was changed. Idempotent.
    """
    changed = False

    if not any(isinstance(f, _MLBlocker) for f in sys.meta_path):
        sys.meta_path.insert(0, _MLBlocker())
        changed = True
    for mod in _ML_MODULES:
        if mod in sys.modules and sys.modules[mod] is None:
            del sys.modules[mod]
            changed = True

    emb = sys.modules.get("embeddings")
    if emb is not None and getattr(emb, "EMBEDDER_AVAILABLE", False):
        emb.EMBEDDER_AVAILABLE = False
        changed = True

    engine_mod = sys.modules.get("memory_engine")
    if engine_mod is not None:
        if getattr(engine_mod, "EMBEDDINGS_AVAILABLE", False):
            engine_mod.EMBEDDINGS_AVAILABLE = False
            changed = True
        if getattr(engine_mod, "EMBEDDINGS_IMPORTABLE", False):
            engine_mod.EMBEDDINGS_IMPORTABLE = False
            engine_mod.embed_text = lambda text: None
            changed = True

    return changed


class EngineV2Adapter(AdapterBase):
    """One scenario per handle: fresh temp DB, real engine + provider.

    ``disable_embeddings`` (default True — the ci contract) forces the
    engine's optional ML path off for the whole process before any corpus is
    loaded, so suite `ci` stays stdlib-fast even where sentence-transformers
    is installed. Suite `full` passes False to measure the vector backend.
    """

    name = "v2"

    def __init__(self, disable_embeddings: bool = True) -> None:
        self.disable_embeddings = disable_embeddings
        if disable_embeddings:
            force_no_embeddings()
        self._module = _load_provider_module()
        self._tmpdirs: List[tempfile.TemporaryDirectory] = []
        self._handles: List[Dict[str, Any]] = []

    # ── adapter interface ──────────────────────────────────────────────

    def load(self, scenario: Scenario) -> EvalHandle:
        tmp = tempfile.TemporaryDirectory(prefix="em-eval-")
        self._tmpdirs.append(tmp)
        home = Path(tmp.name)
        (home / "entropicmem" / "vault").mkdir(parents=True, exist_ok=True)
        db_path = home / "entropicmem" / "memory.db"

        engine_mod = self._import_engine()
        engine = engine_mod.MemoryEngine(db_path, profile_id="eval")

        ref_ids: Dict[str, str] = {}
        for n, mem in enumerate(scenario.memories):
            eid = engine.remember(
                content=mem.content,
                importance=mem.importance,
                domain=mem.domain,
                source="agent",
            )
            ref_ids[f"${n}"] = eid
            if mem.age_days:
                stamp = _iso_days_ago(mem.age_days)
                engine.db.execute(
                    "UPDATE facts SET created_at=?, updated_at=?, last_accessed=? WHERE id=?",
                    (stamp, stamp, stamp, eid),
                )
                engine.db.commit()

        noise_ids: Set[str] = set()
        for content in generate(scenario.noise.generator, scenario.noise.count, scenario.noise.seed):
            noise_ids.add(engine.remember(content, importance=0.3, source="agent"))

        provider = self._make_provider(home, db_path)
        provider.initialize("eval-session", hermes_home=str(home))

        handle = EvalHandle(
            scenario=scenario,
            ref_ids=ref_ids,
            noise_ids=noise_ids,
            extra={"engine": engine, "provider": provider, "db": db_path},
        )
        self._handles.append({"handle": handle, "tmp": tmp})
        return handle

    def search(self, handle: EvalHandle, query: str, k: int = 5) -> List[Hit]:
        engine = handle.extra["engine"]
        # min_relevance=0.0 so ranking metrics measure ORDER, not the gate;
        # abstention is scored separately via prefetch.
        facts = engine.recall_with_relevance(query, top_k=k, min_relevance=0.0)
        return [Hit(id=f.id, content=f.content, score=float(f.relevance_score)) for f in facts]

    def prefetch(self, handle: EvalHandle, query: str) -> str:
        provider = handle.extra["provider"]
        return provider.prefetch(query) or ""

    # ── lifecycle ───────────────────────────────────────────────────────

    def finish(self, handle: EvalHandle) -> None:
        try:
            handle.extra["engine"].close()
        except Exception:
            pass

    def shutdown(self) -> None:
        for rec in self._handles:
            self.finish(rec["handle"])
        self._handles.clear()
        for tmp in self._tmpdirs:
            try:
                tmp.cleanup()
            except Exception:
                pass
        self._tmpdirs.clear()

    # ── internals ───────────────────────────────────────────────────────

    def _import_engine(self):
        if str(_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS))
        import memory_engine

        return memory_engine

    def _make_provider(self, home: Path, db_path: Path):
        cls = self._module.EntropicMemMemoryProvider
        return cls(config={
            "memory_db": str(db_path),
            "index_db": str(home / "entropicmem" / "index.db"),
            "vault_path": str(home / "entropicmem" / "vault"),
            # Evals measure the fact-retrieval pipeline. Core Memory is static
            # boilerplate (not retrieved) and would pollute prefetch_tokens —
            # it is the subject of EM-116, not of v2 retrieval scoring.
            "core_memory_enabled": False,
        })
