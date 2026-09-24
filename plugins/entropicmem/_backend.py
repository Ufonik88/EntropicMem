"""EntropicMem backend — resolve plugin scripts, config and env paths."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def hermes_home_from_kwargs(kwargs: dict) -> Path:
    hh = kwargs.get("hermes_home") or os.environ.get("HERMES_HOME", "")
    if hh:
        return Path(hh).expanduser().resolve()
    return Path.home() / ".hermes"


def resolve_scripts_dir(hermes_home: Path) -> Optional[Path]:
    candidates = [
        # Plugin-local engine (self-contained plugin: catalog install or repo checkout).
        Path(__file__).resolve().parent / "scripts",
        # Legacy layouts: skill copy under HERMES_HOME, or repo-root checkout.
        hermes_home / "skills" / "entropicmem" / "scripts",
        Path(__file__).resolve().parent.parent.parent / "skills" / "entropicmem" / "scripts",
    ]
    for c in candidates:
        if (c / "memory_engine.py").is_file():
            return c.resolve()
    return None


def ensure_scripts_on_path(scripts_dir: Path) -> None:
    p = str(scripts_dir)
    if p not in sys.path:
        sys.path.insert(0, p)


def resolve_paths(hermes_home: Path, plugin_config: dict) -> Tuple[Path, Path, Path]:
    """Resolve vault/index/memory paths.

    The VAULT path comes from the ONE shared resolver,
    ``vault.resolve_vault_path`` (scripts/vault.py), so the CLI and the plugin
    can never operate on different vaults. Precedence there: explicit plugin
    config ``vault_path`` > ``ENTROPICMEM_VAULT_PATH`` env >
    ``{hermes_home}/entropicmem/vault``. ``OBSIDIAN_VAULT_PATH`` is not
    honored anywhere (Phase 2 path unification).

    Index/memory DB defaults always under ``{hermes_home}/entropicmem/``
    (``ENTROPICMEM_INDEX_DB`` / ``ENTROPICMEM_MEMORY_DB`` overrides honored).
    """
    base = hermes_home / "entropicmem"
    scripts = resolve_scripts_dir(hermes_home)
    if scripts:
        ensure_scripts_on_path(scripts)
    from vault import resolve_vault_path

    vault = resolve_vault_path(plugin_config.get("vault_path"), hermes_home=hermes_home)
    index_db = Path(
        plugin_config.get("index_db")
        or os.environ.get("ENTROPICMEM_INDEX_DB", str(base / "index.db"))
    ).expanduser()
    memory_db = Path(
        plugin_config.get("memory_db")
        or os.environ.get("ENTROPICMEM_MEMORY_DB", str(base / "memory.db"))
    ).expanduser()
    return vault, index_db, memory_db


def load_plugin_config(hermes_home: Path) -> dict:
    """Return the EntropicMem config from ``{hermes_home}/config.yaml``.

    Both ``memory.entropicmem`` and ``plugins.entropicmem`` are read, with
    ``memory.entropicmem`` merged OVER ``plugins.entropicmem`` (the host-native
    ``memory.*`` location wins; the plugin location stays for backward
    compatibility).

    Returns ``{}`` when PyYAML is unavailable — but NEVER silently: the
    missing import is logged at WARNING level so a config that stops applying
    is visible in the logs instead of being quietly ignored. Parse failures
    log at DEBUG and return ``{}`` (a broken config must not break loading).
    """
    config_path = hermes_home / "config.yaml"
    if not config_path.is_file():
        return {}
    try:
        import yaml
    except ImportError:
        logger.warning(
            "entropicmem: PyYAML is not installed — ignoring plugin config at %s "
            "(install 'pyyaml' to honor plugins.entropicmem settings)",
            config_path,
        )
        return {}
    try:
        with open(config_path, encoding="utf-8-sig") as f:
            all_config = yaml.safe_load(f) or {}
        plugins = all_config.get("plugins") or {}
        memory = all_config.get("memory") or {}
        merged = dict(plugins.get("entropicmem") or {})
        merged.update(memory.get("entropicmem") or {})
        return merged
    except Exception as e:
        logger.debug("entropicmem: failed to parse plugin config %s: %s", config_path, e)
        return {}
