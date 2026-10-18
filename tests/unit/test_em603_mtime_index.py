"""EM-603 (win 1) — the incremental index: a moved `stat`, not a re-read.

The old refresh read and hashed **every** note on every run, so a 5k-note vault
paid 5k file reads to discover that nothing had changed. `notes_meta` now
carries the file's `(mtime_ns, size)`; the refresh compares those first and only
opens a note whose stat moved. The content hash still decides whether the row is
*changed*, so a bare `touch` refreshes the stat columns and nothing else.

The card's AC is a number: **a 5k-note refresh with one changed file in under
300 ms.** The structural claim beside it is stronger and cheaper to check — an
unchanged note is **never opened** — and both are pinned here.

The recorded trade-off: a rewrite that preserves both size and mtime is
invisible to a stat diff. `rebuild_full` (`entropicmem index rebuild`) is the
escape hatch, and that is pinned too.

Rules: invented data only.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for entry in (str(REPO), str(SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from em_internal.index import SCHEMA_VERSION, VaultIndex  # noqa: E402
from em_internal.vault import Vault  # noqa: E402

AC_BUDGET_MS = 300.0


def _write_note(root: Path, rel: str, title: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        f'---\ntitle: {title}\ntype: permanent\ncreated: "2026-01-02"\n'
        f'updated: "2026-01-02"\nagent: true\n---\n\n{body}\n'
    )
    path.write_text(text, encoding="utf-8")
    return path


def _vault(tmp_path: Path, count: int = 3) -> tuple[Vault, Path]:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        _write_note(root, f"Knowledge/Note {index}.md", f"Note {index}", f"Body {index}.")
    return Vault(root), root


def _index(tmp_path: Path) -> VaultIndex:
    return VaultIndex(tmp_path / "index.db")


def _stamp(index: VaultIndex, note_id: str) -> tuple:
    row = index.db.execute(
        "SELECT mtime_ns, size FROM notes_meta WHERE note_id = ?", (note_id,)
    ).fetchone()
    return (row["mtime_ns"], row["size"])


# --- the schema ---------------------------------------------------------------


def test_a_fresh_index_is_at_version_three(tmp_path):
    index = _index(tmp_path)
    try:
        assert SCHEMA_VERSION == 3
        assert index.db.execute("PRAGMA user_version").fetchone()[0] == 3
        columns = {row[1] for row in index.db.execute("PRAGMA table_info(notes_meta)")}
        assert {"mtime_ns", "size"} <= columns
    finally:
        index.close()


# --- the read elision ---------------------------------------------------------


def test_an_unchanged_note_is_never_opened(tmp_path, monkeypatch):
    vault, root = _vault(tmp_path)
    index = _index(tmp_path)
    try:
        index.rebuild(vault)

        calls = []
        original = Vault.read_note

        def counting(self, path):
            calls.append(path)
            return original(self, path)

        monkeypatch.setattr(Vault, "read_note", counting)
        assert index.rebuild(vault) == 3
        assert calls == [], "an unchanged vault must not read a single note"
    finally:
        index.close()


def test_only_the_changed_note_is_opened(tmp_path, monkeypatch):
    vault, root = _vault(tmp_path)
    index = _index(tmp_path)
    try:
        index.rebuild(vault)
        _write_note(root, "Knowledge/Note 1.md", "Note 1", "A different body.")

        calls = []
        original = Vault.read_note

        def counting(self, path):
            calls.append(str(path))
            return original(self, path)

        monkeypatch.setattr(Vault, "read_note", counting)
        index.rebuild(vault)
        assert len(calls) == 1, calls
        assert "Note 1" in calls[0]
    finally:
        index.close()


def test_a_touch_updates_the_stat_without_reindexing(tmp_path):
    vault, root = _vault(tmp_path)
    index = _index(tmp_path)
    try:
        index.rebuild(vault)
        note_id = "Knowledge/Note 0"
        before = _stamp(index, note_id)
        index.db.execute(
            "UPDATE notes_meta SET body_preview = 'SENTINEL' WHERE note_id = ?", (note_id,)
        )
        index.db.commit()

        # Same bytes, new mtime: the stat moves, the hash does not.
        path = root / "Knowledge" / "Note 0.md"
        path.touch()
        index.rebuild(vault)

        assert _stamp(index, note_id) != before
        assert index.get_note(note_id)["body_preview"] == "SENTINEL", (
            "a touch must not re-write the row"
        )
    finally:
        index.close()


def test_a_content_change_updates_the_hash_and_the_row(tmp_path):
    vault, root = _vault(tmp_path)
    index = _index(tmp_path)
    try:
        index.rebuild(vault)
        _write_note(root, "Knowledge/Note 2.md", "Note 2", "Brand new body.")
        index.rebuild(vault)
        note = index.get_note("Knowledge/Note 2")
        assert note["body_preview"].startswith("Brand new body.")
    finally:
        index.close()


# --- the recorded trade-off ---------------------------------------------------


def test_a_same_size_same_mtime_rewrite_needs_a_full_rebuild(tmp_path):
    vault, root = _vault(tmp_path)
    index = _index(tmp_path)
    try:
        index.rebuild(vault)
        path = root / "Knowledge" / "Note 0.md"
        stat = path.stat()
        text = path.read_text(encoding="utf-8")
        # Same length ("AAAA" -> "BBBB") and the mtime is restored afterwards.
        path.write_text(text.replace("Body 0.", "Body X."), encoding="utf-8")
        import os

        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

        index.rebuild(vault)
        assert index.get_note("Knowledge/Note 0")["body_preview"].endswith("Body 0."), (
            "a stat-preserving rewrite is invisible to the incremental path"
        )

        # ... and the full rebuild is the documented escape hatch.
        index.rebuild_full(vault)
        assert index.get_note("Knowledge/Note 0")["body_preview"].endswith("Body X.")
    finally:
        index.close()


# --- the schema migration -----------------------------------------------------

_V2_SCHEMA = """
CREATE VIRTUAL TABLE notes_fts USING fts5(
    note_id UNINDEXED, title, tags, body, domain, note_type, source,
    importance UNINDEXED, tokenize='porter unicode61'
);
CREATE TABLE notes_meta (
    note_id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
    domain TEXT DEFAULT '', note_type TEXT DEFAULT 'permanent',
    importance REAL DEFAULT 0.3, tags TEXT DEFAULT '', source TEXT DEFAULT '',
    source_url TEXT DEFAULT '', created TEXT DEFAULT '', updated TEXT DEFAULT '',
    agent INTEGER DEFAULT 0, entropic_id TEXT DEFAULT '',
    body_preview TEXT DEFAULT '', content_hash TEXT DEFAULT ''
);
CREATE TABLE graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL,
    target_id TEXT NOT NULL, weight INTEGER DEFAULT 1,
    kind TEXT DEFAULT 'wikilink', UNIQUE(source_id, target_id, kind)
);
"""


def test_a_version_two_database_gains_the_columns_and_backfills(tmp_path):
    vault, root = _vault(tmp_path)
    db = tmp_path / "index.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(_V2_SCHEMA)
        conn.execute(
            "INSERT INTO notes_meta (note_id, path, title, content_hash)"
            " VALUES ('Knowledge/Note 0', 'Knowledge/Note 0.md', 'Note 0', 'stale')"
        )
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
    finally:
        conn.close()

    index = VaultIndex(db)
    try:
        assert index.db.execute("PRAGMA user_version").fetchone()[0] == 3
        # The migrated row's stat is (0, 0), so the first refresh reads it once.
        index.rebuild(vault)
        assert index.get_note("Knowledge/Note 0")["content_hash"] != "stale"
        assert _stamp(index, "Knowledge/Note 0") != (0, 0)
        # ... and the second refresh is quiet again.
        calls = []
        original = Vault.read_note

        def counting(self, path):
            calls.append(path)
            return original(self, path)

        import em_internal.vault as vault_module

        vault_module.Vault.read_note = counting
        try:
            index.rebuild(vault)
        finally:
            vault_module.Vault.read_note = original
        assert calls == []
    finally:
        index.close()


def test_a_symlinked_note_does_not_cause_a_reread_every_refresh(tmp_path, monkeypatch):
    """A linked note is not indexed, and — the part that matters for the AC —
    it must not make every refresh re-read its target under the *link's* stat,
    which would never settle (the target's stat can never equal the link's)."""
    import pytest  # noqa: PLC0415

    vault, root = _vault(tmp_path, count=1)
    real = root / "Knowledge" / "Note 0.md"
    try:
        (root / "Knowledge" / "Linked.md").symlink_to(real)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows
        pytest.skip("symlinks are unavailable on this platform")

    index = _index(tmp_path)
    try:
        index.rebuild(vault)
        assert index.get_note("Knowledge/Linked") is None

        calls = []
        original = Vault.read_note

        def counting(self, path):
            calls.append(str(path))
            return original(self, path)

        monkeypatch.setattr(Vault, "read_note", counting)
        index.rebuild(vault)
        assert calls == [], calls
    finally:
        index.close()


def test_an_escaping_symlink_is_never_indexed(tmp_path):
    """Belt and braces beside the skip above: even if a linked note were read,
    `read_note`'s `resolve_path` refuses a target outside the vault."""
    import pytest  # noqa: PLC0415

    vault, root = _vault(tmp_path, count=1)
    outside = tmp_path / "outside.md"
    outside.write_text('---\ntitle: Outside\n---\n\nSecret body.\n', encoding="utf-8")
    try:
        (root / "Knowledge" / "Escaping.md").symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows
        pytest.skip("symlinks are unavailable on this platform")

    index = _index(tmp_path)
    try:
        index.rebuild(vault)
        assert index.get_note("Knowledge/Escaping") is None
    finally:
        index.close()


