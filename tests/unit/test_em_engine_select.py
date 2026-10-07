"""EM-211 Chunk 9: the provider selects its engine by the store's schema version.

The provider used to construct v2's ``MemoryEngine`` unconditionally. It now
picks: a v2 store gets ``MemoryEngine``, a v3 store gets the facade. Selection is
by ``PRAGMA user_version``, read **read-only, before any engine is constructed** —
because ``V3Engine.__init__`` calls ``migrate()``, so constructing it over a v2
store would perform the v2-to-v3 cutover as a side effect of merely opening it.

That ordering is what the most important test here protects: **opening a v2 store
must leave it byte-for-byte unmigrated.** The cutover is the owner's act, not a
consequence of the provider starting up.

Rules: invented data only. The v2 fixture is always copied, never mutated in place.
"""

from __future__ import annotations

import ast
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
FIXTURES = REPO / "tests" / "fixtures" / "db"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.facade.engine import V3Engine  # noqa: E402
from em.facade.select import StoreVersionError, open_engine, store_kind  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.migrations import LATEST, migrate  # noqa: E402


def v2_store(tmp_path: Path) -> Path:
    """A copy of the committed v2.7.0 fixture — the real thing, not a mock."""
    dest = tmp_path / "v2" / "memory.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "v2_7_0.db", dest)
    return dest


def v3_store(tmp_path: Path) -> Path:
    path = tmp_path / "v3" / "memory.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(path))
    try:
        with store.writer() as conn:
            migrate(conn)
    finally:
        store.close()
    return path


def snapshot(path: Path) -> dict:
    """What must not change when a v2 store is merely opened."""
    conn = sqlite3.connect(path)
    try:
        return {
            "user_version": conn.execute("PRAGMA user_version").fetchone()[0],
            "tables": {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")},
        }
    finally:
        conn.close()


# --- the detector -------------------------------------------------------------


def test_a_missing_file_is_a_new_v2_store(tmp_path):
    """Nothing there yet: the v2 engine creates it, exactly as it does today."""
    assert store_kind(tmp_path / "does-not-exist.db") == "v2"


def test_the_v2_fixture_is_a_v2_store(tmp_path):
    assert store_kind(v2_store(tmp_path)) == "v2"


def test_a_migrated_store_is_a_v3_store(tmp_path):
    assert store_kind(v3_store(tmp_path)) == "v3"


def test_a_store_newer_than_this_build_is_refused(tmp_path):
    path = v3_store(tmp_path)
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA user_version = {LATEST + 1}")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(StoreVersionError):
        store_kind(path)


def test_a_versioned_store_without_the_v3_tables_is_refused(tmp_path):
    """A version bump from somewhere else is not a v3 store we can serve.

    Refusing beats handing it to ``migrate()``, which would run our migrations
    against a database that is not ours.
    """
    path = tmp_path / "foreign.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE something_else (x)")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(StoreVersionError):
        store_kind(path)


# --- the selector -------------------------------------------------------------


def test_open_engine_gives_the_v2_engine_for_a_v2_store(tmp_path):
    from memory_engine import MemoryEngine

    engine = open_engine(v2_store(tmp_path), profile_id="default")
    try:
        assert isinstance(engine, MemoryEngine)
    finally:
        engine.close()


def test_open_engine_gives_the_facade_for_a_v3_store(tmp_path):
    engine = open_engine(v3_store(tmp_path), profile_id="default")
    try:
        assert isinstance(engine, V3Engine)
    finally:
        engine.close()


def test_opening_a_v2_store_does_not_migrate_it(tmp_path):
    """The whole reason selection happens before construction."""
    path = v2_store(tmp_path)
    before = snapshot(path)

    engine = open_engine(path, profile_id="default")
    engine.close()

    after = snapshot(path)
    assert after["user_version"] == before["user_version"] == 0, (
        "a v2 store must not be migrated by merely opening it"
    )
    assert "memories" not in after["tables"], "no v3 tables may appear"
    assert "schema_migrations" not in after["tables"], "our bookkeeping must not appear"
    assert after["tables"] == before["tables"], "the schema must be untouched"
    assert not (path.parent / "migrate-backups").exists(), "no migration backup may be taken"


