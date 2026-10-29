"""Chunk 52 — the release-readiness commands: `doctor` and `memory upgrade`.

The release checklist's two recorded gaps, closed:

* **`doctor`** — the read-only health report the upgrade drills had to fake:
  the store's existence, integrity, schema version and engine; the config's
  load errors; the vault and the index; the embedding state. ASCII
  PASS/WARN/FAIL lines, exit 0 when nothing FAILED, 1 when something did.
  It must never write: not the store, not the vault, not even a temp file.
* **`memory upgrade`** — the friendly v2→v3 cutover wrapper: `--status`
  reports the current shape read-only; the command refuses when already v3,
  when a migration lock exists, when the provider is running, and without
  `--yes`; with `--yes` it runs the real migrator (whose own verified backup,
  guard and parity checks are the safety net the drills proved) and prints
  what moved and where the backup is.

Synthetic data only.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import entropicmem  # noqa: E402
from em.store import db as emdb  # noqa: E402
from em.store.migrations import LATEST, migrate  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "db"


def _copy_v2_fixture(tmp_path: Path) -> Path:
    src = FIXTURES / "v2_7_0.db"
    target = tmp_path / "memory.db"
    target.write_bytes(src.read_bytes())
    return target


def _run_cli(capsys, monkeypatch, argv_env: dict, *argv: str):
    """Run the standalone CLI's main() with the env pointed at a profile."""
    for key, value in argv_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["entropicmem.py", *argv])
    code = entropicmem.main()
    return code


def _vault_for(vault_root: Path) -> None:
    (vault_root / "Knowledge").mkdir(parents=True, exist_ok=True)
    (vault_root / "Knowledge" / "Note.md").write_text(
        '---\ntitle: "Note"\ntags: \n---\n\nA body.\n', encoding="utf-8"
    )


# --- doctor -----------------------------------------------------------------


