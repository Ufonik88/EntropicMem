"""EM-402: ``identity_signature()``'s config-file reader (``em.provider.identity``).

§3.5: the signature is ``{"provider","schema","scope_mode"}`` with ``scope_mode``
**resolved from the config file** — cheap, no DB, safe on an uninitialized
instance, and cached by file mtime because the host calls it on every inbound
message to detect config changes.

The tests pin the four properties that make it safe to call per message: it
reads only the config file, its cache is keyed by mtime (a change is seen, an
unchanged file is not re-parsed), a broken or missing config degrades to the
default signature without raising, and its section merge cannot disagree with
the loader the session itself uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins" / "entropicmem" / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from em.policy.scopes import resolve_scope_mode  # noqa: E402
from em.provider import identity  # noqa: E402


def _write(path: Path, text: str, mtime: float) -> None:
    path.write_text(text, encoding="utf-8")
    import os

    os.utime(path, (mtime, mtime))


PLUGIN_ONLY = (
    "plugins:\n"
    "  entropicmem:\n"
    "    scope_mode: chat\n"
)
MEMORY_SECTION_WINS = (
    "plugins:\n"
    "  entropicmem:\n"
    "    scope_mode: chat\n"
    "memory:\n"
    "  entropicmem:\n"
    "    scope_mode: user\n"
)


# -- the signature -----------------------------------------------------------


def test_the_signature_shape_is_the_three_fields_section_3_5_names():
    sig = identity.default_signature()
    assert sig == {"provider": "entropicmem", "schema": 3, "scope_mode": "profile"}
    assert set(sig) == {"provider", "schema", "scope_mode"}


def test_scope_mode_comes_from_the_config_file(tmp_path):
    cfg = tmp_path / "config.yaml"
    _write(cfg, PLUGIN_ONLY, mtime=100.0)
    assert identity.ConfigSignatureCache().signature(cfg)["scope_mode"] == "chat"

    _write(cfg, "plugins:\n  entropicmem:\n    scope_mode: user\n", mtime=200.0)
    assert identity.ConfigSignatureCache().signature(cfg)["scope_mode"] == "user"


def test_the_memory_section_wins_like_the_session_loader(tmp_path):
    """``memory.entropicmem`` merges OVER ``plugins.entropicmem``
    (``_backend.load_plugin_config``) — identity must not disagree with the
    config the session resolved."""
    cfg = tmp_path / "config.yaml"
    _write(cfg, MEMORY_SECTION_WINS, mtime=100.0)
    assert identity.ConfigSignatureCache().signature(cfg)["scope_mode"] == "user"

    from plugins.entropicmem import _backend

    merged = _backend.load_plugin_config(cfg.parent)
    assert resolve_scope_mode({}, merged) == identity.ConfigSignatureCache().signature(cfg)["scope_mode"]


def test_an_unset_scope_mode_reads_as_the_default(tmp_path):
    cfg = tmp_path / "config.yaml"
    _write(cfg, "plugins:\n  entropicmem:\n    min_relevance_score: 0.4\n", mtime=100.0)
    assert identity.ConfigSignatureCache().signature(cfg)["scope_mode"] == "profile"


# -- the mtime cache ---------------------------------------------------------


def test_an_unchanged_file_is_not_re_parsed(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    _write(cfg, PLUGIN_ONLY, mtime=100.0)
    calls = []
    real = identity.read_scope_mode

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(identity, "read_scope_mode", counting)
    cache = identity.ConfigSignatureCache()
    cache.signature(cfg)
    cache.signature(cfg)
    assert len(calls) == 1, "same mtime: one parse, not one per message"


def test_a_changed_file_is_re_parsed_and_the_new_mode_reported(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    _write(cfg, PLUGIN_ONLY, mtime=100.0)
    calls = []
    real = identity.read_scope_mode

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(identity, "read_scope_mode", counting)
    cache = identity.ConfigSignatureCache()
    first = cache.signature(cfg)
    _write(cfg, "plugins:\n  entropicmem:\n    scope_mode: profile\n", mtime=200.0)
    second = cache.signature(cfg)
    assert len(calls) == 2
    assert first["scope_mode"] == "chat"
    assert second["scope_mode"] == "profile"


def test_the_cache_is_per_file_not_global(tmp_path):
    a = tmp_path / "a" / "config.yaml"
    b = tmp_path / "b" / "config.yaml"
    a.parent.mkdir()
    b.parent.mkdir()
    _write(a, PLUGIN_ONLY, mtime=100.0)
    _write(b, "plugins:\n  entropicmem:\n    scope_mode: user\n", mtime=100.0)
    cache = identity.ConfigSignatureCache()
    assert cache.signature(a)["scope_mode"] == "chat"
    assert cache.signature(b)["scope_mode"] == "user"
    assert cache.signature(a)["scope_mode"] == "chat"


# -- safety: uninitialized, missing, broken ----------------------------------


def test_a_missing_file_or_path_gives_the_default_and_never_raises(tmp_path):
    cache = identity.ConfigSignatureCache()
    assert cache.signature(None) == identity.default_signature()
    assert cache.signature(tmp_path / "nope.yaml") == identity.default_signature()


def test_an_unparseable_config_degrades_to_the_default(tmp_path):
    cfg = tmp_path / "config.yaml"
    _write(cfg, "plugins: [unclosed\n\ttab", mtime=100.0)
    assert identity.ConfigSignatureCache().signature(cfg) == identity.default_signature()


def test_an_uninstalled_yaml_degrades_to_the_default(monkeypatch, tmp_path):
    import builtins

    cfg = tmp_path / "config.yaml"
    _write(cfg, PLUGIN_ONLY, mtime=100.0)
    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_yaml)
    assert identity.ConfigSignatureCache().signature(cfg) == identity.default_signature()


def test_a_scope_mode_config_of_another_shape_is_ignored(tmp_path):
    cfg = tmp_path / "config.yaml"
    _write(cfg, "plugins:\n  entropicmem:\n    scope_mode: 7\n", mtime=100.0)
    assert identity.ConfigSignatureCache().signature(cfg)["scope_mode"] == "profile"


# -- "reads only the config file" --------------------------------------------


def test_the_identity_reader_touches_nothing_but_the_file_it_is_handed():
    """AST scan: no host import, no environment read, no database — the §3.5
    "cheap, no DB, safe on an uninitialized instance" contract."""
    import ast

    tree = ast.parse((SCRIPTS / "em" / "provider" / "identity.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert not name.startswith("agent"), f"host import in identity.py: {name}"
            assert name != "sqlite3", "identity_signature must not touch a database"
            assert not name.startswith("em.store"), "identity_signature must not touch a database"
    source = (SCRIPTS / "em" / "provider" / "identity.py").read_text(encoding="utf-8")
    assert "os.environ" not in source
    assert "HERMES_HOME" not in source
