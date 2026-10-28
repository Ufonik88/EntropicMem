"""EM-901 — the upgrade drills: the committed v2.x fixtures, driven to 3.0.

The card's AC is a drill report in ``docs/UPGRADING.md``; these tests are the
drills that report is built from, and they stay in the suite so the upgrade
path can never rot silently. Every drill drives a **copy** of a committed
fixture — the committed bytes are hash-pinned first, so a drill bug (or anyone
else's) can never silently rewrite the evidence.

Generations: v2.3.0 / v2.5.0 / v2.7.0 are the committed fixtures (built by the
real historical engines — ``tests/fixtures/db/generate_fixtures.py``); the
**2.8.1 generation is derived, not guessed**: a real 2.8.1 store is a 2.7
store that the 2.8 engine opened once, so the drill opens ``v2_7_0.db`` with
the current v2 engine (its guarded ``ALTER`` ladder is idempotent) and seeds a
row through its real ``remember``.

What the drills pin:

* **Migrate** — five migrations apply, ``user_version`` reaches ``LATEST``,
  ``integrity_check`` stays ``ok``.
* **Nothing lost** — every pre-migration fact resolves by ``legacy_id`` with
  its content byte-equal; deleted rows land ``deleted``; pending rows land
  ``pending``; episode and snapshot counts survive.
* **The store serves** — ``MemoryStore.get`` resolves each v2 fact id through
  the v3 read path's own legacy-id form.
* **The vault** — an old-style vault (v2.8's writer: quoted-unescaped titles,
  a ``---`` horizontal rule in a body) with a legacy index (old note ids,
  ``user_version`` 0) migrates to the current index generation and serves
  full-text search and a graph export.
* **Sync** — a capsule exported from the 2.8.1 generation imports into a fresh
  3.0-line profile and migrates cleanly there; the reverse direction is pinned
  as the documented limitation (0002 renamed the v2 tables, so a 2.8 engine
  sees none of the migrated rows — sync to an old profile requires both
  upgraded).

Synthetic data only (``syn_*`` ids, placeholder content).
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import entropicmem  # noqa: E402
from em.store import db as emdb  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import LATEST, discover, migrate  # noqa: E402
from em.store.types import Scope  # noqa: E402
from em_internal.index import SCHEMA_VERSION, VaultIndex  # noqa: E402
from em_internal.vault import Vault  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "db"

#: sha256 of every committed fixture, pinned so a drill bug (or anyone else's)
#: can never silently rewrite the evidence. Regenerate deliberately with
#: python tests/fixtures/db/generate_fixtures.py — v2.5 and v2.7 share bytes
#: because the two releases share an identical schema and seed set.
PINNED_FIXTURE_HASHES = {
    "v2_3_0.db": "4c62f0899c7cd2a7e6050cd90ec278618d0f9075a3cb108dc9654324b1dfb271",
    "v2_5_0.db": "d1cef111a4e738f0f5a2599eaca222fd2d2fdb57d3ce92a98d5f2f8fd662169a",
    "v2_7_0.db": "d1cef111a4e738f0f5a2599eaca222fd2d2fdb57d3ce92a98d5f2f8fd662169a",
}


# --- helpers ---------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    src = FIXTURES / name
    assert src.is_file(), f"missing committed fixture {src}"
    target = tmp_path / name
    shutil.copyfile(src, target)
    return target


def _capture_v2(conn: sqlite3.Connection) -> dict:
    """The pre-migration state the drills compare against."""
    facts = [
        (r["id"], r["content"], int(r["deleted"] or 0))
        for r in conn.execute("SELECT id, content, deleted FROM facts ORDER BY id")
    ]
    pending = [
        (r["id"], r["content"])
        for r in conn.execute("SELECT id, content FROM pending_facts")
    ] if _has_table(conn, "pending_facts") else []
    return {
        "facts": facts,
        "pending": pending,
        "episodes": int(conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]),
        "fact_versions": int(
            conn.execute("SELECT COUNT(*) FROM fact_versions").fetchone()[0]
        ) if _has_table(conn, "fact_versions") else 0,
    }


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _baseline_shape(conn: sqlite3.Connection) -> None:
    """Apply 0001 alone, so any v2.x generation is comparable at the v2.7 shape.

    This is the real migration order — 0001 always runs before 0002 — and it
    is what makes the v2.3 generation capturable at all (its ``facts`` table
    has no ``deleted`` column until the baseline's guarded ALTERs add it).
    """
    baseline = [m for m in discover() if m.version == 1]
    migrate(conn, registry=baseline)


def _drill_migration(conn: sqlite3.Connection, before: dict) -> None:
    """The migration drill's asserts, shared by every generation."""
    applied = migrate(conn)
    assert [m.version for m in applied] == list(range(2, LATEST + 1)), (
        "every pending migration must run (0001 was applied for the capture)"
    )
    assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == LATEST
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    moved = dict(
        conn.execute(
            "SELECT legacy_id, content FROM memories WHERE legacy_id IS NOT NULL"
        )
    )
    store = MemoryStore(conn)
    for fact_id, content, deleted in before["facts"]:
        assert fact_id in moved, f"v2 fact {fact_id} did not migrate"
        status = conn.execute(
            "SELECT status FROM memories WHERE legacy_id=?", (fact_id,)
        ).fetchone()[0]
        if deleted == 1:
            assert status == "deleted", f"deleted fact {fact_id} arrived {status}"
            continue
        assert moved[fact_id] == content, f"content drifted for {fact_id}"
        # The v3 read path's own legacy-id form resolves it, not just SQL.
        row = store.get(fact_id, scope=Scope(profile="default"))
        assert row is not None, f"legacy id {fact_id} unresolved through MemoryStore.get"
        assert row["content"] == content

    if before["pending"]:
        landed_pending = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE legacy_id IN ({})"
            " AND status = 'pending'".format(",".join("?" * len(before["pending"]))),
            tuple(pid for pid, _ in before["pending"]),
        ).fetchone()[0]
        assert landed_pending == len(before["pending"])

    assert int(
        conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    ) >= before["episodes"], "episodes lost"
    assert int(
        conn.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0]
    ) >= before["fact_versions"], "version snapshots lost"


