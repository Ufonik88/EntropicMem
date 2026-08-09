"""
test_v2_1_8.py — Tests for the v2.1.8 index/FTS/gate maintenance release.

Covers:
- `entropicmem index rebuild|status` CLI (vault index maintenance)
- MemoryEngine.rebuild_fts() orphan repair + CLI `memory reindex`
- Health check: FTS orphan detection, stability-gate current-streak semantics
- daily_stability_gate.count_consecutive_ok current-streak semantics
"""

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_SCRIPT_DIR = REPO / "skills" / "entropicmem" / "scripts"
_CLI = str(_SCRIPT_DIR / "entropicmem.py")
_HEALTH = REPO / "scripts" / "entropicmem_health_check.py"
_GATE = REPO / "scripts" / "daily_stability_gate.py"
sys.path.insert(0, str(_SCRIPT_DIR))

from index import VaultIndex
from memory_engine import MemoryEngine
from vault import Vault


def _run(*args, **env):
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, _CLI, *args],
        capture_output=True, text=True, env=full_env,
    )


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def vault_env(tmp_path):
    """Temp vault + index DB wired through the CLI env overrides."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    index_db = tmp_path / "index.db"
    env = {
        "ENTROPICMEM_VAULT_PATH": str(vault_dir),
        "ENTROPICMEM_INDEX_DB": str(index_db),
    }
    return vault_dir, index_db, env


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "memory.db"
    eng = MemoryEngine(db_path)
    yield eng
    eng.close()


# ── index rebuild CLI ──────────────────────────────────────────────────────


def test_index_rebuild_reindexes_vault_notes(vault_env):
    vault_dir, index_db, env = vault_env
    vault = Vault(vault_dir)
    for title in ("Alpha Note", "Beta Note"):
        path = vault.write_note(
            folder="Knowledge", title=title,
            body=f"Body of {title}. Enough content to pass the lint floor.",
            tags=["test"],
        )
        # write_note returns a vault-relative path; resolve against the vault
        assert (vault_dir / path).exists()
    assert not index_db.exists() or True  # index may not exist yet

    result = _run("index", "rebuild", **env)
    assert result.returncode == 0, result.stderr
    assert "Index rebuilt: 2 notes" in result.stdout

    conn = sqlite3.connect(str(index_db))
    count = conn.execute("SELECT COUNT(*) FROM notes_meta").fetchone()[0]
    titles = {r[0] for r in conn.execute("SELECT title FROM notes_meta")}
    conn.close()
    assert count == 2
    assert {"Alpha Note", "Beta Note"} <= titles


def test_index_rebuild_picks_up_late_note(vault_env):
    """A note added after the first rebuild is indexed by the next rebuild."""
    vault_dir, index_db, env = vault_env
    vault = Vault(vault_dir)
    vault.write_note(folder="Knowledge", title="First",
                     body="First note body, long enough to index cleanly.", tags=[])
    assert _run("index", "rebuild", **env).returncode == 0

    vault.write_note(folder="Knowledge", title="Second",
                     body="Second note body, long enough to index cleanly.", tags=[])
    result = _run("index", "rebuild", **env)
    assert result.returncode == 0

    conn = sqlite3.connect(str(index_db))
    titles = {r[0] for r in conn.execute("SELECT title FROM notes_meta")}
    conn.close()
    assert {"First", "Second"} <= titles


def test_index_status_reports_freshness(vault_env):
    vault_dir, index_db, env = vault_env
    vault = Vault(vault_dir)
    vault.write_note(folder="Knowledge", title="Only",
                     body="Only note body, long enough to index cleanly.", tags=[])
    _run("index", "rebuild", **env)

    result = _run("index", "status", **env)
    assert result.returncode == 0, result.stderr
    assert "Notes:" in result.stdout
    assert "Age:" in result.stdout
    assert "1" in result.stdout.split("Notes:")[1].split("\n")[0]


def test_index_status_missing_db(vault_env):
    _, _, env = vault_env
    result = _run("index", "status", **env)
    assert result.returncode == 1
    assert "missing" in result.stdout


# ── FTS rebuild ────────────────────────────────────────────────────────────


def test_rebuild_fts_removes_orphans(engine):
    engine.remember("durable fact one", domain="Test", importance=0.5)
    engine.remember("durable fact two", domain="Test", importance=0.5)

    # Inject an orphan FTS row with a rowid that matches no fact.
    max_rowid = engine.db.execute("SELECT MAX(rowid) FROM facts").fetchone()[0]
    engine.db.execute(
        "INSERT INTO facts_fts (rowid, content, title, tags, domain) VALUES (?, ?, ?, ?, ?)",
        (max_rowid + 100, "ghost content", "ghost", "", "Test"),
    )
    engine.db.commit()

    orphans = engine.db.execute(
        "SELECT COUNT(*) FROM facts_fts WHERE rowid NOT IN (SELECT rowid FROM facts)"
    ).fetchone()[0]
    assert orphans == 1

    r = engine.rebuild_fts()
    assert r["fts_after"] == r["facts"] == 2

    orphans_after = engine.db.execute(
        "SELECT COUNT(*) FROM facts_fts WHERE rowid NOT IN (SELECT rowid FROM facts)"
    ).fetchone()[0]
    assert orphans_after == 0


def test_rebuild_fts_is_audited(engine):
    engine.remember("audited fact", domain="Test", importance=0.5)
    engine.rebuild_fts()
    events = [row[0] for row in engine.db.execute(
        "SELECT action FROM audit_log").fetchall()]
    assert "fts_rebuild" in events


def test_cli_memory_reindex(tmp_path):
    db = tmp_path / "mem.db"
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    # remember projects to the vault — pin all three paths so stale
    # ENTROPICMEM_* env vars in the calling shell cannot poison the run
    env = {
        **os.environ,
        "ENTROPICMEM_MEMORY_DB": str(db),
        "ENTROPICMEM_VAULT_PATH": str(vault_dir),
        "ENTROPICMEM_INDEX_DB": str(tmp_path / "index.db"),
    }
    assert _run("remember", "reindex me", "--domain", "Test", **env).returncode == 0
    result = _run("memory", "reindex", **env)
    assert result.returncode == 0, result.stderr
    assert "FTS rebuilt:" in result.stdout


# ── health check: FTS orphan detection ─────────────────────────────────────


def test_health_check_flags_fts_orphans(tmp_path):
    hermes_home = tmp_path / "hermes"
    (hermes_home / "entropicmem").mkdir(parents=True)
    (hermes_home / "backups").mkdir()
    db_path = hermes_home / "entropicmem" / "memory.db"

    eng = MemoryEngine(db_path)
    eng.remember("clean fact", domain="Test", importance=0.5)
    max_rowid = eng.db.execute("SELECT MAX(rowid) FROM facts").fetchone()[0]
    eng.db.execute(
        "INSERT INTO facts_fts (rowid, content, title, tags, domain) VALUES (?, ?, ?, ?, ?)",
        (max_rowid + 5, "orphan", "", "", ""),
    )
    eng.db.commit()
    eng.close()

    env = {**os.environ, "HERMES_HOME": str(hermes_home)}
    result = subprocess.run(
        [sys.executable, str(_HEALTH)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    report = json.loads(result.stdout)
    fts = report["checks"]["fts"]
    assert fts["status"] == "WARN"
    assert fts["fts_orphans"] == 1
    assert "reindex" in fts["note"]


def test_health_check_fts_ok_when_clean(tmp_path):
    hermes_home = tmp_path / "hermes"
    (hermes_home / "entropicmem").mkdir(parents=True)
    (hermes_home / "backups").mkdir()
    db_path = hermes_home / "entropicmem" / "memory.db"

    eng = MemoryEngine(db_path)
    eng.remember("clean fact only", domain="Test", importance=0.5)
    eng.close()

    env = {**os.environ, "HERMES_HOME": str(hermes_home)}
    result = subprocess.run(
        [sys.executable, str(_HEALTH)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    report = json.loads(result.stdout)
    assert report["checks"]["fts"]["status"] == "OK"


# ── stability gate: current-streak semantics ──────────────────────────────


def _write_gate_log(log_path: Path, statuses: list[str], end: date | None = None):
    """Write one line per day, oldest first, ending at `end` (default today)."""
    end = end or date.today()
    start = end - timedelta(days=len(statuses) - 1)
    lines = []
    for i, s in enumerate(statuses):
        lines.append(f"{(start + timedelta(days=i)).isoformat()},{s}")
    log_path.write_text("\n".join(lines) + "\n")


def _gate_count(gate_log: Path) -> int:
    gate = _load_module("daily_stability_gate", _GATE)
    gate.GATE_LOG = gate_log
    return gate.count_consecutive_ok()


def test_gate_counts_current_streak_not_historical(tmp_path):
    log = tmp_path / "stability_gate.log"
    # 3 OK days long ago, then WARN, then 2 OK days ending today.
    _write_gate_log(log, ["OK", "OK", "OK", "WARN", "OK", "OK"])
    assert _gate_count(log) == 2  # NOT 3 (the historical longest)


def test_gate_streak_broken_by_gap(tmp_path):
    log = tmp_path / "stability_gate.log"
    end = date.today()
    lines = [
        (end - timedelta(days=3)).isoformat() + ",OK",
        # day -2 missing → gap
        (end - timedelta(days=1)).isoformat() + ",OK",
        end.isoformat() + ",OK",
    ]
    log.write_text("\n".join(lines) + "\n")
    assert _gate_count(log) == 2  # gap resets; only the tail counts


def test_gate_full_week_passes(tmp_path):
    log = tmp_path / "stability_gate.log"
    _write_gate_log(log, ["OK"] * 7)
    assert _gate_count(log) == 7


def test_health_gate_uses_current_streak(tmp_path):
    hermes_home = tmp_path / "hermes"
    (hermes_home / "entropicmem").mkdir(parents=True)
    (hermes_home / "backups").mkdir()
    _write_gate_log(
        hermes_home / "entropicmem" / "stability_gate.log",
        ["OK"] * 7 + ["WARN"] + ["OK"] * 3,
    )

    env = {**os.environ, "HERMES_HOME": str(hermes_home)}
    result = subprocess.run(
        [sys.executable, str(_HEALTH)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    report = json.loads(result.stdout)
    gate = report["checks"]["stability_gate"]
    assert gate["gate_passed"] is False  # 3 current, not 7 historical
    assert gate["current_consecutive_ok"] == 3
    assert gate["longest_consecutive_ok"] == 7
    assert "3/7 current consecutive OK days" in gate["message"]
