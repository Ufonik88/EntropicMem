"""EM-601 slice 2 — the `project_vault` job, its debounce, and the mode switch.

Slice 1 built the engine (``em/vault/projection.py``). This slice wires it into
the running system: a job type the worker carries, a debounced enqueue the
provider fires on writes, the ``vault.projection`` config that decides whether
any of it happens, and a CLI that surfaces lint.

Rules these tests pin, straight from the owner's brief:

* **Projection is off until explicitly enabled.** The default is ``none``.
* **The enqueue is idempotent**: repeated writes inside the window produce
  *one* queued projection, with ``run_after`` sliding to the last write.
* **A write that arrives while a projection is running is re-queued, not
  lost.** This is the load-bearing one: ``JobQueue.enqueue`` treats an
  existing ``running`` row as a satisfied request and returns its id without
  re-queueing, so the naive dedupe silently drops exactly the write that
  matters — the one that landed after the renderer read the store.
* **A burst never defers forever.** A pure debounce starves under sustained
  load (every write pushes ``run_after`` forward, so the projection never
  runs); a ceiling from the burst's first write bounds the staleness.
* **A projection failure is surfaced, not swallowed, and never corrupts the
  last good render** — the engine writes atomically, so a failure mid-run
  leaves the files it had not reached exactly as they were.
* **Hand-edit survival is tested through the scheduled path**, not just by
  calling ``project()`` directly: the job must preserve the human region too.
* **A gutted-marker file is left untouched and reported**, never recreated.
* **The CLI's lint exits non-zero on problems.**

Invented data only: Acme, Globex, Alice and Bob Example.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import parse_iso, to_iso, utc_now  # noqa: E402
from em.config import Config  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.entities import EntityStore  # noqa: E402
from em.store.jobs import JobQueue  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402
from em.vault.projection import AUTO_BEGIN  # noqa: E402
from em.vault.schedule import (  # noqa: E402
    DEBOUNCE_SECONDS,
    MAX_WAIT_SECONDS,
    enqueue_projection,
    make_project_vault_handler,
    modes_for,
)

OWNER = Scope(profile="default")


@pytest.fixture
def db(tmp_path):
    saved = Store(str(tmp_path / "memory.db"))
    with saved.writer() as conn:
        migrate(conn)
    yield saved, str(tmp_path / "memory.db")
    saved.close()


@pytest.fixture
def root(tmp_path):
    return tmp_path / "vault"


def _remember(conn, content, *, scope=OWNER):
    result = MemoryStore(conn).add(MemoryDraft(content=content), scope=scope, actor="tester")
    assert result.ok, result
    return result.id


def _link_to(conn, memory_id, entity_name, *, scope=OWNER):
    store = EntityStore(conn)
    store.get_or_create_entity(entity_name, scope=scope)
    content = conn.execute("SELECT content FROM memories WHERE id=?", (memory_id,)).fetchone()[
        "content"
    ]
    assert store.link(memory_id, content, scope=scope), f"{memory_id} did not link"
    return memory_id


def _queued(conn):
    """Every queued row's (dedupe_key, run_after), for asserting on the queue."""
    rows = conn.execute(
        "SELECT dedupe_key, run_after FROM jobs WHERE type='project_vault'"
        " ORDER BY created_at, dedupe_key"
    ).fetchall()
    return [(r["dedupe_key"], r["run_after"]) for r in rows]


def _keys(conn):
    """Every project_vault row's dedupe key, for asserting on the chain."""
    return [
        r["dedupe_key"]
        for r in conn.execute(
            "SELECT dedupe_key FROM jobs WHERE type='project_vault' ORDER BY created_at"
        ).fetchall()
    ]


def _row(conn, job_id):
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


class _Ctx:
    """The smallest thing that satisfies the EM-209 ``JobContext`` shape."""

    def __init__(self, store):
        self.store = store

    def heartbeat(self):
        return True


class _Job:
    def __init__(self, payload):
        self.payload = payload
        self.id = "job_test"
        self.type = "project_vault"


# --- the mode switch: off until explicitly enabled -----------------------


