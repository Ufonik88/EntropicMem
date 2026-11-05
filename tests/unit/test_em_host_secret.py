"""The plugin's credential resolver follows the host's profile secret scope.

Regression for the catalog review on the 3.0.0 re-pin: the formation LLM and the
embedding backends read their API keys straight from ``os.environ``. In a host
serving several profiles that returns the launch profile's value to every
profile, so the key must come through ``agent.secret_scope.get_secret`` when the
host is present, and only degrade to ``os.environ`` when it is genuinely absent
(standalone CLI, bare pip install).

Invented data only: Acme.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em import host_secret  # noqa: E402

KEY = "ENTROPICMEM_LLM_API_KEY"


def _install_host(monkeypatch, resolver) -> None:
    """Put a stand-in ``agent.secret_scope`` in ``sys.modules``.

    Importable for the duration of one test, with no Hermes install required.
    """
    module = types.ModuleType("agent.secret_scope")
    module.get_secret = resolver
    package = types.ModuleType("agent")
    package.secret_scope = module
    monkeypatch.setitem(sys.modules, "agent", package)
    monkeypatch.setitem(sys.modules, "agent.secret_scope", module)


def test_the_profile_scope_wins_over_the_process_environment(monkeypatch):
    monkeypatch.setenv(KEY, "launch-profile-key")
    _install_host(monkeypatch, lambda name, default=None: "scoped-key")

    assert host_secret.get_secret(KEY) == "scoped-key", (
        "the active profile's value must beat the process environment"
    )


def test_a_host_without_the_agent_package_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv(KEY, "standalone-key")
    for name in ("agent", "agent.secret_scope"):
        monkeypatch.setitem(sys.modules, name, None)  # makes the import raise

    assert host_secret.get_secret(KEY) == "standalone-key", (
        "outside Hermes, os.environ is the only source there is"
    )


def test_an_unscoped_host_read_fails_closed(monkeypatch):
    monkeypatch.setenv(KEY, "launch-profile-key")

    def unscoped(name, default=None):
        raise RuntimeError("UnscopedSecretError")

    _install_host(monkeypatch, unscoped)

    assert host_secret.get_secret(KEY, "fallback") == "fallback", (
        "a missing profile scope must never borrow the launch profile's value"
    )


def test_an_unset_secret_returns_the_default(monkeypatch):
    monkeypatch.setenv(KEY, "launch-profile-key")
    _install_host(monkeypatch, lambda name, default=None: None)

    assert host_secret.get_secret(KEY, "") == ""


def test_the_requested_name_is_passed_through(monkeypatch):
    seen = []

    def recording(name, default=None):
        seen.append(name)
        return "value"

    _install_host(monkeypatch, recording)
    assert host_secret.get_secret("ENTROPICMEM_EMBEDDINGS_API_KEY") == "value"
    assert seen == ["ENTROPICMEM_EMBEDDINGS_API_KEY"]
