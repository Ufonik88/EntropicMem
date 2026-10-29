"""Chunk 56 — the shadow's scratch dir is an allowed migration root.

Hermes's P0c collection found the shadow's own default copy location
(``~/.hermes/entropicmem-shadow/``) is a path the migration guard refuses —
the guard's allow-list covered only tempdir and test trees, so the shadow's
copy could never migrate on a normal host and the collection silently
produced nothing (``shadow_ids`` raised "no such table: memories" and
``run`` swallowed it at debug).

The guard's purpose is protecting data that has no other copy. The shadow's
copy **is** the copy: it is refreshed from the live store, its loss costs one
re-copy, and nothing else lives in its directory. So an **exact** directory
match on ``<hermes_root>/entropicmem-shadow`` is now an allowed root, after
the live-store deny rules (which keep their precedence).

The decision is a pure function of the resolved path and the home
(``_path_decision``), so the tests pin the allow/deny distinctions without
touching the real home or any file.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.store import db as emdb  # noqa: E402
from em.store import migrations as emmig  # noqa: E402
from em.store.migrations import LATEST, migrate  # noqa: E402


def _decision(path: str, home: str) -> str:

    return emmig._path_decision(Path(path), Path(home))


def test_the_shadow_scratch_dir_is_an_allowed_root():
    """The exact shadow dir under the hermes root: allowed, not by tempdir."""
    assert _decision("/home/u/.hermes/entropicmem-shadow/memory.db", "/home/u") == "allowed"


def test_the_live_store_dir_is_still_refused():
    assert _decision("/home/u/.hermes/entropicmem/memory.db", "/home/u") == "refused"


def test_a_versioned_live_clone_is_still_refused():
    assert _decision("/home/u/.hermes/entropicmem-live-3.0.0/memory.db", "/home/u") == "refused"


def test_the_allow_is_exact_not_a_prefix_family():
    """A sibling that merely starts with the same text stays refused."""
    assert _decision("/home/u/.hermes/entropicmem-shadow-evil/memory.db", "/home/u") == "refused"
    assert _decision("/home/u/.hermes/entropicmem-shadowed/memory.db", "/home/u") == "refused"


def test_a_shadow_dir_outside_the_hermes_root_stays_refused():
    """The allow is <hermes_root>/entropicmem-shadow, not any path named that."""
    assert _decision("/var/scratch/entropicmem-shadow/memory.db", "/home/u") == "refused"


def test_an_arbitrary_hermes_dir_stays_refused():
    assert _decision("/home/u/.hermes/hermes-agent/memory.db", "/home/u") == "refused"


def test_tempdir_and_tests_trees_stay_allowed():
    import tempfile

    temp_root = Path(tempfile.gettempdir()).resolve()
    assert _decision(str(temp_root / "anything" / "memory.db"), "/home/u") == "allowed"
    assert _decision(str(Path("/repo/tests/fixtures/x.db")), "/home/u") == "allowed"


def test_an_empty_db_copy_at_the_shadow_dir_migrates_end_to_end(tmp_path, monkeypatch):
    """The plumbing, end to end: a copy at a (faked) shadow dir migrates."""
    home = tmp_path / "home"
    copy = home / ".hermes" / "entropicmem-shadow" / "memory.db"
    copy.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(copy)
    conn.close()  # an empty file: the guard's empty-store rule applies anyway
    monkeypatch.setattr(emmig.Path, "home", lambda: home)
    conn = emdb.open_db(copy)
    try:
        applied = migrate(conn)
        assert [m.version for m in applied] == list(range(1, LATEST + 1))
    finally:
        conn.close()