def _first_seed_word(before: dict) -> str:
    """A content word from a live fixture fact, for the served-path check."""
    for _fid, content, deleted in before["facts"]:
        if deleted:
            continue
        for word in content.split():
            if len(word) >= 5:
                return word
    return "synthetic"


# --- the drills ------------------------------------------------------------


@pytest.mark.parametrize("name", ["v2_3_0.db", "v2_5_0.db", "v2_7_0.db"])
def test_drill_generation_migrates_and_serves(tmp_path, name):
    path = _copy_fixture(name, tmp_path)
    conn = emdb.open_db(path)
    try:
        _baseline_shape(conn)
        before = _capture_v2(conn)
        assert before["facts"], f"{name} carries no facts to drill"
        _drill_migration(conn, before)

        # The served path: the migrated rows are findable by content.
        term = _first_seed_word(before)
        rows = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE content LIKE ? AND status != 'deleted'",
            (f"%{term}%",),
        ).fetchone()[0]
        assert rows, f"no migrated row matches {term!r} (the served path would be empty)"
    finally:
        conn.close()


def test_the_committed_fixtures_are_untouched_by_the_drills(tmp_path):
    """The drills copy; the committed bytes are evidence and stay evidence."""
    for name, pinned in PINNED_FIXTURE_HASHES.items():
        assert _sha256(FIXTURES / name) == pinned, (
            f"{name} no longer matches its pinned hash — fixtures are "
            "regenerated deliberately (generate_fixtures.py), never in place"
        )
        before = _sha256(FIXTURES / name)
        work = _copy_fixture(name, tmp_path)
        conn = emdb.open_db(work)
        try:
            migrate(conn)
        finally:
            conn.close()
        assert _sha256(FIXTURES / name) == before, f"{name} was mutated by a drill"