# --- the CLI ------------------------------------------------------------------


def test_index_refresh_cli_picks_up_a_changed_note(tmp_path):
    import os
    import subprocess

    vault, root = _vault(tmp_path, count=2)
    db = tmp_path / "index.db"
    script = SCRIPTS / "entropicmem.py"
    env = {
        **os.environ,
        "ENTROPICMEM_VAULT_PATH": str(root),
        "ENTROPICMEM_INDEX_DB": str(db),
        "HERMES_HOME": str(tmp_path / "home"),
    }
    first = subprocess.run(
        [sys.executable, str(script), "index", "refresh"],
        capture_output=True, text=True, env=env,
    )
    assert first.returncode == 0, first.stderr
    assert "Index refreshed: 2 notes" in first.stdout, first.stdout

    _write_note(root, "Knowledge/Note 0.md", "Note 0", "Changed body.")
    second = subprocess.run(
        [sys.executable, str(script), "index", "refresh"],
        capture_output=True, text=True, env=env,
    )
    assert second.returncode == 0, second.stderr
    index = VaultIndex(db)
    try:
        assert index.get_note("Knowledge/Note 0")["body_preview"].startswith("Changed body.")
    finally:
        index.close()


# --- win 3: the reindex_vault job --------------------------------------------


def _memory_store(tmp_path: Path):
    from em.store.db import Store
    from em.store.migrations import migrate

    saved = Store(str(tmp_path / "memory.db"))
    with saved.writer() as conn:
        migrate(conn)
    return saved


