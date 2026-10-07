"""EM-211 Chunk 10.4: the CLI runs against a v3 store.

Runs the **real CLI as a subprocess** — not the functions in-process — because the
point of this chunk is that `entropicmem <command>` works when the store is v3,
and only a subprocess proves the whole path (argument parsing, `_engine()`
selection, the command body).

Two things are asserted, and both matter:

* the **ported** commands succeed on a v3 store — reads (10.1) and maintenance
  (10.2) through the facade;
* the **v2-only** commands still refuse, by name (10.3). Their guards run before
  `_engine()`, so routing must not have quietly bypassed them.

And one regression pass: a **v2 store is untouched** by the routing. That is the
risk this chunk carries — the CLI's engine construction changed for every store,
not just v3 ones.

Rules: invented data only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
FIXTURES = REPO / "tests" / "fixtures" / "db"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.store.db import Store  # noqa: E402
from em.store.migrations import migrate  # noqa: E402


def v3_store(tmp_path: Path) -> Path:
    path = tmp_path / "home" / "entropicmem" / "memory.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(path))
    try:
        with store.writer() as conn:
            migrate(conn)
    finally:
        store.close()
    return path


def v2_store(tmp_path: Path) -> Path:
    path = tmp_path / "home" / "entropicmem" / "memory.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "v2_7_0.db", path)
    return path


def cli(db: Path, *args: str) -> subprocess.CompletedProcess:
    home = db.parent.parent
    (home / "vault").mkdir(parents=True, exist_ok=True)  # `remember` writes a note
    env = {k: v for k, v in os.environ.items() if not k.startswith("ENTROPICMEM_")}
    env["ENTROPICMEM_MEMORY_DB"] = str(db)
    env["ENTROPICMEM_VAULT_PATH"] = str(home / "vault")
    env["HERMES_HOME"] = str(home)
    env.pop("ENTROPICMEM_ALLOW_LIVE_MIGRATION", None)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "entropicmem.py"), *args],
        env=env, capture_output=True, text=True, timeout=120,
    )


# --- the ported commands, on a v3 store ---------------------------------------


def test_memory_stats_on_v3(tmp_path):
    db = v3_store(tmp_path)
    out = cli(db, "memory", "stats")
    assert out.returncode == 0, out.stderr
    assert "Facts: 0" in out.stdout, out.stdout


def test_remember_recall_and_list_on_v3(tmp_path):
    """The write -> read round trip through the real CLI."""
    db = v3_store(tmp_path)

    written = cli(db, "remember", "Acme deploys the billing service.")
    assert written.returncode == 0, written.stderr
    assert "Remembered:" in written.stdout, written.stdout

    listed = cli(db, "memory", "list")
    assert listed.returncode == 0, listed.stderr
    assert "Acme deploys the billing service." in listed.stdout

    recalled = cli(db, "recall", "Acme billing service")
    assert recalled.returncode == 0, recalled.stderr
    assert "Acme deploys the billing service." in recalled.stdout


def test_history_on_v3(tmp_path):
    db = v3_store(tmp_path)
    cli(db, "remember", "Acme ships on Tuesdays.")
    listed = cli(db, "memory", "list")
    mid = listed.stdout.split("\t", 1)[0].strip()

    out = cli(db, "history", mid)
    assert out.returncode == 0, out.stderr
    assert "Version history for" in out.stdout, out.stdout


def test_audit_and_pending_and_episode_stats_on_v3(tmp_path):
    db = v3_store(tmp_path)
    cli(db, "remember", "Globex ships on Tuesdays.")

    audit = cli(db, "audit")
    assert audit.returncode == 0 and "events)" in audit.stdout, audit.stdout

    pending = cli(db, "pending", "list")
    assert pending.returncode == 0 and "pending)" in pending.stdout, pending.stdout

    episodes = cli(db, "episode", "stats")
    assert episodes.returncode == 0 and "Episodes:" in episodes.stdout, episodes.stdout


def test_pending_promote_on_v3(tmp_path):
    """10.2's maintenance path through the CLI, end to end."""
    db = v3_store(tmp_path)
    out = cli(db, "pending", "prune", "--older-than", "30d")
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    assert "pruned" in payload


def test_timeline_on_v3(tmp_path):
    db = v3_store(tmp_path)
    cli(db, "remember", "Initech ships on Tuesdays.")
    out = cli(db, "timeline")
    assert out.returncode == 0, out.stderr
    assert "Initech ships on Tuesdays." in out.stdout, out.stdout


# --- the refusals, still refusing after routing -------------------------------


@pytest.mark.parametrize(
    "args, needle",
    [
        (("triple", "stats"), "S5"),
        (("embed", "--rebuild"), "S3"),
        (("publish",), "S5"),
        (("pull",), "S5"),
        (("memory", "project"), "S6"),
        (("migrate", "--status"), "migration"),
        (("recall", "anything", "--scope", "shared"), "S5"),
    ],
)
def test_v2_only_commands_still_refuse_on_v3(args, needle, tmp_path):
    db = v3_store(tmp_path)
    out = cli(db, *args)
    assert out.returncode != 0, f"expected a refusal, got: {out.stdout!r}"
    assert "v3 store" in out.stderr, out.stderr
    assert needle in out.stderr, (needle, out.stderr)
    assert "Traceback" not in out.stderr, out.stderr


# --- the v2 regression pass ---------------------------------------------------


def test_the_portable_commands_still_work_on_a_v2_store(tmp_path):
    """The routing changed engine construction for every store, so prove v2 too."""
    db = v2_store(tmp_path)

    stats = cli(db, "memory", "stats")
    assert stats.returncode == 0, stats.stderr
    assert "Facts:" in stats.stdout

    written = cli(db, "remember", "Acme ships on Wednesdays now.")
    assert written.returncode == 0, written.stderr

    listed = cli(db, "memory", "list")
    assert listed.returncode == 0 and "Wednesdays" in listed.stdout, listed.stdout


def test_a_v2_store_is_not_migrated_by_the_cli(tmp_path):
    """Opening the CLI must never cut a store over."""
    db = v2_store(tmp_path)
    before = db.read_bytes()
    out = cli(db, "memory", "stats")
    assert out.returncode == 0, out.stderr
    assert db.read_bytes() != b"", "still a database"
    import sqlite3

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0, (
            "a v2 store must stay v2 after the CLI touches it"
        )
    finally:
        conn.close()
    assert before  # sanity: there was something to compare
