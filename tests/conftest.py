"""Conftest for smart context tests."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "entropicmem" / "scripts"))

# Mock the agent.memory_provider module before importing plugin
mock_memory_provider = MagicMock()
sys.modules["agent"] = MagicMock()
sys.modules["agent.memory_provider"] = mock_memory_provider
mock_memory_provider.MemoryProvider = type("MemoryProvider", (), {})