class _Ctx:
    """The smallest thing that satisfies the EM-209 ``JobContext`` shape."""

    def __init__(self, store):
        self.store = store

    def heartbeat(self) -> bool:
        return True


class _Job:
    def __init__(self, payload, type_="reindex_vault"):
        self.payload = payload
        self.id = "job_test"
        self.type = type_


def test_the_reindex_job_type_is_carried_by_the_registry():
    """A worker must not claim work nothing can run, and nothing may enqueue
    work the worker will not claim — the two lists must agree (EM-410's rule)."""
    from em.jobs.registry import KNOWN_JOB_TYPES, build_registry  # noqa: PLC0415

    assert "reindex_vault" in KNOWN_JOB_TYPES
    registry = build_registry(":memory:", types=["reindex_vault"])
    assert "reindex_vault" in registry


def test_enqueue_reindex_dedupes_per_pair(tmp_path):
    from em.vault.schedule import enqueue_reindex  # noqa: PLC0415

    saved = _memory_store(tmp_path)
    try:
        with saved.transaction() as conn:
            first = enqueue_reindex(conn, root=tmp_path / "vault", index_db=tmp_path / "index.db")
            second = enqueue_reindex(conn, root=tmp_path / "vault", index_db=tmp_path / "index.db")
        rows = saved.reader().execute(
            "SELECT id FROM jobs WHERE type='reindex_vault'"
        ).fetchall()
        assert first is not None and first == second
        assert len(rows) == 1
    finally:
        saved.close()


def test_enqueue_reindex_needs_both_paths(tmp_path):
    from em.vault.schedule import enqueue_reindex  # noqa: PLC0415

    saved = _memory_store(tmp_path)
    try:
        with saved.transaction() as conn:
            assert enqueue_reindex(conn, root="", index_db="x") is None
            assert enqueue_reindex(conn, root="x", index_db=None) is None
    finally:
        saved.close()


