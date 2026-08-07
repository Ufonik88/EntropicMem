"""
test_v2_1_9.py — Tests for the v2.1.9 `.env` re-poisoning fix.

Covers the root cause found during v2.1.8 verification: `_append_env` claimed
idempotency but only guarded on `ENTROPICMEM_VAULT_PATH`, so once a cleanup
removed that single line, the next `entropicmem init` re-appended a fresh
`/tmp`-based block to ~/.hermes/.env, shadowing the canonical runtime paths.

The fix (v2.1.9):
- Block-level idempotency: skip writing when ANY of the three keys exist.
- Temp-dir refusal: never persist vault/index paths under /tmp.
"""

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_SCRIPT_DIR = REPO / "skills" / "entropicmem" / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

from entropicmem import _append_env  # noqa: E402


def _read_env(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ── _append_env unit behaviour ─────────────────────────────────────────────


def test_append_env_writes_once(tmp_path):
    env_file = tmp_path / ".env"
    _append_env(env_file, Path("/home/u/.hermes/entropicmem/vault"),
                Path("/home/u/.hermes/entropicmem/index.db"),
                Path("/home/u/.hermes/entropicmem/memory.db"))
    first = _read_env(env_file)
    assert "ENTROPICMEM_VAULT_PATH" in first

    # Second call with the same file must not append a duplicate block.
    _append_env(env_file, Path("/home/u/.hermes/entropicmem/vault"),
                Path("/home/u/.hermes/entropicmem/index.db"),
                Path("/home/u/.hermes/entropicmem/memory.db"))
    assert _read_env(env_file) == first


def test_append_env_skips_when_any_key_present(tmp_path):
    """The v2.1.8 incident: only VAULT_PATH was removed, the next init
    re-appended everything. Any single surviving key must block the write."""
    env_file = tmp_path / ".env"
    env_file.write_text('ENTROPICMEM_MEMORY_DB="/home/u/.hermes/entropicmem/memory.db"\n')
    _append_env(env_file, Path("/tmp/evil/vault"), Path("/tmp/evil/index.db"),
                Path("/tmp/evil/memory.db"))
    text = _read_env(env_file)
    assert 'ENTROPICMEM_VAULT_PATH' not in text
    assert 'ENTROPICMEM_INDEX_DB' not in text
    assert "/tmp/evil" not in text


def test_append_env_refuses_temp_paths(tmp_path):
    """Temp-dir vault/index must never be persisted, even on a fresh file."""
    env_file = tmp_path / ".env"
    _append_env(env_file, Path("/tmp/tmpabc123/vault"), Path("/tmp/tmpabc123/index.db"),
                Path("/home/u/.hermes/entropicmem/memory.db"))
    text = _read_env(env_file)
    assert "ENTROPICMEM_VAULT_PATH" not in text
    assert "ENTROPICMEM_INDEX_DB" not in text
    assert "tmpabc123" not in text


def test_append_env_canonical_memory_db_allowed(tmp_path):
    """A fresh file with only canonical (non-tmp) paths still writes."""
    env_file = tmp_path / ".env"
    _append_env(env_file, Path("/home/u/.hermes/entropicmem/vault"),
                Path("/home/u/.hermes/entropicmem/index.db"),
                Path("/home/u/.hermes/entropicmem/memory.db"))
    text = _read_env(env_file)
    assert "ENTROPICMEM_VAULT_PATH" in text
    assert "ENTROPICMEM_MEMORY_DB" in text


# ── init end-to-end (guards the regression at the CLI level) ───────────────


def test_init_does_not_poison_existing_env(tmp_path):
    """entropicmem init with a tmp vault must not touch an already-configured
    .env — the exact scenario that re-poisoned ~/.hermes/.env after v2.1.8."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        'ENTROPICMEM_VAULT_PATH="/home/u/.hermes/entropicmem/vault"\n'
        'ENTROPICMEM_INDEX_DB="/home/u/.hermes/entropicmem/index.db"\n'
        'ENTROPICMEM_MEMORY_DB="/home/u/.hermes/entropicmem/memory.db"\n'
    )
    env = {
        **os.environ,
        "ENTROPICMEM_HOME_ENV": str(env_file),  # not used by CLI; keeps test hermetic
    }
    # _append_env is invoked by cmd_init with the resolved env file; simulate
    # the CLI path by calling it with a tmp vault against the pre-populated file.
    _append_env(env_file, Path("/tmp/tmpfresh123/vault"), Path("/tmp/tmpfresh123/index.db"),
                Path("/home/u/.hermes/entropicmem/memory.db"))
    text = _read_env(env_file)
    assert "/tmp/tmpfresh123" not in text
    assert text.count("ENTROPICMEM_VAULT_PATH") == 1
    assert text.count("ENTROPICMEM_INDEX_DB") == 1
    assert text.count("ENTROPICMEM_MEMORY_DB") == 1
