"""Multi-profile isolation tests (v2.2.x).

Verifies that two distinct HERMES_HOME roots (e.g. the default profile and a
secondary personal profile) produce fully separate EntropicMem stores:
separate memory.db, separate index.db, separate vaults, and no cross-profile
recall. This is the regression guard for the multi-profile support built in
v2.2.1 (HERMES_HOME-aware path resolution).
"""
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "plugins" / "entropicmem" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import vault  # noqa: E402
from memory_engine import MemoryEngine  # noqa: E402


@pytest.fixture()
def two_homes(tmp_path):
    """Two isolated HERMES_HOME roots, each with its own entropicmem dir."""
    home_a = tmp_path / "home_a"
    home_b = tmp_path / "home_b"
    for h in (home_a, home_b):
        (h / "entropicmem" / "vault").mkdir(parents=True)
    return home_a, home_b


def test_resolve_vault_path_profile_aware(two_homes, monkeypatch):
    """HERMES_HOME set => vault resolves under that profile. The legacy shared
    Obsidian fallback and OBSIDIAN_VAULT_PATH are gone (Phase 2 path
    unification): CLI and plugin must resolve the SAME vault."""
    home_a, home_b = two_homes
    # Clear any ambient ENTROPICMEM_* / OBSIDIAN_* that could shadow the test.
    monkeypatch.delenv("ENTROPICMEM_VAULT_PATH", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

    monkeypatch.setenv("HERMES_HOME", str(home_a))
    assert vault.resolve_vault_path() == (home_a / "entropicmem" / "vault").resolve()

    monkeypatch.setenv("HERMES_HOME", str(home_b))
    assert vault.resolve_vault_path() == (home_b / "entropicmem" / "vault").resolve()

    # No HERMES_HOME: always ~/.hermes/entropicmem/vault. The legacy
    # ~/Documents/Obsidian Vault fallback is DROPPED even when that vault
    # exists with AGENTS.md, and OBSIDIAN_VAULT_PATH is not honored (live ops
    # scripts read it from os.environ themselves). Isolated via a fake home so
    # the test is deterministic regardless of the real machine's layout.
    monkeypatch.delenv("HERMES_HOME", raising=False)
    fake_home = Path(tempfile.mkdtemp())
    monkeypatch.setattr(vault.Path, "home", staticmethod(lambda: Path(fake_home)))

    obsidian_vault = fake_home / "Documents" / "Obsidian Vault"
    (obsidian_vault).mkdir(parents=True)
    (obsidian_vault / "AGENTS.md").write_text("# vault", encoding="utf-8")
    expected = (fake_home / ".hermes" / "entropicmem" / "vault").resolve()
    assert vault.resolve_vault_path() == expected

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(obsidian_vault))
    assert vault.resolve_vault_path() == expected


def test_stores_are_isolated_per_home(two_homes, monkeypatch):
    """Facts written to home A are invisible to home B and vice versa."""
    home_a, home_b = two_homes
    db_a = home_a / "entropicmem" / "memory.db"
    db_b = home_b / "entropicmem" / "memory.db"

    with MemoryEngine(db_a) as eng:
        eng.remember("PROFILE_A_ONLY: secret of profile A", domain="Test")
    with MemoryEngine(db_b) as eng:
        eng.remember("PROFILE_B_ONLY: secret of profile B", domain="Test")

    # A sees A only.
    with MemoryEngine(db_a) as eng:
        a_results = eng.recall("PROFILE_A_ONLY")
        b_in_a = eng.recall("PROFILE_B_ONLY")
    assert any("PROFILE_A_ONLY" in r.content for r in a_results)
    assert all("PROFILE_B_ONLY" not in r.content for r in b_in_a)

    # B sees B only.
    with MemoryEngine(db_b) as eng:
        b_results = eng.recall("PROFILE_B_ONLY")
        a_in_b = eng.recall("PROFILE_A_ONLY")
    assert any("PROFILE_B_ONLY" in r.content for r in b_results)
    assert all("PROFILE_A_ONLY" not in r.content for r in a_in_b)


def test_cli_defaults_follow_hermes_home(two_homes, monkeypatch):
    """The CLI's default paths (no ENTROPICMEM_* env) must follow HERMES_HOME."""
    home_a, _ = two_homes
    monkeypatch.delenv("ENTROPICMEM_MEMORY_DB", raising=False)
    monkeypatch.delenv("ENTROPICMEM_INDEX_DB", raising=False)
    monkeypatch.delenv("ENTROPICMEM_VAULT_PATH", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(home_a))

    # Imported fresh so module-level defaults are recomputed under the test env.
    import importlib

    import entropicmem as cli

    importlib.reload(cli)
    assert cli._memory_db_path() == (home_a / "entropicmem" / "memory.db").resolve()
    assert cli._resolve_env()[0] == (home_a / "entropicmem" / "vault").resolve()
    assert cli._resolve_env()[1] == (home_a / "entropicmem" / "index.db").resolve()
