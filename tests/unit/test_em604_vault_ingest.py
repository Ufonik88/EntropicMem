"""EM-604 — opt-in ingestion of human vault edits.

The card (``REMAINING_PLAN.md`` §6.5) is the other direction of EM-601: the
projection writes the store into Markdown, and this reads a *human* edit back.
It is off by default, and what it produces is a **proposal**, never a durable
fact.

Rules these tests pin:

* **Off by default.** ``vault.ingest_human_edits`` is ``False``; the pass runs
  only when the job payload says so.
* **Only the human region.** A ``- <statement>`` line *outside* every
  ``entropicmem:auto`` block becomes a ``pending`` memory with
  ``source="vault_edit"``, linked to that page's entity — so the user's own note
  lands in the review queue, not the live store. Lines inside an auto-section
  (the projection's own bullets) are never re-ingested.
* **Idempotent.** Re-ingesting an unchanged page writes nothing; the store's
  exact-duplicate guard carries it.
* **A removed auto-section line is a hint, not an edit.** The projection
  re-adds it; ingestion never touches it, but records ``user removed line for
  m·… - forget?`` for the ``review`` surface.
* **A page whose markers were gutted is skipped**, not guessed at.
* **Scope bounds it** (F-004): an entity that belongs to another profile is not
  ingested.

Invented data only: Acme, Globex, Alice and Bob Example.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import short_id  # noqa: E402
from em.config import SCHEMA_KEYS, Config, config_schema_fields  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.entities import EntityStore  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402
from em.vault.ingest import ingest, read_hints  # noqa: E402
from em.vault.projection import AUTO_BEGIN, AUTO_END, project  # noqa: E402
from em.vault.schedule import enqueue_projection, make_project_vault_handler  # noqa: E402

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


# --- helpers -----------------------------------------------------------------


def _remember(conn, content, *, scope=OWNER):
    result = MemoryStore(conn).add(
        MemoryDraft(content=content, status="active"), scope=scope, actor="tester"
    )
    assert result.ok, result
    return result.id


def _entity_page(conn, root, name="Acme Corp", content="Acme Corp uses Globex for hosting."):
    """Render one entity page. Returns ``(entity_id, memory_id, page path)``."""
    mid = _remember(conn, content)
    store = EntityStore(conn)
    entity_id = store.get_or_create_entity(name, scope=OWNER)
    assert store.link(mid, content, scope=OWNER), "the seed did not link"
    project(conn, root, scope=OWNER, modes=("entities",))
    return entity_id, mid, root / "Entities" / f"{name}.md"


def _insert_human_line(page: Path, line: str) -> None:
    """Put ``line`` in the page's human region (before the first marker)."""
    text = page.read_text(encoding="utf-8")
    marker = AUTO_BEGIN.format(section="facts")
    edited = text.replace(marker, f"{line}\n\n{marker}", 1)
    assert edited != text, "the test did not actually edit the page"
    page.write_text(edited, encoding="utf-8", newline="")


def _remove_first_fact(page: Path) -> str:
    """Delete the first facts bullet from disk. Returns the removed line."""
    text = page.read_text(encoding="utf-8")
    begin = AUTO_BEGIN.format(section="facts")
    end = AUTO_END.format(section="facts")
    body = text.split(begin, 1)[1].split(end, 1)[0]
    bullet = body.strip().splitlines()[0]
    assert bullet.startswith("- "), bullet
    page.write_text(text.replace(f"{bullet}\n", "", 1), encoding="utf-8", newline="")
    return bullet


def _pending(conn, scope=OWNER):
    return MemoryStore(conn).list(scope=scope, status=("pending",))


def _linked_entity_ids(conn, memory_id):
    return [
        row["entity_id"]
        for row in conn.execute(
            "SELECT entity_id FROM memory_entities WHERE memory_id=?", (memory_id,)
        ).fetchall()
    ]


# --- the config key ----------------------------------------------------------


def test_ingest_is_a_typed_config_key_default_off():
    assert Config().vault.ingest_human_edits is False
    assert "vault.ingest_human_edits" in SCHEMA_KEYS
    fields = {f["key"]: f for f in config_schema_fields()}
    assert fields["vault.ingest_human_edits"]["kind"] == "bool"
    assert fields["vault.ingest_human_edits"]["default"] is False


def test_a_vault_edit_write_is_quarantined_not_live():
    """The card asks for a *pending* row; the store's only pending route is the
    write policy, so the policy must recognise the source."""
    from em_internal.policy import evaluate_write

    action, reason = evaluate_write("Acme Corp prefers Globex.", source="vault_edit")
    assert action == "quarantine", (action, reason)