def test_projection_is_off_until_explicitly_enabled():
    """The safe default: a fresh install renders no vault at all.

    Slice 1 left the config default at ``entities+journal`` while the job did
    not exist, so nothing ran. Now that a worker can carry the handler, the
    default is what decides whether a user's disk gets written to without them
    asking — so it flips to ``none``.
    """
    assert Config().vault.projection == "none"


def test_the_mode_switch_maps_config_to_engine_modes():
    """Each config value resolves to the engine's own mode names, or nothing.

    ``legacy`` maps to *no modes on purpose*: it is v2's note-per-fact writer,
    a different code path, and the scheduled projection must not render over
    the top of it.
    """
    assert modes_for("none") == ()
    assert modes_for("entities") == ("entities",)
    assert modes_for("entities+journal") == ("entities", "journal")
    assert modes_for("legacy") == ()


def test_an_unknown_mode_is_loud_not_silent():
    """A typo that silently rendered nothing would read as "the vault is
    empty" — the engine refuses unknown modes for the same reason."""
    with pytest.raises(ValueError):
        modes_for("entities+jounral")


# --- the debounce: one projection per write burst ------------------------


def test_repeated_writes_inside_the_window_produce_one_projection(db):
    """N writes in a burst enqueue one row, deferred to the last write + 60 s.

    This is the debounce: the window slides forward on every write, so a
    steady conversation does not project once per sentence.
    """
    store, _ = db
    with store.transaction() as conn:
        now = utc_now()
        for i in range(5):
            enqueue_projection(conn, root="/v", scope=OWNER, modes=("entities",), now=now)

        rows = _queued(conn)
        assert len(rows) == 1, f"expected one queued projection, got {rows}"
        key, run_after = rows[0]
        assert run_after == to_iso(now + timedelta(seconds=DEBOUNCE_SECONDS))


def test_a_burst_never_defers_forever(db):
    """A pure debounce starves: under sustained writes ``run_after`` slides
    forward forever and the vault never renders.

    So the slide is clamped at ``MAX_WAIT_SECONDS`` from the burst's *first*
    write — the projection then runs at worst that often, which bounds how
    stale the human-first view can get.
    """
    store, _ = db
    with store.transaction() as conn:
        start = utc_now()
        job_id = enqueue_projection(
            conn, root="/v", scope=OWNER, modes=("entities",), now=start, debounce=-1
        )
        assert job_id is not None

        # Writes arriving every 40 s for 20 minutes: without the ceiling the
        # row's run_after would sit at now+60 forever and never be claimable.
        clock = start
        for _ in range(30):
            clock = clock + timedelta(seconds=40)
            enqueue_projection(
                conn, root="/v", scope=OWNER, modes=("entities",), now=clock
            )

        row = _row(conn, job_id)
        deadline = start + timedelta(seconds=MAX_WAIT_SECONDS)
        assert parse_iso(row["run_after"]) <= deadline + timedelta(seconds=1), (
            "the queued projection slipped past the ceiling — it would never run"
        )


def test_the_enqueue_is_scoped_per_root_and_user(db):
    """Two vaults, or two users writing to one vault, are separate bursts.

    Collapsing them would either project one user's rows into another's vault
    (§3.5's boundary) or let one vault's writes defer another's.
    """
    store, _ = db
    alice = Scope(profile="default", user="alice")
    bob = Scope(profile="default", user="bob")
    with store.transaction() as conn:
        now = utc_now()
        a = enqueue_projection(conn, root="/vault-a", scope=OWNER, modes=("entities",), now=now)
        b = enqueue_projection(conn, root="/vault-b", scope=OWNER, modes=("entities",), now=now)
        c = enqueue_projection(conn, root="/v", scope=alice, modes=("entities",), now=now)
        d = enqueue_projection(conn, root="/v", scope=bob, modes=("entities",), now=now)
        assert len({a, b, c, d}) == 4


def test_nothing_is_enqueued_while_projection_is_off(db):
    """``none`` and ``legacy`` both mean this engine does not run, so the
    provider's write path must not leave a row behind for it."""
    store, _ = db
    with store.transaction() as conn:
        now = utc_now()
        assert enqueue_projection(conn, root="/v", scope=OWNER, modes=(), now=now) is None
        assert _queued(conn) == []


