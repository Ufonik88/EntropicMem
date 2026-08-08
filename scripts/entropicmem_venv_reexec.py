"""
entropicmem_venv_reexec.py — shared embedder-environment bootstrap (v2.2.0).

The sentence-transformers embedder lives ONLY in the Hermes venv
(~/.hermes/hermes-agent/venv). Scripts that write facts (cron helper, Notion
sync) must run under that interpreter so `remember()` embeds on insert.

Call `ensure_embedder()` as early as possible (after stdlib imports, before
any EntropicMem engine import): if the current interpreter already has
sentence-transformers it returns immediately; otherwise it re-execs the whole
script with the venv Python. Keeping this in ONE module prevents the two
write-path scripts from drifting in behavior.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
_VENV_PYTHON = HERMES_HOME / "hermes-agent" / "venv" / "bin" / "python3"


def ensure_embedder() -> None:
    """Re-exec via the Hermes venv Python if sentence-transformers is missing.

    No-op when the embedder is already importable (the common case when the
    script runs under the venv). Safe to call multiple times.

    Never loops: if the venv Python is already the running interpreter (or is
    missing entirely) and the import still fails, warn on stderr and continue
    without embeddings rather than re-exec'ing again.
    """
    try:
        import sentence_transformers  # noqa: F401
        return
    except ImportError:
        pass
    venv_python = str(_VENV_PYTHON)
    if not _VENV_PYTHON.exists():
        print(
            f"WARN: sentence-transformers unavailable and venv Python missing: "
            f"{venv_python}; continuing without embeddings",
            file=sys.stderr,
        )
        return
    if os.path.realpath(sys.executable) == os.path.realpath(venv_python):
        print(
            "WARN: sentence-transformers unavailable even under the Hermes "
            "venv; continuing without embeddings",
            file=sys.stderr,
        )
        return
    os.execv(venv_python, [venv_python, *sys.argv])
