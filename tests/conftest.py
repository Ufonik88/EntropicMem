"""Conftest for smart context tests."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "plugins" / "entropicmem" / "scripts"))

# Mock the agent.memory_provider module before importing plugin
mock_memory_provider = MagicMock()
sys.modules["agent"] = MagicMock()
sys.modules["agent.memory_provider"] = mock_memory_provider
mock_memory_provider.MemoryProvider = type("MemoryProvider", (), {})


# ── shared host-harness fixtures (EM-003) — visible to every test dir ────────
# Previously these lived only in tests/harness/conftest.py, which silently
# broke tests/regressions (strict xfail swallowed the setup errors, so the
# harness-based regression tests never actually ran).

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


@pytest.fixture()
def make_provider():
    """Factory: fresh EntropicMem provider instance (constructor config is test-only)."""
    from plugins.entropicmem import EntropicMemMemoryProvider

    def _make(config=None):
        return EntropicMemMemoryProvider(config=dict(config or {}))

    return _make
