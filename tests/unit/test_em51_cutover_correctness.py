"""Chunk 51 — the cutover-correctness round, from Hermes's audit.

Four fixes, each pinned where it broke:

* **`migrate()`'s path guard runs only when a migration would run.** The guard
  ran before the pending check, so an already-migrated store at the live path
  refused to open unless `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1` was permanently
  in the process env — the cutover opt-in had become a runtime requirement.
  The tests fake the guard (raising unconditionally) and assert it is never
  *reached* when nothing is pending, and an **empty store** (no data tables)
  skips it even with pending migrations — creating a fresh store destroys
  nothing, which is the guard's whole purpose. A store with data and pending
  migrations still refuses.
* **`import_capsule` refuses a store newer than the build** and **backs the
  existing target up before replacing it** — the capsule's sha256s prove
  integrity, not compatibility, and the old target used to vanish
  unrecoverably.
* **The profile-patch gate reads the typed `core.writable_by_agent`** — the
  legacy flat spelling folds through `LEGACY_KEY_MAP` and the typed value is
  synced into the flat dict at the load site, so the gate reads one source of
  truth (the typed key was inert before).

Synthetic data only.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import entropicmem  # noqa: E402
from em.store import db as emdb  # noqa: E402
from em.store.migrations import LATEST, migrate  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "db"


@pytest.fixture
def paranoid_guard(monkeypatch):
    """Make the path guard refuse EVERYTHING, and count its invocations."""
    from em.store import migrations as emmig

    calls = {"n": 0}

    def _refuse(path):
        calls["n"] += 1
        raise emmig.MigrationRefused(f"refusing {path} (test guard)")

    monkeypatch.setattr(emmig, "assert_safe_db_path", _refuse)
    return calls


def _copy_v2_fixture(tmp_path: Path) -> Path:
    src = FIXTURES / "v2_7_0.db"
    target = tmp_path / "memory.db"
    target.write_bytes(src.read_bytes())
    return target


# --- the guard reorder ------------------------------------------------------


def test_the_guard_never_runs_when_nothing_is_pending(tmp_path, paranoid_guard):
    """A migrated store opens again: no pending work, no guard, no env var."""
    path = tmp_path / "memory.db"
    conn = emdb.open_db(path)
    try:
        # Phase 1: a fresh store is created with the guard refusing everything
        # — an empty store has nothing to destroy, so the carve-out applies.
        migrate(conn)
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == LATEST
    finally:
        conn.close()

    # Phase 2: the migrated store re-opens with zero pending migrations —
    # the guard must not be reached at all (this is what made a migrated
    # live store unopenable without the env permanently set).
    conn = emdb.open_db(path)
    try:
        assert migrate(conn) == []
        assert paranoid_guard["n"] == 0, (
            "the path guard ran even though no migration was pending"
        )
    finally:
        conn.close()


def test_the_guard_still_blocks_a_data_store_with_pending_migrations(
    tmp_path, paranoid_guard
):
    """The development-safety rule is intact: data + pending work refuses."""
    path = _copy_v2_fixture(tmp_path)
    conn = emdb.open_db(path)
    try:
        with pytest.raises(Exception) as excinfo:
            migrate(conn)
        assert "refusing" in str(excinfo.value)
        assert paranoid_guard["n"] == 1
    finally:
        conn.close()


def test_a_migrated_store_reopens_through_the_engine_without_the_env(tmp_path):
    """Hermes's drill: V3Engine over an already-migrated store, no env set."""
    from em.facade.engine import V3Engine

    path = tmp_path / "memory.db"
    conn = emdb.open_db(path)
    try:
        migrate(conn)
    finally:
        conn.close()

    # The real env must not carry the opt-in for this to mean anything.
    import os

    assert os.environ.get("ENTROPICMEM_ALLOW_LIVE_MIGRATION") != "1"
    engine = V3Engine(path, profile_id="default", scope_user="", scope_chat="", is_owner=True)
    try:
        new_id = engine.remember(
            "The fern prefers morning light.",
            actor="tester",
        )
        assert isinstance(new_id, str) and new_id, new_id
    finally:
        engine.close()


# --- the capsule import guards ---------------------------------------------


