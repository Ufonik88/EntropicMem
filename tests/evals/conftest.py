"""Bootstrap for evals tests: make the repo root importable as `evals.*`.

Mirrors tests/conftest.py (scripts dir on sys.path, Hermes host module mocked)
so the provider-backed v2 adapter can be constructed without a Hermes install.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SCRIPTS = _REPO_ROOT / "plugins" / "entropicmem" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# Mock the agent.memory_provider module before importing the plugin (same
# pattern as the top-level tests/conftest.py).
_mock_memory_provider = MagicMock()
sys.modules.setdefault("agent", MagicMock())
sys.modules.setdefault("agent.memory_provider", _mock_memory_provider)
_mock_memory_provider.MemoryProvider = type("MemoryProvider", (), {})