def test_drill_the_281_generation(tmp_path):
    """A 2.8.1 store is a 2.7 store the 2.8 engine opened once — derive it so."""
    from memory_engine import MemoryEngine

    work = _copy_fixture("v2_7_0.db", tmp_path)
    with MemoryEngine(
        work, profile_id="default", hermes_home=tmp_path / "hermes"
    ) as engine:
        fact_id = engine.remember(
            "The fern prefers morning light.", domain="Testing"
        )
        assert fact_id

    conn = emdb.open_db(work)
    try:
        # The 2.8 engine's own ladder upgraded the shape in place.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
        for required in ("version", "deleted", "profile_id", "fact_timestamp"):
            assert required in cols, f"the 2.8 upgrade did not add facts.{required}"
        _baseline_shape(conn)
        before = _capture_v2(conn)
        assert any("fern" in content for _fid, content, _d in before["facts"])
        _drill_migration(conn, before)
    finally:
        conn.close()


def _write_old_style_note(path: Path, title: str, body: str) -> None:
    """The v2.8 writer's exact bytes: quoted title, no escaping."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'---\ntitle: "{title}"\ntags: \n---\n\n{body}\n', encoding="utf-8")


def _downgrade_index_to_legacy_ids(index: VaultIndex) -> None:
    """Rewind a rebuilt index to the pre-EM-602 id space (EM-602's pattern)."""
    mapping = {
        row["note_id"]: row["path"].rsplit(".", 1)[0].split("/")[-1]
        for row in index.db.execute("SELECT note_id, path FROM notes_meta")
    }
    for old, new in mapping.items():
        index.db.execute("UPDATE notes_meta SET note_id = ? WHERE note_id = ?", (new, old))
        index.db.execute("UPDATE notes_fts SET note_id = ? WHERE note_id = ?", (new, old))
    index.db.execute("PRAGMA user_version = 0")
    index.db.commit()


def test_an_old_style_note_reads_with_real_lists_and_a_title(tmp_path):
    """The old-writer bytes parse to the fields Note declares.

    A real 2.8 vault writes ``tags: `` (null) for no tags and a comma string
    otherwise; the drill caught the null reaching ``Note.importance`` as
    ``None`` and killing the 3.0 index rebuild with ``len(None)``.
    """
    vault = tmp_path / "vault"
    note_path = Path("Knowledge") / "Old Note.md"
    _write_old_style_note(
        vault / "Knowledge" / "Old Note.md",
        "Old Note",
        "A note with a comma tag list in the old writer's shape.",
    )
    # And one with no tags at all — the exact bytes that crashed the rebuild —
    # and one with a null title (a hand edit the old reader never saw).
    (vault / "Knowledge" / "No Tags.md").write_text(
        '---\ntitle: "No Tags"\ntags: \n---\n\nThe fern prefers morning light.\n',
        encoding="utf-8",
    )
    (vault / "Knowledge" / "Untitled.md").write_text(
        '---\ntitle: \ntags: hosting\n---\n\nA note whose title line is null.\n',
        encoding="utf-8",
    )

    v = Vault(vault)
    note = v.read_note(note_path)
    assert isinstance(note.tags, list), f"tags must be a list, got {type(note.tags)}"
    assert note.tags == [], f"the null scalar must read as empty, got {note.tags!r}"
    assert isinstance(note.importance, float), "importance must not crash on the old shape"
    no_tags = v.read_note(Path("Knowledge") / "No Tags.md")
    assert no_tags.tags == []
    assert no_tags.title == "No Tags"
    assert isinstance(no_tags.importance, float)
    # The null title falls back to the file's stem, never None.
    untitled = v.read_note(Path("Knowledge") / "Untitled.md")
    assert untitled.title == "Untitled"
    assert untitled.tags == ["hosting"], "the comma string must read as a list"
    assert isinstance(untitled.importance, float)


def test_drill_the_old_vault_and_index(tmp_path):
    """An old-style vault and a legacy index rebuild and serve on 3.0.

    The v2.8 writer emitted ``title: "…"`` quoted and unescaped, and read with
    a plain ``---`` split — a body carrying a horizontal rule truncated it.
    3.0's reader parses the old bytes correctly, and the index migration moves
    the note ids to full paths.
    """
    vault = tmp_path / "vault"
    _write_old_style_note(
        vault / "Knowledge" / "Acme Hosting.md",
        "Acme Hosting",
        "Acme Corp hosts everything on Globex.\n\n---\n\nA horizontal rule above.\n",
    )
    _write_old_style_note(
        vault / "Knowledge" / "Sub" / "Nested Note.md",
        "Nested Note",
        "A note in a nested folder.",
    )

    index_db = tmp_path / "index.db"
    index = VaultIndex(index_db)
    try:
        index.rebuild(Vault(vault))
        assert index.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        _downgrade_index_to_legacy_ids(index)
    finally:
        index.close()

    # A fresh open migrates the legacy ids back to full paths.
    index = VaultIndex(index_db)
    try:
        assert index.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        rows = index.search_fts("Globex")
        assert rows, "the old vault's note is unfindable after the rebuild"
        assert any("Acme Hosting" == hit.title for hit in rows)

        from em.graph.model import build_graph_payload

        payload = build_graph_payload(index, include_bodies=False)
        assert payload["meta"]["note_count"] >= 2
        assert payload["nodes"], "the graph export sees no notes"
    finally:
        index.close()


def test_drill_sync_capsule_from_28_into_30(tmp_path, monkeypatch):
    """A 2.8 capsule imports into a 3.0-line profile and migrates cleanly."""
    work = _copy_fixture("v2_7_0.db", tmp_path)
    profile_a = tmp_path / "profile-a"
    profile_a.mkdir()
    store = profile_a / "memory.db"
    shutil.move(str(work), str(store))

    monkeypatch.setenv("ENTROPICMEM_MEMORY_DB", str(store))
    monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", str(profile_a / "vault"))
    monkeypatch.setenv("ENTROPICMEM_INDEX_DB", str(profile_a / "index.db"))
    capsule = tmp_path / "capsule.tar.gz"
    report = entropicmem.export_capsule(capsule)
    assert report["manifest"]["version"]

    profile_b = tmp_path / "profile-b"
    profile_b.mkdir()
    monkeypatch.setenv("ENTROPICMEM_MEMORY_DB", str(profile_b / "memory.db"))
    monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", str(profile_b / "vault"))
    monkeypatch.setenv("ENTROPICMEM_INDEX_DB", str(profile_b / "index.db"))
    entropicmem.import_capsule(capsule, trust_unverified=True)
    assert (profile_b / "memory.db").is_file()

    conn = emdb.open_db(profile_b / "memory.db")
    try:
        _baseline_shape(conn)
        before = _capture_v2(conn)
        assert before["facts"], "the capsule lost its facts in transit"
        _drill_migration(conn, before)
    finally:
        conn.close()


def test_sync_into_an_old_profile_requires_both_upgraded(tmp_path, monkeypatch):
    """The documented limitation, pinned: a migrated store syncs nowhere old.

    0002 renames the v2 tables to ``v2_*``, so a 2.8 engine opening a migrated
    store creates an empty ``facts`` table and sees none of the rows. The
    capsule round-trip in that direction must not lie about it.
    """
    from memory_engine import MemoryEngine

    work = _copy_fixture("v2_7_0.db", tmp_path)
    profile_a = tmp_path / "profile-a"
    profile_a.mkdir()
    store = profile_a / "memory.db"
    shutil.move(str(work), str(store))

    conn = emdb.open_db(store)
    try:
        migrate(conn)
    finally:
        conn.close()

    monkeypatch.setenv("ENTROPICMEM_MEMORY_DB", str(store))
    monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", str(profile_a / "vault"))
    monkeypatch.setenv("ENTROPICMEM_INDEX_DB", str(profile_a / "index.db"))
    capsule = tmp_path / "migrated.tar.gz"
    entropicmem.export_capsule(capsule)

    old_home = tmp_path / "old"
    old_home.mkdir()
    monkeypatch.setenv("ENTROPICMEM_MEMORY_DB", str(old_home / "memory.db"))
    monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", str(old_home / "vault"))
    monkeypatch.setenv("ENTROPICMEM_INDEX_DB", str(old_home / "index.db"))
    entropicmem.import_capsule(capsule, trust_unverified=True)

    with MemoryEngine(
        old_home / "memory.db", profile_id="default", hermes_home=old_home
    ) as engine:
        rows = engine.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    assert rows == 0, (
        "a 2.8 engine unexpectedly sees migrated rows — the documented "
        "limitation no longer holds; update UPGRADING.md"
    )