def _capsule(tmp_path: Path, *, user_version: int) -> Path:
    """A minimal valid-signature capsule whose store reports *user_version*."""
    staging = tmp_path / f"cap-{user_version}"
    staging.mkdir(parents=True, exist_ok=True)
    db = staging / "memory.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE facts (id TEXT PRIMARY KEY, content TEXT)")
    conn.execute("INSERT INTO facts VALUES ('syn_x1', 'capsule fact')")
    conn.execute(f"PRAGMA user_version = {int(user_version)}")
    conn.commit()
    conn.close()

    import hashlib

    files = {"memory.db": {"sha256": hashlib.sha256(db.read_bytes()).hexdigest()}}
    manifest = {
        "version": 2,
        "files": files,
        "schema_versions": {"memory": {"user_version": user_version}},
    }
    capsule = tmp_path / f"capsule-{user_version}.tar.gz"
    with tarfile.open(capsule, "w:gz") as tar:
        tar.add(db, arcname="memory.db")
        info = tarfile.TarInfo(name="manifest.json")
        payload = json.dumps(manifest).encode()
        info.size = len(payload)
        tar.addfile(info, __import__("io").BytesIO(payload))
    return capsule


def test_import_refuses_a_store_newer_than_the_build(tmp_path, monkeypatch):
    """A capsule the build cannot serve is refused, target untouched."""
    capsule = _capsule(tmp_path, user_version=LATEST + 10)
    target = tmp_path / "profile"
    target.mkdir()
    monkeypatch.setenv("ENTROPICMEM_MEMORY_DB", str(target / "memory.db"))
    monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", str(target / "vault"))
    monkeypatch.setenv("ENTROPICMEM_INDEX_DB", str(target / "index.db"))

    with pytest.raises(ValueError) as excinfo:
        entropicmem.import_capsule(capsule, trust_unverified=True)
    assert "newer" in str(excinfo.value)
    assert not (target / "memory.db").exists(), "the refused import still replaced the target"


def test_import_backs_the_target_up_before_replacing(tmp_path, monkeypatch):
    """The replaced store survives as a verified pre-import backup."""
    capsule = _capsule(tmp_path, user_version=0)
    target = tmp_path / "profile"
    target.mkdir()
    old = target / "memory.db"
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE facts (id TEXT PRIMARY KEY, content TEXT)")
    conn.execute("INSERT INTO facts VALUES ('syn_old', 'the row that must survive')")
    conn.commit()
    conn.close()

    monkeypatch.setenv("ENTROPICMEM_MEMORY_DB", str(old))
    monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", str(target / "vault"))
    monkeypatch.setenv("ENTROPICMEM_INDEX_DB", str(target / "index.db"))
    entropicmem.import_capsule(capsule, trust_unverified=True)

    backups = list((target / "backups").glob("pre-import*/*.db")) if (
        target / "backups"
    ).is_dir() else []
    assert backups, "the replaced store was not backed up"
    check = sqlite3.connect(backups[0])
    try:
        row = check.execute("SELECT content FROM facts WHERE id='syn_old'").fetchone()
    finally:
        check.close()
    assert row is not None, "the pre-import backup does not hold the old row"


# --- the typed config gate --------------------------------------------------


def _provider(tmp_path: Path, **config):
    from plugins.entropicmem import EntropicMemMemoryProvider

    provider = EntropicMemMemoryProvider(
        config={"core_memory_enabled": True, **config}
    )
    provider.initialize("em51-session", hermes_home=str(tmp_path), agent_identity="default")
    provider._scripts_dir = SCRIPTS
    return provider


def _patch(provider):
    out = provider.handle_tool_call(
        "entropicmem_profile",
        {"action": "patch", "target": "persona", "old_text": "", "new_text": ""},
    )
    return json.loads(out)


def test_the_profile_patch_gate_reads_the_typed_key(tmp_path):
    provider = _provider(tmp_path, **{"core.writable_by_agent": True})
    out = _patch(provider)
    assert out.get("reason_code") != "writes_disabled", out


def test_the_legacy_flat_key_still_folds_into_the_typed_gate(tmp_path):
    provider = _provider(tmp_path, core_memory_writable=True)
    out = _patch(provider)
    assert out.get("reason_code") != "writes_disabled", out


def test_the_gate_stays_shut_when_neither_key_is_set(tmp_path):
    provider = _provider(tmp_path)
    out = _patch(provider)
    assert out.get("reason_code") == "writes_disabled", out