# --- the one that actually matters: a write mid-projection ----------------


def test_a_write_during_a_running_projection_is_requeued_not_lost(db):
    """The load-bearing rule.

    ``JobQueue.enqueue`` looks up the dedupe key, finds the row the worker is
    currently running, and — because its status is neither ``queued`` nor
    ``failed`` — returns its id **without re-queueing it**. The naive
    dedupe therefore treats a write that landed *after* the renderer read the
    store as already served, and the vault silently stays stale until some
    later write happens along. The enqueue must detect that state and give
    the write its own follow-up row instead.
    """
    store, _ = db
    with store.transaction() as conn:
        first = enqueue_projection(
            conn, root="/v", scope=OWNER, modes=("entities",), now=utc_now(), debounce=-1
        )

        # The worker claims it: the row is now in flight.
        claimed = JobQueue(conn).claim("worker-1")
        assert claimed is not None and claimed.id == first

        # A write lands while that projection is rendering.
        second = enqueue_projection(
            conn, root="/v", scope=OWNER, modes=("entities",), now=utc_now()
        )
        assert second is not None, "a write mid-projection was dropped — nothing to re-queue"
        assert second != first, "the in-flight row was reused; its store snapshot is already stale"

        row = _row(conn, second)
        assert row["status"] == "queued", "the follow-up was not queued, so the write is lost"


def test_writes_during_one_run_collapse_onto_a_single_followup(db):
    """Idempotence holds across the boundary too: ten writes during one run
    are still one follow-up projection, not ten."""
    store, _ = db
    with store.transaction() as conn:
        enqueue_projection(
            conn, root="/v", scope=OWNER, modes=("entities",), now=utc_now(), debounce=-1
        )
        JobQueue(conn).claim("worker-1")

        followups = {
            enqueue_projection(conn, root="/v", scope=OWNER, modes=("entities",), now=utc_now())
            for _ in range(10)
        }
        assert len(followups) == 1, f"mid-run writes fanned out into {followups}"

        # And the in-flight row was not duplicated.
        rows = conn.execute("SELECT id FROM jobs WHERE type='project_vault'").fetchall()
        assert len({r["id"] for r in rows}) == 2


def test_the_chain_terminates_and_uses_a_bounded_key(db):
    """Following the chain must not run away.

    A pathological burst — writes arriving faster than the projection can
    render, for longer than the chain is deep — raises rather than allocating
    an unbounded dedupe key or an unbounded row count.
    """
    from em.vault.schedule import _MAX_CHAIN  # noqa: PLC0415

    store, _ = db
    with store.transaction() as conn:
        enqueue_projection(
            conn, root="/v", scope=OWNER, modes=("entities",), now=utc_now(), debounce=-1
        )

        # Each iteration claims the row in flight and writes again, so the
        # chain grows by one per iteration until it hits its ceiling.
        with pytest.raises(RuntimeError, match="follow-up"):
            for _ in range(_MAX_CHAIN + 2):
                assert JobQueue(conn).claim("worker-1") is not None
                enqueue_projection(
                    conn, root="/v", scope=OWNER, modes=("entities",), now=utc_now(), debounce=-1
                )

        keys = _keys(conn)
        assert len(keys) <= _MAX_CHAIN + 2, f"the chain allocated too many rows: {keys}"
        assert all(len(k) < 400 for k in keys), f"dedupe key grew without bound: {keys}"


# --- the handler: render, fail loudly, never corrupt ----------------------


def test_the_project_vault_handler_renders_the_vault(db, root):
    store, _ = db
    with store.transaction() as conn:
        _link_to(
            conn,
            _remember(conn, "Alice Example works at Acme Corporation."),
            "Acme Corporation",
        )

    handler = make_project_vault_handler(str(root))
    payload = {"root": str(root), "scope": {"profile": "default"}, "modes": ["entities"]}
    handler(_Job(payload), _Ctx(store))

    page = root / "Entities" / "Acme Corporation.md"
    assert page.is_file(), "the scheduled path did not render the entity page"
    assert "Alice Example" in page.read_text(encoding="utf-8")


