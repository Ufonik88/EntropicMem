"""Phase 5 CLI smoke tests."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CLI = str(_ROOT / "skills/entropicmem/scripts/entropicmem.py")


def _run(*args, **env):
    return subprocess.run(
        [sys.executable, _CLI, *args],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )


def test_recall_after_remember():
    with tempfile.TemporaryDirectory() as td:
        vp = Path(td) / "vault"
        ip = Path(td) / "index.db"
        mp = Path(td) / "memory.db"
        env = {
            "ENTROPICMEM_VAULT_PATH": str(vp),
            "ENTROPICMEM_INDEX_DB": str(ip),
            "ENTROPICMEM_MEMORY_DB": str(mp),
        }
        assert _run("init", "--vault", str(vp), "--index-db", str(ip), **env).returncode == 0
        r = _run("remember", "Phase five recall smoke test fact", **env)
        assert r.returncode == 0
        r2 = _run("recall", "recall smoke", "--top-k", "5", **env)
        assert r2.returncode == 0
        assert "recall smoke" in r2.stdout.lower() or "Phase five" in r2.stdout


def test_memory_list():
    with tempfile.TemporaryDirectory() as td:
        vp = Path(td) / "vault"
        ip = Path(td) / "index.db"
        mp = Path(td) / "memory.db"
        env = {
            "ENTROPICMEM_VAULT_PATH": str(vp),
            "ENTROPICMEM_INDEX_DB": str(ip),
            "ENTROPICMEM_MEMORY_DB": str(mp),
        }
        _run("init", "--vault", str(vp), "--index-db", str(ip), **env)
        _run("remember", "List test fact one", **env)
        r = _run("memory", "list", "--limit", "10", **env)
        assert r.returncode == 0
        assert len(r.stdout.strip().splitlines()) >= 1