def test_a_v3_store_is_served_without_a_further_migration(tmp_path):
    """`migrate()` inside the facade is a no-op once the store is current."""
    path = v3_store(tmp_path)
    before = snapshot(path)
    engine = open_engine(path, profile_id="default")
    engine.close()
    assert snapshot(path) == before


def test_the_selector_routes_pii_locales_to_both_engines(tmp_path):
    """A v3 store must keep the locale-aware redaction a v2 store had.

    v2 took the packs on the engine; the facade now carries them into every
    write's draft, or a store configured for e.g. the `za` pack would silently
    lose that detection on v3.
    """
    v2 = open_engine(v2_store(tmp_path), profile_id="default", pii_locales=["za"])
    try:
        assert v2.pii_locales == ["za"]
    finally:
        v2.close()

    v3 = open_engine(v3_store(tmp_path), profile_id="default", pii_locales=["za"])
    try:
        assert isinstance(v3, V3Engine)
        assert v3.pii_locales == ("za",)
    finally:
        v3.close()


def test_a_sensitive_v3_write_redacts_with_the_engines_locales(tmp_path, monkeypatch):
    """The plumbing end to end: facade -> draft -> `redact_pii(locales=...)`."""
    import pii

    seen = {}
    real = pii.redact_pii

    def spy(text, **kwargs):
        seen["locales"] = kwargs.get("locales")
        return real(text, **kwargs)

    monkeypatch.setattr(pii, "redact_pii", spy)
    engine = open_engine(v3_store(tmp_path), profile_id="default", pii_locales=["za"])
    try:
        engine.remember(content="Bob Example called from a number we redact.",
                         sensitivity="sensitive")
    finally:
        engine.close()
    assert seen.get("locales") == ("za",), (
        "the configured locale packs must reach redaction, not just the engine"
    )


def test_an_ordinary_v3_write_is_not_redacted(tmp_path, monkeypatch):
    """The tier gate is deliberate and stays: public/internal rows are untouched."""
    import pii

    called = []
    monkeypatch.setattr(pii, "redact_pii", lambda *a, **k: called.append(1) or "x")
    engine = open_engine(v3_store(tmp_path), profile_id="default", pii_locales=["za"])
    try:
        engine.remember(content="Acme deploys on Tuesdays.", sensitivity="internal")
    finally:
        engine.close()
    assert called == [], "internal content is not redacted — v3's documented policy"


# --- the provider -------------------------------------------------------------


def make_provider(db: Path, *, gateway_user: str | None = None, owners: list | None = None):
    from plugins.entropicmem import EntropicMemMemoryProvider, _backend

    _backend.ensure_scripts_on_path(SCRIPTS)
    provider = EntropicMemMemoryProvider(
        config={"owner_user_ids": owners or [], "vault_path": str(db.parent / "vault")}
    )
    provider._scripts_dir = SCRIPTS
    provider._memory_db = db
    provider._profile_id = "default"
    provider._hermes_home = db.parent
    provider._gateway_user_id = gateway_user
    return provider


def test_the_provider_opens_the_v2_engine_for_a_v2_store(tmp_path):
    from memory_engine import MemoryEngine

    engine = make_provider(v2_store(tmp_path))._open_engine()
    try:
        assert isinstance(engine, MemoryEngine)
    finally:
        engine.close()


def test_the_provider_opens_the_facade_for_a_v3_store(tmp_path):
    engine = make_provider(v3_store(tmp_path))._open_engine()
    try:
        assert isinstance(engine, V3Engine)
    finally:
        engine.close()


def test_the_provider_does_not_migrate_a_v2_store_on_startup(tmp_path):
    path = v2_store(tmp_path)
    before = snapshot(path)
    engine = make_provider(path)._open_engine()
    engine.close()
    assert snapshot(path) == before, "opening the provider must not cut a store over"


def test_the_provider_passes_the_gateway_identity(tmp_path):
    """The half of the §3.5 rule Chunk 7.2 left for here."""
    engine = make_provider(v3_store(tmp_path), gateway_user="bob", owners=["alice"])._open_engine()
    try:
        assert engine.scope.user == "bob"
        assert engine.scope.is_owner is False, "bob is not in owner_user_ids"
    finally:
        engine.close()