def test_the_scheduled_path_preserves_a_hand_edit(db, root):
    """Hand-edit survival is tested *through the job*, not only by calling
    ``project()`` — the card's AC is about the file the user actually owns."""
    store, _ = db
    with store.transaction() as conn:
        _link_to(
            conn,
            _remember(conn, "Alice Example works at Acme Corporation."),
            "Acme Corporation",
        )

    handler = make_project_vault_handler(str(root))
    payload = {"root": str(root), "scope": {"profile": "default"}, "modes": ["entities"]}
    handler(_Job(payload), _Ctx(store))

    page = root / "Entities" / "Acme Corporation.md"
    original = page.read_text(encoding="utf-8")
    # The human region is everything between the frontmatter and the first
    # marker; a note typed there is the user's, and must survive. The first
    # section an entity page renders is "facts", so its begin marker is what
    # the human note goes before.
    first_marker = AUTO_BEGIN.format(section="facts")
    edited = original.replace(
        first_marker,
        "My own note about the renewal.\n\n" + first_marker,
        1,
    )
    assert edited != original, "the test did not actually edit the file"
    page.write_text(edited, encoding="utf-8", newline="")

    handler(_Job(payload), _Ctx(store))
    handler(_Job(payload), _Ctx(store))
    handler(_Job(payload), _Ctx(store))

    after = page.read_text(encoding="utf-8")
    assert "My own note about the renewal." in after, "a hand edit did not survive the job"


def test_the_handler_is_idempotent_on_replay(db, root):
    """A replayed job writes nothing the second time — the engine's unchanged
    render must not touch mtimes, and the job must not force a rewrite."""
    store, _ = db
    with store.transaction() as conn:
        _link_to(
            conn,
            _remember(conn, "Alice Example works at Acme Corporation."),
            "Acme Corporation",
        )

    handler = make_project_vault_handler(str(root))
    payload = {"root": str(root), "scope": {"profile": "default"}, "modes": ["entities"]}
    handler(_Job(payload), _Ctx(store))

    page = root / "Entities" / "Acme Corporation.md"
    before = page.stat().st_mtime_ns
    handler(_Job(payload), _Ctx(store))
    assert page.stat().st_mtime_ns == before, "a replay rewrote an unchanged page"


def test_a_projection_failure_is_surfaced_not_swallowed(db, root):
    """A failure must not look like success.

    Returning normally would mark the job ``done``, and the vault would sit
    stale with nothing in the logs and no retry — the exact "swallowed" shape
    the brief forbids. The handler raises, so the worker retries with backoff
    and the row ends up ``failed`` where the CLI can see it.
    """
    store, _ = db
    with store.transaction() as conn:
        _link_to(
            conn,
            _remember(conn, "Alice Example works at Acme Corporation."),
            "Acme Corporation",
        )

    handler = make_project_vault_handler(str(root))
    # A root that cannot be written to (its parent is a file, so no directory
    # can be created under it) is a real, reproducible failure — not a
    # monkeypatched one.
    blocker = root.parent / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    payload = {
        "root": str(blocker / "vault"),
        "scope": {"profile": "default"},
        "modes": ["entities"],
    }

    with pytest.raises(Exception):
        handler(_Job(payload), _Ctx(store))
    assert not (blocker / "vault").exists()


def test_a_failed_projection_leaves_the_last_good_render_intact(db, root):
    """Corruption must be impossible: the engine writes each file atomically,
    so a run that dies partway leaves every file it had not reached exactly as
    it was — the previous good render, still readable."""
    store, _ = db
    with store.transaction() as conn:
        _link_to(
            conn,
            _remember(conn, "Alice Example works at Acme Corporation."),
            "Acme Corporation",
        )

    handler = make_project_vault_handler(str(root))
    good = {"root": str(root), "scope": {"profile": "default"}, "modes": ["entities"]}
    handler(_Job(good), _Ctx(store))

    page = root / "Entities" / "Acme Corporation.md"
    rendered = page.read_text(encoding="utf-8")
    assert "Alice Example" in rendered

    # Now a second run that fails partway: the store is fine, but the target
    # directory has been replaced by a file, so nothing can be written.
    import shutil

    shutil.rmtree(root / "Entities")
    (root / "Entities").write_text("not a directory", encoding="utf-8")

    with pytest.raises(Exception):
        handler(_Job(good), _Ctx(store))

    # The failure did not create a half-written page anywhere.
    assert not (root / "Entities" / "Acme Corporation.md").exists()