def test_doctor_passes_on_a_healthy_profile(tmp_path, monkeypatch, capsys):
    store = _copy_v2_fixture(tmp_path)
    _vault_for(tmp_path / "vault")
    code = _run_cli(
        capsys,
        monkeypatch,
        {
            "ENTROPICMEM_MEMORY_DB": str(store),
            "ENTROPICMEM_VAULT_PATH": str(tmp_path / "vault"),
            "ENTROPICMEM_INDEX_DB": str(tmp_path / "index.db"),
        },
        "doctor",
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "FAIL" not in out
    assert "integrity" in out.lower()


def test_doctor_fails_on_a_corrupted_store(tmp_path, monkeypatch, capsys):
    store = _copy_v2_fixture(tmp_path)
    raw = bytearray(store.read_bytes())
    raw[4096:4100] = b"ZZZZ"  # clobber a page
    store.write_bytes(bytes(raw))
    code = _run_cli(
        capsys,
        monkeypatch,
        {
            "ENTROPICMEM_MEMORY_DB": str(store),
            "ENTROPICMEM_VAULT_PATH": str(tmp_path / "vault"),
            "ENTROPICMEM_INDEX_DB": str(tmp_path / "index.db"),
        },
        "doctor",
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL" in out


def test_doctor_names_the_schema_version_and_engine(tmp_path, monkeypatch, capsys):
    store = _copy_v2_fixture(tmp_path)
    _run_cli(
        capsys,
        monkeypatch,
        {
            "ENTROPICMEM_MEMORY_DB": str(store),
            "ENTROPICMEM_VAULT_PATH": str(tmp_path / "vault"),
            "ENTROPICMEM_INDEX_DB": str(tmp_path / "index.db"),
        },
        "doctor",
    )
    out = capsys.readouterr().out
    assert "v2" in out

    conn = emdb.open_db(store)
    try:
        migrate(conn)
    finally:
        conn.close()
    _run_cli(
        capsys,
        monkeypatch,
        {
            "ENTROPICMEM_MEMORY_DB": str(store),
            "ENTROPICMEM_VAULT_PATH": str(tmp_path / "vault"),
            "ENTROPICMEM_INDEX_DB": str(tmp_path / "index.db"),
        },
        "doctor",
    )
    out = capsys.readouterr().out
    assert "v3" in out


def test_doctor_never_writes_the_store(tmp_path, monkeypatch, capsys):
    store = _copy_v2_fixture(tmp_path)
    before = store.read_bytes()
    _run_cli(
        capsys,
        monkeypatch,
        {
            "ENTROPICMEM_MEMORY_DB": str(store),
            "ENTROPICMEM_VAULT_PATH": str(tmp_path / "vault"),
            "ENTROPICMEM_INDEX_DB": str(tmp_path / "index.db"),
        },
        "doctor",
    )
    assert store.read_bytes() == before, "doctor wrote to the store"


# --- memory upgrade ---------------------------------------------------------


def _upgrade_env(tmp_path: Path, store: Path) -> dict:
    return {
        "ENTROPICMEM_MEMORY_DB": str(store),
        "ENTROPICMEM_VAULT_PATH": str(tmp_path / "vault"),
        "ENTROPICMEM_INDEX_DB": str(tmp_path / "index.db"),
    }


def test_upgrade_status_reports_read_only(tmp_path, monkeypatch, capsys):
    store = _copy_v2_fixture(tmp_path)
    code = _run_cli(capsys, monkeypatch, _upgrade_env(tmp_path, store), "memory", "upgrade", "--status")
    assert code == 0
    out = capsys.readouterr().out
    assert "v2" in out and "upgrade" in out.lower()
    assert store.read_bytes() == _copy_v2_fixture(tmp_path).read_bytes()


def test_upgrade_refuses_without_yes(tmp_path, monkeypatch, capsys):
    store = _copy_v2_fixture(tmp_path)
    code = _run_cli(capsys, monkeypatch, _upgrade_env(tmp_path, store), "memory", "upgrade")
    assert code != 0
    out = capsys.readouterr().out
    assert "--yes" in out
    conn = sqlite3.connect(store)
    uv = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert uv == 0, "the refusal must not have migrated"


def test_upgrade_refuses_when_already_v3(tmp_path, monkeypatch, capsys):
    store = _copy_v2_fixture(tmp_path)
    conn = emdb.open_db(store)
    try:
        migrate(conn)
    finally:
        conn.close()
    code = _run_cli(
        capsys, monkeypatch, _upgrade_env(tmp_path, store), "memory", "upgrade", "--yes"
    )
    assert code != 0
    assert "already" in capsys.readouterr().out.lower()


def test_upgrade_refuses_when_a_migration_lock_exists(tmp_path, monkeypatch, capsys):
    from memory_engine import MemoryEngine

    store = _copy_v2_fixture(tmp_path)
    lock = store.parent / MemoryEngine.MIGRATION_LOCK_FILENAME
    lock.write_text("held")
    code = _run_cli(
        capsys, monkeypatch, _upgrade_env(tmp_path, store), "memory", "upgrade", "--yes"
    )
    assert code != 0
    assert "lock" in (capsys.readouterr().err or "").lower()


def test_upgrade_migrates_reports_and_backs_up(tmp_path, monkeypatch, capsys):
    store = _copy_v2_fixture(tmp_path)
    facts_before = sqlite3.connect(store).execute(
        "SELECT COUNT(*) FROM facts"
    ).fetchone()[0]

    code = _run_cli(
        capsys, monkeypatch, _upgrade_env(tmp_path, store), "memory", "upgrade", "--yes"
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "backup" in out.lower()

    conn = sqlite3.connect(store)
    uv = conn.execute("PRAGMA user_version").fetchone()[0]
    memories = conn.execute("SELECT COUNT(*) FROM memories WHERE legacy_id IS NOT NULL").fetchone()[0]
    conn.close()
    assert uv == LATEST
    assert memories == facts_before

    backups = list((store.parent / "backups").glob("*/**")) if (store.parent / "backups").is_dir() else []
    assert backups, "no pre-upgrade backup recorded"


def test_upgrade_runs_without_the_env_var_set(tmp_path, monkeypatch, capsys):
    """The command is the opt-in: it must not require the env var."""
    store = _copy_v2_fixture(tmp_path)
    monkeypatch.delenv("ENTROPICMEM_ALLOW_LIVE_MIGRATION", raising=False)
    code = _run_cli(capsys, monkeypatch, _upgrade_env(tmp_path, store), "memory", "upgrade", "--yes")
    assert code == 0
    conn = sqlite3.connect(store)
    uv = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert uv == LATEST


def test_upgrade_restores_the_callers_env_afterwards(tmp_path, monkeypatch, capsys):
    """The opt-in is scoped to the command: a leaked flag would disable the
    guard's protection for every real store this process touches afterwards."""
    import os

    store = _copy_v2_fixture(tmp_path)
    monkeypatch.delenv("ENTROPICMEM_ALLOW_LIVE_MIGRATION", raising=False)
    _run_cli(capsys, monkeypatch, _upgrade_env(tmp_path, store), "memory", "upgrade", "--yes")
    assert os.environ.get("ENTROPICMEM_ALLOW_LIVE_MIGRATION") != "1"


# --- chunk 60: the duplicate-plugin-tree check ------------------------------


def _write_tree(root: Path, version: str) -> None:
    tree = root / "plugins" / f"entropicmem-{version}"
    tree.mkdir(parents=True, exist_ok=True)
    (tree / "plugin.yaml").write_text(f"name: entropicmem\nversion: {version}\n", encoding="utf-8")


def test_doctor_warns_on_duplicate_plugin_trees(tmp_path, monkeypatch, capsys):
    import em_internal.vault as vault_module

    home = tmp_path / "home"
    _write_tree(home, "3.0.0")
    _write_tree(home, "3.0.0.dev0")
    monkeypatch.setattr(vault_module, "hermes_home_path", lambda: home)
    code = _run_cli(
        capsys, monkeypatch, _upgrade_env(tmp_path, tmp_path / "memory.db"), "doctor"
    )
    assert code == 0  # a duplicate tree is a WARN, not a FAIL
    out = capsys.readouterr().out
    assert "2 entropicmem trees" in out
    assert "3.0.0" in out and "3.0.0.dev0" in out


def test_doctor_passes_a_single_tree(tmp_path, monkeypatch, capsys):
    import em_internal.vault as vault_module

    home = tmp_path / "home"
    _write_tree(home, "3.0.0")
    monkeypatch.setattr(vault_module, "hermes_home_path", lambda: home)
    _run_cli(
        capsys, monkeypatch, _upgrade_env(tmp_path, tmp_path / "memory.db"), "doctor"
    )
    out = capsys.readouterr().out
    assert "FAIL" not in out
    assert "plugin trees" in out