def test_the_default_config_is_the_owner_context(tmp_path):
    """An empty owner list means nobody is a guest — v2's single-pool behaviour."""
    engine = make_provider(v3_store(tmp_path), gateway_user="bob", owners=[])._open_engine()
    try:
        assert engine.scope.is_owner is True
    finally:
        engine.close()

    owner = make_provider(v3_store(tmp_path), gateway_user="alice", owners=["alice"])._open_engine()
    try:
        assert owner.scope.is_owner is True
    finally:
        owner.close()


def test_the_provider_builds_engines_only_through_the_helper():
    """Drift guard: a tenth raw construction would decide the engine by accident.

    Nine inline ``MemoryEngine(...)`` sites were routed through ``_open_engine``
    in Chunk 9. The provider must not construct an engine itself again, or that
    site would bypass the version check and could migrate a v2 store.
    """
    provider = REPO / "plugins" / "entropicmem" / "__init__.py"
    tree = ast.parse(provider.read_text(encoding="utf-8"))
    raw = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "MemoryEngine"
    ]
    assert not raw, (
        f"MemoryEngine(...) constructed directly at lines {raw}; route it through "
        "_open_engine() so the store version decides the engine"
    )
    assert "_open_engine" in provider.read_text(encoding="utf-8"), (
        "the provider must name its engine factory"
    )


# --- the CLI's guard ----------------------------------------------------------


def test_the_cli_serves_a_v3_store_through_the_facade(tmp_path):
    """Chunk 10.4: the CLI routes by store version, exactly as the provider does.

    Until 10.4 this refused; the refusal was correct only while the facade could
    not serve the CLI's calls. It can now (10.1/10.2), and the v2-only commands
    refuse before they get here (10.3).
    """
    import entropicmem

    engine = entropicmem._engine(v3_store(tmp_path))
    try:
        assert isinstance(engine, V3Engine)
    finally:
        engine.close()


def test_the_cli_does_not_override_a_home_derived_profile(tmp_path, monkeypatch):
    """The trap 10.4 had to avoid, and a bug Chunk 9 left on the provider path.

    ``MemoryEngine.profile_id()`` resolves ``explicit > hermes_home basename >
    'default'``. Passing ``profile_id="default"`` would make it *explicit* and
    silently restamp every write in a non-default home. Selection must pass the
    profile through untouched — ``None`` means "let the engine decide".
    """
    import entropicmem

    home = tmp_path / "alice-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("ENTROPICMEM_MEMORY_DB", raising=False)
    engine = entropicmem._engine()
    try:
        assert engine.profile_id() == "alice-home", (
            "the CLI must let MemoryEngine resolve the slug from hermes_home"
        )
    finally:
        engine.close()


def test_the_provider_does_not_override_a_home_derived_profile(tmp_path):
    """The same trap on the provider path (Chunk 9, fixed in Chunk 10.4)."""
    from plugins.entropicmem import EntropicMemMemoryProvider

    home = tmp_path / "bob-home"
    home.mkdir()
    provider = EntropicMemMemoryProvider(config={})
    provider._scripts_dir = SCRIPTS
    provider._memory_db = home / "entropicmem" / "memory.db"
    provider._hermes_home = home
    provider._profile_id = None  # no explicit identity: the home decides

    engine = provider._open_engine()
    try:
        assert engine.profile_id() == "bob-home"
    finally:
        engine.close()


def test_the_cli_still_opens_a_v2_store(tmp_path):
    """The guard must not break the path every user is on today."""
    import entropicmem
    from memory_engine import MemoryEngine

    engine = entropicmem._engine(v2_store(tmp_path))
    try:
        assert isinstance(engine, MemoryEngine)
    finally:
        engine.close()


def test_the_cli_still_opens_a_store_that_does_not_exist_yet(tmp_path):
    import entropicmem
    from memory_engine import MemoryEngine

    engine = entropicmem._engine(tmp_path / "fresh" / "memory.db")
    try:
        assert isinstance(engine, MemoryEngine)
    finally:
        engine.close()
