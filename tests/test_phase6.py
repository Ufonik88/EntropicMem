"""Phase 6 plugin backend tests."""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugins" / "entropicmem"))

from _backend import resolve_paths, resolve_scripts_dir


def test_resolve_scripts_from_repo():
    scripts = resolve_scripts_dir(ROOT)
    assert scripts is not None
    assert (scripts / "memory_engine.py").is_file()


def test_resolve_paths_defaults():
    with tempfile.TemporaryDirectory() as td:
        hh = Path(td)
        v, i, m = resolve_paths(hh, {})
        assert v.name == "vault"
        assert m.name == "memory.db"