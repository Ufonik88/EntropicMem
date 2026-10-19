"""Best-effort POSIX permission helpers for files that hold memory content.

The v3 store already applies this policy in :mod:`em.store.db`; vault notes,
the v2 search index and encryption artefacts use the same rule here so a local
account cannot read another account's memory.
"""

from __future__ import annotations

import os

__all__ = ["chmod_posix"]


def chmod_posix(path: "os.PathLike[str] | str", mode: int) -> None:
    """Set *mode* on POSIX; a no-op on Windows and filesystems without it."""
    if os.name == "nt":  # pragma: no cover - POSIX-only hardening
        return
    try:
        os.chmod(str(path), mode)
    except OSError:
        pass  # best-effort; e.g. a filesystem without permission support