# --- the ingestion itself ----------------------------------------------------


def test_a_human_region_bullet_becomes_a_pending_vault_edit(db, root):
    saved, _ = db
    with saved.writer() as conn:
        entity_id, _mid, page = _entity_page(conn, root)
        _insert_human_line(page, "- Acme Corp prefers Globex for streaming.")

        report = ingest(conn, root, scope=OWNER)

        rows = _pending(conn)
        assert len(rows) == 1, [r["content"] for r in rows]
        assert rows[0]["content"] == "Acme Corp prefers Globex for streaming."
        assert rows[0]["source"] == "vault_edit"
        assert rows[0]["status"] == "pending"
        assert report.added == [rows[0]["id"]]
        assert _linked_entity_ids(conn, rows[0]["id"]) == [entity_id]


def test_the_projection_regions_are_not_ingested(db, root):
    """The projection's own ``- fact ^m-…`` bullets are inside an auto-section,
    so re-ingesting them would turn every rendered fact into a duplicate."""
    saved, _ = db
    with saved.writer() as conn:
        _entity_page(conn, root)
        report = ingest(conn, root, scope=OWNER)
        assert report.added == []
        assert _pending(conn) == []


def test_ingesting_an_unchanged_page_twice_writes_nothing(db, root):
    saved, _ = db
    with saved.writer() as conn:
        _entity_page(conn, root)
        page = root / "Entities" / "Acme Corp.md"
        _insert_human_line(page, "- Acme Corp runs on Globex.")
        first = ingest(conn, root, scope=OWNER)
        assert len(first.added) == 1
        second = ingest(conn, root, scope=OWNER)
        assert second.added == []
        assert len(_pending(conn)) == 1


def test_a_removed_auto_section_line_is_recorded_as_a_review_hint(db, root):
    """The user deletes a fact bullet from the page. The projection would put it
    back, so ingestion leaves it alone and records a hint instead — naming the
    memory's own short id, so the user can forget it rather than fight."""
    saved, _ = db
    with saved.writer() as conn:
        _entity_id, mid, page = _entity_page(conn, root)
        # The first pass records the baseline: what the projection put on disk.
        ingest(conn, root, scope=OWNER)

        _remove_first_fact(page)
        report = ingest(conn, root, scope=OWNER)

    assert report.added == []
    assert len(report.hints) == 1, report.hints
    hint = report.hints[0]
    assert hint["memory_id"] == mid
    assert hint["ref"] == f"m-{short_id(mid)}"
    assert "forget?" in hint["text"]


def test_a_removed_line_is_not_a_hint_on_the_first_pass(db, root):
    """No baseline yet, so nothing can be called "removed" — the pass records
    what it sees and stays quiet."""
    saved, _ = db
    with saved.writer() as conn:
        _entity_id, _mid, page = _entity_page(conn, root)
        _remove_first_fact(page)
        report = ingest(conn, root, scope=OWNER)
    assert report.hints == []


def test_hints_are_readable_for_the_review_surface(db, root):
    saved, _ = db
    with saved.writer() as conn:
        _entity_id, mid, page = _entity_page(conn, root)
        ingest(conn, root, scope=OWNER)
        _remove_first_fact(page)
        ingest(conn, root, scope=OWNER)

        hints = read_hints(conn, OWNER)

    assert len(hints) == 1
    assert hints[0]["memory_id"] == mid
    assert set(hints[0]) >= {"ref", "memory_id", "text"}


def test_a_forgotten_memory_clears_its_hint(db, root):
    saved, _ = db
    with saved.writer() as conn:
        _entity_id, mid, page = _entity_page(conn, root)
        ingest(conn, root, scope=OWNER)
        _remove_first_fact(page)
        ingest(conn, root, scope=OWNER)
        assert len(read_hints(conn, OWNER)) == 1

        MemoryStore(conn).set_status(mid, "deleted", actor="tester", reason="forget")

        assert read_hints(conn, OWNER) == []


def test_a_gutted_page_is_skipped_not_guessed(db, root):
    """A page whose markers the user removed has no trustworthy human region, so
    ingestion skips it — the same rule the projection follows."""
    saved, _ = db
    with saved.writer() as conn:
        _entity_id, _mid, page = _entity_page(conn, root)
        text = page.read_text(encoding="utf-8")
        gutted = re.sub(
            r"(?m)^[ \t]*<!-- entropicmem:auto:(begin|end) id=[A-Za-z0-9_-]+ -->[ \t]*\r?\n",
            "",
            text,
        )
        assert "entropicmem:auto" not in gutted, "the test did not gut the page"
        close = gutted.index("\n---\n") + len("\n---\n")
        page.write_text(
            gutted[:close] + "\n- Acme Corp prefers Globex.\n" + gutted[close:],
            encoding="utf-8",
            newline="",
        )
        report = ingest(conn, root, scope=OWNER)
        assert report.added == []
        assert _pending(conn) == []


