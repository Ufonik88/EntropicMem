"""Conftest for smart context tests."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "plugins" / "entropicmem" / "scripts"))
# harness fakes (FakeHost) must be importable from any test dir, not only
# when tests/harness happens to be collected first
sys.path.insert(0, str(Path(__file__).parent / "harness"))

# Mock the agent.memory_provider module before importing plugin
mock_memory_provider = MagicMock()
sys.modules["agent"] = MagicMock()
sys.modules["agent.memory_provider"] = mock_memory_provider
mock_memory_provider.MemoryProvider = type("MemoryProvider", (), {})


# ── the graph server's search bucket is per process (EM-606) ────────────────
# /api/search is rate limited in the server module itself, which is imported
# once per pytest session — so without this reset one test's searches would
# spend the next test's tokens. The bucket is replaced with a fresh one; the
# module is only touched when a test has already imported it, so this adds no
# fastapi dependency to the suite.

@pytest.fixture(autouse=True)
def _fresh_graph_search_bucket():
    mod = sys.modules.get("graph_server.server")
    if mod is not None:
        mod._SEARCH_LIMITER = mod.TokenBucket(mod.SEARCH_RATE_PER_SECOND)
    yield


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