def test_the_reindex_handler_refreshes_the_index(tmp_path):
    from em.vault.schedule import make_reindex_vault_handler  # noqa: PLC0415

    vault, root = _vault(tmp_path, count=2)
    db = tmp_path / "index.db"
    saved = _memory_store(tmp_path)
    try:
        handler = make_reindex_vault_handler()
        count = handler(
            _Job({"root": str(root), "index_db": str(db)}), _Ctx(saved)
        )
        assert count == 2
    finally:
        saved.close()

    index = VaultIndex(db)
    try:
        assert index.get_note("Knowledge/Note 0")["title"] == "Note 0"
    finally:
        index.close()


def test_a_reindex_payload_without_paths_is_permanent(tmp_path):
    import pytest  # noqa: PLC0415

    from em.jobs.worker import PermanentJobError  # noqa: PLC0415
    from em.vault.schedule import make_reindex_vault_handler  # noqa: PLC0415

    saved = _memory_store(tmp_path)
    try:
        handler = make_reindex_vault_handler()
        with pytest.raises(PermanentJobError):
            handler(_Job({"root": str(tmp_path / "vault")}), _Ctx(saved))
    finally:
        saved.close()


def test_a_missing_vault_root_is_permanent(tmp_path):
    import pytest  # noqa: PLC0415

    from em.jobs.worker import PermanentJobError  # noqa: PLC0415
    from em.vault.schedule import make_reindex_vault_handler  # noqa: PLC0415

    saved = _memory_store(tmp_path)
    try:
        handler = make_reindex_vault_handler()
        with pytest.raises(PermanentJobError):
            handler(
                _Job(
                    {
                        "root": str(tmp_path / "nope"),
                        "index_db": str(tmp_path / "index.db"),
                    }
                ),
                _Ctx(saved),
            )
    finally:
        saved.close()


def test_the_projection_handler_schedules_a_reindex(tmp_path):
    from em.vault.schedule import make_project_vault_handler  # noqa: PLC0415

    root = tmp_path / "vault"
    root.mkdir()
    index_db = tmp_path / "index.db"
    saved = _memory_store(tmp_path)
    try:
        handler = make_project_vault_handler()
        handler(
            _Job(
                {
                    "root": str(root),
                    "scope": {"profile": "default"},
                    "modes": ["entities"],
                    "index_db": str(index_db),
                },
                type_="project_vault",
            ),
            _Ctx(saved),
        )
        row = saved.reader().execute(
            "SELECT payload FROM jobs WHERE type='reindex_vault'"
        ).fetchone()
        assert row is not None, "the projection must schedule the index refresh"
        assert json.loads(row["payload"])["index_db"] == str(index_db)
    finally:
        saved.close()


def test_a_projection_without_an_index_path_schedules_nothing(tmp_path):
    from em.vault.schedule import make_project_vault_handler  # noqa: PLC0415

    root = tmp_path / "vault"
    root.mkdir()
    saved = _memory_store(tmp_path)
    try:
        handler = make_project_vault_handler()
        handler(
            _Job(
                {"root": str(root), "scope": {"profile": "default"}, "modes": ["entities"]},
                type_="project_vault",
            ),
            _Ctx(saved),
        )
        rows = saved.reader().execute(
            "SELECT id FROM jobs WHERE type='reindex_vault'"
        ).fetchall()
        assert rows == []
    finally:
        saved.close()


# --- the AC -------------------------------------------------------------------


def test_a_five_thousand_note_refresh_with_one_change_is_under_300ms(tmp_path):
    root = tmp_path / "vault"
    root.mkdir(parents=True)
    (root / "Knowledge").mkdir()
    body = (
        '---\ntitle: Note {i}\ntype: permanent\ncreated: "2026-01-02"\n'
        'updated: "2026-01-02"\nagent: true\n---\n\nBody {i} about [[Note 0]].\n'
    )
    for i in range(5_000):
        (root / "Knowledge" / f"Note {i}.md").write_text(
            body.format(i=i), encoding="utf-8"
        )
    vault = Vault(root)
    index = _index(tmp_path)
    try:
        cold = time.perf_counter()
        assert index.rebuild(vault) == 5_000
        cold_ms = (time.perf_counter() - cold) * 1000.0

        _write_note(root, "Knowledge/Note 2500.md", "Note 2500", "One changed body.")

        started = time.perf_counter()
        assert index.rebuild(vault) == 5_000
        warm_ms = (time.perf_counter() - started) * 1000.0

        print(f"[index] 5k cold {cold_ms:.1f} ms, warm-with-1-change {warm_ms:.1f} ms")
        assert warm_ms < AC_BUDGET_MS, (
            f"5k refresh with one change took {warm_ms:.1f} ms (AC: < {AC_BUDGET_MS:.0f} ms)"
        )
    finally:
        index.close()
