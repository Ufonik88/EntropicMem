"""Shared fixtures for the Hermes host-harness tests (EM-003).

The harness must exercise the CURRENT EntropicMem provider end-to-end the way
Hermes drives it, with each fake profile living in its own HERMES_HOME directory
(never the real ~/.hermes).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Same bootstrap tests/conftest.py does: plugin import needs `agent.memory_provider`,
# and the scripts dir must be importable (mirrors pytest ini pythonpath).
sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# No ML deps in the default test run. The optional embedding stack
# is an external model download (non-deterministic, seconds); a None entry in
# sys.modules makes `import sentence_transformers` raise ImportError exactly
# like a machine without it (CI) — the engine then uses its FTS-only path.
sys.modules.setdefault("sentence_transformers", None)

# Shared fixtures (home_a, home_b, make_provider) live in tests/conftest.py so
# tests/regressions can use them too (EM-101 fixture-scope fix).

