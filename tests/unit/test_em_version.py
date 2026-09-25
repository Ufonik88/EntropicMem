"""EM-201: version single-source tests.

``plugins/entropicmem/scripts/em/__init__.py`` carries ``__version__`` — the
single source of truth. ``pyproject.toml`` reads it via
``[tool.setuptools.dynamic]`` and ``plugin.yaml`` / the CLI must match it
(plan §5 EM-201 "Files" contract).

Static text scans only: no tomllib (3.11+; CI floor is 3.10) and no PyYAML
requirement (mirrors test_f011's approach in the regression suite).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = ROOT / "plugins" / "entropicmem" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import em  # noqa: E402

_PEP440_DEV = re.compile(r"^\d+\.\d+\.\d+\.dev\d+$")


def test_em_version_is_pep440_dev_of_3_0_0():
    assert _PEP440_DEV.match(em.__version__), em.__version__
    assert em.__version__.startswith("3.0.0.dev"), em.__version__


def _pyproject_text() -> str:
    return (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_pyproject_declares_dynamic_version_from_em():
    text = _pyproject_text()
    assert re.search(r'^\s*dynamic\s*=\s*\[\s*"version"\s*\]', text, re.M), (
        "pyproject [project] must declare dynamic = [\"version\"]"
    )
    assert re.search(
        r'^\s*version\s*=\s*\{\s*attr\s*=\s*"em\.__version__"\s*\}', text, re.M
    ), 'pyproject must read version via [tool.setuptools.dynamic] attr = "em.__version__"'
    # the static version line must be gone (single source)
    assert not re.search(r'^\s*version\s*=\s*"\d', text, re.M), (
        "pyproject still carries a static version string next to the dynamic one"
    )


def _plugin_yaml_version() -> str:
    text = (ROOT / "plugins" / "entropicmem" / "plugin.yaml").read_text(encoding="utf-8")
    m = re.search(r"^version:\s*[\"']?([^\s\"'#]+)", text, re.M)
    assert m, "plugin.yaml has no version line"
    return m.group(1)


def test_plugin_yaml_version_matches_em():
    assert _plugin_yaml_version() == em.__version__


def test_cli_version_matches_em():
    text = (_SCRIPTS / "entropicmem.py").read_text(encoding="utf-8")
    # the CLI must import the single source, not re-declare a literal
    assert re.search(r"^from em import .*__version__|^from em import __version__",
                     text, re.M), "entropicmem.py must import __version__ from em"
    assert not re.search(r'^__version__\s*=\s*"\d', text, re.M), (
        "entropicmem.py still hard-codes a version literal"
    )
