"""Shared fixtures for the Hermes host-harness tests (EM-003).

The harness must exercise the CURRENT EntropicMem provider end-to-end the way
Hermes drives it, with each fake profile living in its own HERMES_HOME directory
(never the real ~/.hermes).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Same bootstrap tests/conftest.py does: plugin import needs `agent.memory_provider`,
# and the scripts dir must be importable (mirrors pytest ini pythonpath).
sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Plan §6.1: no ML deps in the default test run. The optional embedding stack
# is an external model download (non-deterministic, seconds); a None entry in
# sys.modules makes `import sentence_transformers` raise ImportError exactly
# like a machine without it (CI) — the engine then uses its FTS-only path.
sys.modules.setdefault("sentence_transformers", None)


@pytest.fixture()
def home_a(tmp_path):
    """Fake HERMES_HOME for profile A, with plugin config pointing inside it."""
    home = tmp_path / "homeA"
    _write_home_config(home)
    return home


@pytest.fixture()
def home_b(tmp_path):
    """Second fake HERMES_HOME: same process, different profile."""
    home = tmp_path / "homeB"
    _write_home_config(home)
    return home


def _write_home_config(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "plugins:\n"
        "  entropicmem:\n"
        f"    vault_path: {home / 'entropicmem' / 'vault'}\n"
        f"    index_db: {home / 'entropicmem' / 'index.db'}\n"
        f"    memory_db: {home / 'entropicmem' / 'memory.db'}\n",
        encoding="utf-8",
    )


@pytest.fixture()
def make_provider():
    """Factory: fresh EntropicMem provider instance (constructor config is test-only)."""
    from plugins.entropicmem import EntropicMemMemoryProvider

    def _make(config=None):
        return EntropicMemMemoryProvider(config=dict(config or {}))

    return _make
