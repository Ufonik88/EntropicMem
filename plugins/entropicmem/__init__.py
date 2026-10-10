"""EntropicMem Hermes MemoryProvider plugin.

Install:
  ln -s /path/to/EntropicMem/plugins/entropicmem ~/.hermes/plugins/entropicmem

Prerequisites:
  /learn https://github.com/Ufonik88/EntropicMem
  entropicmem init

Config (~/.hermes/config.yaml):
  memory:
    provider: entropicmem
  plugins:
    entropicmem:
      vault_path: ~/.hermes/entropicmem/vault
      index_db: ~/.hermes/entropicmem/index.db
      memory_db: ~/.hermes/entropicmem/memory.db

EM-401: this package is the thin Hermes-facing shell. The provider itself lives
in ``em/provider/provider.py`` and imports no host; everything host-shaped —
paths and config, the P0a shadow read, the context-propagating thread factory,
the host's tool-error formatter and ``RecallStatus`` — is injected through
``_HermesHost``. ``em.*`` stays standard-library only; this package is the one
place that may import the host.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from agent.memory_provider import MemoryProvider

from . import _shadow
from ._backend import (
    bootstrap_scripts_path,
    ensure_scripts_on_path,
    hermes_home_from_kwargs,
    load_plugin_config,
    resolve_paths,
    resolve_scripts_dir,
)

# em.provider.* is needed at class-definition time, before the host has resolved
# any paths — so the scripts dir goes on sys.path here, from the plugin's own
# layout, before the import below.
bootstrap_scripts_path()

from em.provider.provider import (  # noqa: E402
    INJECTION_WARNING,
    SMART_CONTEXT_DEFAULTS,
    EntropicMemProvider,
    ProviderHost,
)

__all__ = [
    "EntropicMemMemoryProvider", "INJECTION_WARNING", "MemoryProvider",
    "SMART_CONTEXT_DEFAULTS", "register", "register_memory_provider",
]


class _HermesHost(ProviderHost):
    """The host glue ``em.provider.provider`` runs on.

    The resolvers read this module's globals at call time, not at construction,
    so the seam that patches ``plugins.entropicmem.resolve_scripts_dir`` /
    ``load_plugin_config`` keeps working through the split.
    """

    def hermes_home_from_kwargs(self, kwargs: dict):
        return hermes_home_from_kwargs(kwargs)

    def load_plugin_config(self, hermes_home):
        return load_plugin_config(hermes_home)

    def resolve_paths(self, hermes_home, config):
        return resolve_paths(hermes_home, config)

    def resolve_scripts_dir(self, hermes_home):
        return resolve_scripts_dir(hermes_home)

    def ensure_scripts_on_path(self, scripts_dir) -> None:
        ensure_scripts_on_path(scripts_dir)

    @property
    def spawn_context_thread(self) -> Optional[Callable[..., Any]]:
        """The host's contextvars-bound thread factory, or ``None`` when absent."""
        try:
            from agent.memory_provider import spawn_context_thread as factory
        except ImportError:
            return None
        return factory

    def recall_status(self, label: str, count: int):
        from agent.memory_provider import RecallStatus

        return RecallStatus(label, count)

    def tool_error(self, message: str) -> str:
        try:
            from tools.registry import tool_error

            return tool_error(message)
        except Exception:
            return json.dumps({"error": message})

    def shadow_path(self):
        return _shadow.shadow_path()

    def shadow_injected_ids(self, block: str):
        return _shadow.injected_ids(block)

    def run_shadow(self, live_db, *, profile, query, v2_ids):
        return _shadow.run(live_db, profile=profile, query=query, v2_ids=v2_ids)


_HOST = _HermesHost()


class EntropicMemMemoryProvider(EntropicMemProvider, MemoryProvider):
    """The installed provider: em.provider's implementation over the real host.

    ``EntropicMemProvider`` is listed first so its concrete methods and its
    ``name`` property satisfy the ABC — with ``MemoryProvider`` first they would
    be shadowed and the class would stay abstract.
    """

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config=config, host=_HOST)


def register_memory_provider(ctx) -> None:
    """Memory provider discovery entry point.

    H4/EM-102: constructed with NO config — anything loaded at register()
    time belongs to whatever profile the loader runs under and would
    override the real profile's file config at initialize(). Explicit
    constructor config is reserved for callers that genuinely mean it.
    """
    ctx.register_memory_provider(EntropicMemMemoryProvider())


def register(ctx) -> None:
    """General plugin loader entry point."""
    register_memory_provider(ctx)