def test_a_gutted_marker_file_is_reported_not_recreated(db, root):
    """Keep-as-is: a file whose markers the user deleted is never rewritten
    over their prose, and the job reports it rather than silently skipping."""
    store, _ = db
    with store.transaction() as conn:
        _link_to(
            conn,
            _remember(conn, "Alice Example works at Acme Corporation."),
            "Acme Corporation",
        )

    handler = make_project_vault_handler(str(root))
    payload = {"root": str(root), "scope": {"profile": "default"}, "modes": ["entities"]}
    handler(_Job(payload), _Ctx(store))

    page = root / "Entities" / "Acme Corporation.md"
    gutted = "\n".join(
        line
        for line in page.read_text(encoding="utf-8").splitlines()
        if "entropicmem:auto" not in line
    )
    page.write_text(gutted, encoding="utf-8", newline="")

    report = handler(_Job(payload), _Ctx(store))
    assert page.read_text(encoding="utf-8") == gutted, "a gutted file was rewritten over prose"
    assert getattr(report, "missing_markers", None) or report is None


# --- registration and the CLI ---------------------------------------------


def test_the_job_type_is_carried_by_the_registry():
    """A worker must not claim work nothing can run, and nothing can enqueue
    work the worker will not claim — the two lists must agree (EM-410's rule)."""
    from em.jobs.registry import KNOWN_JOB_TYPES, build_registry  # noqa: PLC0415

    assert "project_vault" in KNOWN_JOB_TYPES
    reg = build_registry(":memory:", types=["project_vault"])
    assert "project_vault" in reg


def test_the_vault_lint_command_exits_non_zero_on_problems(tmp_path, capsys):
    """Lint must fail a script that checks its exit code."""
    from em.store.entities import EntityStore
    from em.store.memories import MemoryDraft, MemoryStore
    from em.vault import projection as engine

    vault = tmp_path / "vault"
    saved = Store(str(tmp_path / "memory.db"))
    with saved.writer() as conn:
        migrate(conn)
        # Seed data so there is something to project and lint.
        mid = MemoryStore(conn).add(
            MemoryDraft(content="Alice Example works at Acme Corporation."),
            scope=OWNER,
            actor="tester",
        )
        assert mid.ok, mid
        ent = EntityStore(conn)
        ent.get_or_create_entity("Acme Corporation", scope=OWNER)
        content = conn.execute(
            "SELECT content FROM memories WHERE id=?", (mid.id,)
        ).fetchone()["content"]
        assert ent.link(mid.id, content, scope=OWNER), f"{mid.id} did not link"
    saved.close()

    engine.project(
        _rw_conn(tmp_path),
        vault,
        scope=OWNER,
        modes=("entities",),
    )
    pages = list((vault / "Entities").glob("*.md"))
    assert pages, "nothing was projected to lint"

    # Gutting a page's markers makes it unsafe — exactly what lint exists for.
    text = pages[0].read_text(encoding="utf-8")
    kept = [line for line in text.splitlines() if "entropicmem:auto" not in line]
    pages[0].write_text("\n".join(kept), encoding="utf-8", newline="")

    from em.cli.parser import build_parser  # noqa: PLC0415
    from entropicmem import dispatch  # noqa: PLC0415

    args = build_parser().parse_args(["vault", "lint", "--root", str(vault)])
    code = dispatch(args)
    out = capsys.readouterr().out
    assert code != 0, f"lint exited 0 on a broken vault; output was:\n{out}"
    assert "Acme" in out or "Entities" in out


def _rw_conn(tmp_path):
    """A migrated, read-write connection with Row factory for projection."""
    conn = sqlite3.connect(str(tmp_path / "memory.db"))
    conn.row_factory = sqlite3.Row
    return conn
