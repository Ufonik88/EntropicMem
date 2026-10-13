"""``identity_signature()``'s config reader (§3.5, EM-402).

    identity_signature() returns {"provider":"entropicmem","schema":3,
    "scope_mode":<resolved from config file>} — cheap, no DB, safe on an
    uninitialized instance.

The host calls it on **every inbound message** to detect config changes, so the
resolved signature is cached against the file's ``(path, mtime, size)``: an
unchanged file is not re-parsed, a changed one is. The section merge mirrors
``_backend.load_plugin_config`` — ``memory.entropicmem`` over
``plugins.entropicmem`` in the home's ``config.yaml`` — because the signature
must not disagree with the config the session itself resolved.

This module touches nothing but the file it is handed: no host import, no
environment reads, no database (pinned by
``test_the_identity_reader_touches_nothing_but_the_file_it_is_handed``). A
missing home, a missing file, an unparseable file or an absent PyYAML all
degrade to the default signature — the hook must never raise.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional, Tuple, Union

from ..policy.scopes import resolve_scope_mode

logger = logging.getLogger(__name__)

#: The host-facing identity of this plugin (§3.5).
PROVIDER = "entropicmem"

#: The schema generation the signature reports. §3.5 names 3.
SCHEMA = 3

_PathLike = Union[str, Path]


def signature_for(scope_mode: str) -> dict:
    return {"provider": PROVIDER, "schema": SCHEMA, "scope_mode": scope_mode}


def default_signature() -> dict:
    """What an unknown config resolves to: §3.5's default mode, no file read."""
    return signature_for(resolve_scope_mode({}, {}))


def _plugin_section(data: Any) -> dict:
    """``plugins.entropicmem`` and ``memory.entropicmem``, the session's merge.

    ``memory.entropicmem`` (the host-native location) wins over
    ``plugins.entropicmem`` — the same precedence ``load_plugin_config``
    applies. A section that is not a mapping is ignored.
    """
    if not isinstance(data, dict):
        return {}
    merged: dict = {}
    plugins = data.get("plugins")
    if isinstance(plugins, dict):
        section = plugins.get("entropicmem")
        if isinstance(section, dict):
            merged.update(section)
    memory = data.get("memory")
    if isinstance(memory, dict):
        section = memory.get("entropicmem")
        if isinstance(section, dict):
            merged.update(section)
    return merged


def read_scope_mode(config_path: _PathLike) -> Optional[str]:
    """The configured ``scope_mode`` at *config_path*, or None when unknown.

    "Unknown" covers every failure mode: no PyYAML, an unreadable file, an
    unparseable file, no plugin section. The caller resolves None through
    :func:`resolve_scope_mode`, so a broken config falls back to the default
    instead of guessing.
    """
    try:
        import yaml
    except ImportError:
        logger.debug("entropicmem identity: PyYAML absent; using default scope_mode")
        return None
    try:
        text = Path(config_path).read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 - a broken config must never break the hook
        logger.debug("entropicmem identity: config unreadable; using default scope_mode",
                     exc_info=True)
        return None
    section = _plugin_section(data)
    mode = str(section.get("scope_mode") or "").strip().lower()
    return mode or None


class ConfigSignatureCache:
    """The signature for one config file, cached by ``(path, mtime, size)``.

    One cache instance per provider. Keying on mtime (and size, for editors
    that write within one tick) is what makes the per-message call cheap while
    still seeing every save.
    """

    def __init__(self) -> None:
        self._key: Optional[Tuple[str, Optional[int], Optional[int]]] = None
        self._signature: Optional[dict] = None

    @staticmethod
    def _stat_key(config_path: _PathLike) -> Tuple[str, Optional[int], Optional[int]]:
        try:
            st = os.stat(config_path)
        except OSError:
            return (str(config_path), None, None)
        return (str(config_path), st.st_mtime_ns, st.st_size)

    def signature(self, config_path: Optional[_PathLike]) -> dict:
        if config_path is None:
            return default_signature()
        key = self._stat_key(config_path)
        if self._signature is not None and key == self._key:
            return self._signature
        mode = read_scope_mode(config_path)
        signature = signature_for(resolve_scope_mode({}, {"scope_mode": mode or ""}))
        self._key = key
        self._signature = signature
        return signature

    def reset(self) -> None:
        """Forget the cached signature (a home change re-keys implicitly)."""
        self._key = None
        self._signature = None
