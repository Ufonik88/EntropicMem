"""Read plugin credentials through the host's profile-aware secret scope.

Hermes resolves a profile's credentials with :func:`agent.secret_scope.get_secret`,
which returns the value bound to the *active profile* rather than whatever the
process launched with. Reading ``os.environ`` directly in a multi-profile
gateway returns the launch profile's value for every profile, which is the leak
this module exists to close.

The host import stays lazy and fully guarded so ``em`` keeps its no-host rule:

* the ``agent`` package is absent (standalone CLI, a bare pip install) — fall
  back to ``os.environ``, which is the only source there is;
* the host is present but the caller has no profile scope bound while
  multiplexing — return ``default`` and never borrow ``os.environ``. That case
  is a spawn-site bug in the host, and reading the launch profile's secret to
  paper over it is exactly the cross-profile leak the host's guard prevents.
"""

from __future__ import annotations

import os

__all__ = ["get_secret"]


def get_secret(name: str, default: str = "") -> str:
    """The active profile's value for *name*, or *default* when unset."""
    try:
        from agent.secret_scope import get_secret as host_get_secret
    except Exception:  # host package absent: standalone CLI / bare install
        return os.environ.get(name, default)
    try:
        value = host_get_secret(name)
    except Exception:  # UnscopedSecretError under multiplexing: fail closed
        return default
    return default if value is None else value