def test_an_entity_from_another_profile_is_not_ingested(db, root):
    saved, _ = db
    with saved.writer() as conn:
        store = EntityStore(conn)
        other = store.get_or_create_entity("Globex", scope=Scope(profile="other"))
        page = root / "Entities" / "Globex.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "---\n"
            f"entropic_entity: {other}\n"
            "name: Globex\n"
            "kind: thing\n"
            "aliases: []\n"
            "---\n"
            "\n"
            "- Globex hosts staging.\n"
            "\n"
            f"{AUTO_BEGIN.format(section='facts')}\n"
            f"{AUTO_END.format(section='facts')}\n",
            encoding="utf-8",
            newline="",
        )
        report = ingest(conn, root, scope=OWNER)
        assert report.added == []
        assert _pending(conn) == []


def test_a_crlf_page_ingests(db, root):
    saved, _ = db
    with saved.writer() as conn:
        _entity_id, _mid, page = _entity_page(conn, root)
        text = page.read_text(encoding="utf-8").replace("\n", "\r\n")
        marker = AUTO_BEGIN.format(section="facts")
        page.write_text(
            text.replace(marker, f"- Acme Corp runs on Globex.\r\n\r\n{marker}", 1),
            encoding="utf-8",
            newline="",
        )
        report = ingest(conn, root, scope=OWNER)
        assert len(report.added) == 1


def test_a_plain_dash_line_in_the_human_region_is_a_statement(db, root):
    """The card's grammar is ``- <statement>``; anything else in the human
    region (prose, headings, blank lines) is the user's, and untouched."""
    saved, _ = db
    with saved.writer() as conn:
        _entity_id, _mid, page = _entity_page(conn, root)
        text = page.read_text(encoding="utf-8")
        marker = AUTO_BEGIN.format(section="facts")
        edited = text.replace(
            marker,
            "## Notes\n\nA sentence that is not a bullet.\n\n- Acme Corp runs on Globex.\n\n"
            + marker,
            1,
        )
        page.write_text(edited, encoding="utf-8", newline="")
        report = ingest(conn, root, scope=OWNER)

    assert len(report.added) == 1
    with sqlite3.connect(db[1]) as check:
        content = check.execute(
            "SELECT content FROM memories WHERE id=?", (report.added[0],)
        ).fetchone()[0]
    assert content == "Acme Corp runs on Globex."


# --- the handler: off unless the payload asks --------------------------------


class _Ctx:
    def __init__(self, store):
        self.store = store

    def heartbeat(self):
        return True


class _Job:
    def __init__(self, payload):
        self.payload = payload
        self.id = "job_test"
        self.type = "project_vault"


def test_the_handler_ingests_only_when_the_payload_says_so(db, root):
    store, _ = db
    with store.transaction() as conn:
        _entity_page(conn, root)
    page = root / "Entities" / "Acme Corp.md"
    _insert_human_line(page, "- Acme Corp prefers Globex.")

    handler = make_project_vault_handler(str(root))
    base = {"root": str(root), "scope": {"profile": "default"}, "modes": ["entities"]}

    handler(_Job(dict(base)), _Ctx(store))
    with store.transaction() as conn:
        assert _pending(conn) == [], "the pass ingested with the flag off"

    handler(_Job({**base, "ingest": True}), _Ctx(store))
    with store.transaction() as conn:
        assert [r["source"] for r in _pending(conn)] == ["vault_edit"]


def test_the_enqueue_carries_the_ingest_flag_only_when_asked(db, root):
    """The handler reads its flag from the payload, so the *enqueue* is what
    actually turns ingestion on. Off is the default; on must be explicit, so a
    payload that silently lost the flag would leave the pass off forever."""
    store, _ = db
    with store.transaction() as conn:
        off_id = enqueue_projection(
            conn, root=root, scope=OWNER, modes=("entities",)
        )
        on_id = enqueue_projection(
            conn, root=f"{root}-on", scope=OWNER, modes=("entities", "journal"), ingest=True
        )
        payloads = {
            r["id"]: json.loads(r["payload"])
            for r in conn.execute(
                "SELECT id, payload FROM jobs WHERE type='project_vault'"
            ).fetchall()
        }

    assert "ingest" not in payloads[off_id]
    assert payloads[on_id].get("ingest") is True
