"""Conftest for regression tests.

Reuses the harness fixtures (make_provider, home_a, home_b) that set up
sys.path, sys.modules mocks, and FakeHost integration.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Same bootstrap as the harness conftest + tests/conftest.py
sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Harness dir (where fake_host and memory_engine live)
HARNESS = ROOT / "tests" / "harness"
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

# Plan §6.1: no ML deps in default test run. Block embedding imports so the
# engine uses its FTS-only path (same as harness conftest).
sys.modules.setdefault("sentence_transformers", None)
