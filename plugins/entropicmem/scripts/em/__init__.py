"""EntropicMem v3 storage core (``em.*``).

Single source of truth for the project version: ``pyproject.toml`` reads it
via ``[tool.setuptools.dynamic]`` and ``plugins/entropicmem/plugin.yaml`` is
kept in sync by a test (``tests/unit/test_em_version.py``).

Rules (plan §3.2): modules under ``em.*`` are stdlib-only, never import the
Hermes host or the provider layer, and never read ``os.environ["HERMES_HOME"]``
— paths are passed in explicitly.
"""

__version__ = "3.0.0.dev0"
