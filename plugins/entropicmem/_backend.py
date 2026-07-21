"""EntropicMem backend — resolve skill scripts and env paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Tuple


def hermes_home_from_kwargs(kwargs: dict) -> Path:
    hh = kwargs.get("hermes_home") or os.environ.get("HERMES_HOME", "")
    if hh:
        return Path(hh).expanduser().resolve()
    return Path.home() / ".hermes"


def resolve_scripts_dir(hermes_home: Path) -> Optional[Path]:
    candidates = [
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
    vault = Path(
        plugin_config.get("vault_path")
        or os.environ.get("ENTROPICMEM_VAULT_PATH", str(hermes_home / "entropicmem" / "vault"))
    ).expanduser()
    index_db = Path(
        plugin_config.get("index_db")
        or os.environ.get("ENTROPICMEM_INDEX_DB", str(hermes_home / "entropicmem" / "index.db"))
    ).expanduser()
    memory_db = Path(
        plugin_config.get("memory_db")
        or os.environ.get("ENTROPICMEM_MEMORY_DB", str(hermes_home / "entropicmem" / "memory.db"))
    ).expanduser()
    return vault, index_db, memory_db


def load_plugin_config(hermes_home: Path) -> dict:
    config_path = hermes_home / "config.yaml"
    if not config_path.is_file():
        return {}
    try:
        import yaml

        with open(config_path, encoding="utf-8-sig") as f:
            all_config = yaml.safe_load(f) or {}
        plugins = all_config.get("plugins") or {}
        return dict(plugins.get("entropicmem") or {})
    except Exception:
        return {}
