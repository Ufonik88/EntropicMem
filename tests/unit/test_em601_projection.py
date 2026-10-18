"""EM-601 slice 1 — the vault projection engine (S6).

The card (``REMAINING_PLAN.md`` §6.5) makes the vault *a projection of memory*,
not a note-per-fact dump: the store is the source of truth, the Markdown files
are a rendering of it, and the user owns everything outside the auto-sections.

Rules these tests pin:

* **Only auto-sections are rewritten.** The frontmatter and the human region
  are byte-preserved across runs, so a hand edit survives any number of
  projections (the card's AC: ten runs).
* **Idempotent** — a second projection with an unchanged store writes nothing
  and moves no mtime.
* **`forget` clears every line the memory put there**: its bullet from the
  facts section, and the relation it sourced.
* **A file whose markers were deleted is left untouched and reported by
  `lint`**, never recreated over the user's prose.
* **Sensitive and secret rows never reach the vault** — the files are
  plaintext, so §3.5's owner-only tiers are excluded outright rather than
  gated by scope (a deliberate strengthening, recorded in the CHANGELOG).
* **A caller's scope bounds what it sees** (§3.5 / F-004): another user's rows
  never reach this scope's projection.

Invented data only: Acme, Globex, Alice and Bob Example.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import new_id, short_id, to_iso, utc_now  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.entities import EntityStore  # noqa: E402
from em.store.episodes import EpisodeStore  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402
from em.vault.projection import (  # noqa: E402
    AUTO_BEGIN,
    AUTO_END,
    LintProblem,
    ProjectionReport,
    lint,
    project,
)

OWNER = Scope(profile="default")
ALICE = Scope(profile="default", user="alice")
BOB = Scope(profile="default", user="bob")


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


def _remember(conn, content, *, scope=OWNER, sensitivity="internal"):
    result = MemoryStore(conn).add(
        MemoryDraft(content=content, sensitivity=sensitivity),
        scope=scope,
        actor="tester",
    )
    assert result.ok, result
    return result.id


def _link_to(conn, memory_id, entity_name, *, scope=OWNER):
    """Ensure one entity exists and this memory is linked to it.

    Uses the real linker path: ``get_or_create_entity`` registers the alias and
    ``link`` then resolves the phrase in the memory's own text back to it, so
    the test seeds through production code rather than raw SQL.
    """
    store = EntityStore(conn)
    store.get_or_create_entity(entity_name, scope=scope)
    content = conn.execute("SELECT content FROM memories WHERE id=?", (memory_id,)).fetchone()[
        "content"
    ]
    linked = store.link(memory_id, content, scope=scope)
    assert linked, f"{memory_id} did not link to {entity_name!r}"
    return linked


def _forget(conn, memory_id, reason="forget"):
    result = MemoryStore(conn).set_status(memory_id, "deleted", actor="tester", reason=reason)
    assert result.ok, result
    return result


def _seed_secret(conn, content, *, scope=OWNER):
    """Insert a ``secret`` row the way the v2→v3 migration makes one.

    ``MemoryStore.add`` can never produce this tier: ``evaluate_write`` blocks
    every ``secret`` write outright ("store secrets in a secrets manager"). The
    rows that do exist are migrated v2 facts — precisely the case a projection
    has to catch, since they arrive already stamped.
    """
    row_id = new_id("mem")
    now = to_iso(utc_now())
    conn.execute(
        "INSERT INTO memories (id, scope_profile, scope_user, scope_chat, content, content_hash,"
        " sensitivity, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (row_id, scope.profile, scope.user, scope.chat, content, f"hash-{row_id}", "secret",
         "migration", now, now),
    )
    return row_id


def _project(conn, root, *, scope=OWNER, modes=("entities", "journal", "unfiled")):
    return project(conn, root, scope=scope, modes=modes)


def _section(text, section):
    """The body between one auto-section's markers (markers included nowhere)."""
    body = text.split(AUTO_BEGIN.format(section=section), 1)[1]
    return body.split(AUTO_END.format(section=section), 1)[0]


# --- entity pages ---------------------------------------------------------


def test_an_entity_page_is_written_with_frontmatter_and_three_sections(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, mid, "Acme Corp")
        report = _project(conn, root)

    page = root / "Entities" / "Acme Corp.md"
    assert page.is_file(), report
    text = page.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "entropic_entity: ent_" in text
    assert "kind: thing" in text
    assert "aliases:" in text
    for section in ("facts", "history", "relations"):
        assert AUTO_BEGIN.format(section=section) in text
        assert AUTO_END.format(section=section) in text
    assert report.written == [page.relative_to(root)]


def test_the_facts_section_lists_active_memories_with_block_refs(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, mid, "Acme Corp")
        _project(conn, root)

    body = _section(
        (root / "Entities" / "Acme Corp.md").read_text(encoding="utf-8"), "facts"
    )
    assert "Acme Corp uses Globex for hosting." in body
    assert f"^m-{short_id(mid)}" in body


def test_a_multiline_memory_renders_as_one_bullet_line(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex.\nSecond line here.")
        _link_to(conn, mid, "Acme Corp")
        _project(conn, root)

    body = _section(
        (root / "Entities" / "Acme Corp.md").read_text(encoding="utf-8"), "facts"
    )
    bullet = [line for line in body.splitlines() if line.startswith("- ")][0]
    assert "Second line here." in bullet
    assert "Second line here.\n" not in body


def test_superseded_memories_land_in_the_history_section_capped_at_ten(db, root):
    saved, _path = db
    with saved.writer() as conn:
        store = MemoryStore(conn)
        current = _remember(conn, "Acme Corp hosts on Globex v1.")
        _link_to(conn, current, "Acme Corp")
        for version in range(2, 14):
            result = store.supersede(
                current,
                MemoryDraft(content=f"Acme Corp hosts on Globex v{version}."),
                scope=OWNER,
                actor="tester",
                reason="update",
            )
            assert result.ok, result
            _link_to(conn, result.id, "Acme Corp")
            current = result.id
        _project(conn, root)

    text = (root / "Entities" / "Acme Corp.md").read_text(encoding="utf-8")
    history = [line for line in _section(text, "history").splitlines() if line.startswith("- ")]
    facts = [line for line in _section(text, "facts").splitlines() if line.startswith("- ")]
    assert len(history) == 10, history
    assert len(facts) == 1, facts


def test_open_relations_render_as_wikilinks_to_the_object_entity(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp contracts with Globex.")
        _link_to(conn, mid, "Acme Corp")
        entities = EntityStore(conn)
        globex = entities.get_or_create_entity("Globex", scope=OWNER)
        entities.add_relation(
            scope=OWNER,
            subject_id=entities.find_entity("Acme Corp"),
            predicate="contracts_with",
            object_id=globex,
        )
        _project(conn, root)

    body = _section(
        (root / "Entities" / "Acme Corp.md").read_text(encoding="utf-8"), "relations"
    )
    assert "[[Globex]]" in body
    assert "contracts_with" in body


def test_a_literal_relation_renders_as_plain_text(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp moved to Initech Park.")
        _link_to(conn, mid, "Acme Corp")
        entities = EntityStore(conn)
        entities.add_relation(
            scope=OWNER,
            subject_id=entities.find_entity("Acme Corp"),
            predicate="located_in",
            object_literal="Initech Park",
        )
        _project(conn, root)

    body = _section(
        (root / "Entities" / "Acme Corp.md").read_text(encoding="utf-8"), "relations"
    )
    assert "Initech Park" in body
    assert "[[Initech Park" not in body


# --- idempotence and hand edits -------------------------------------------


def test_a_second_projection_writes_nothing(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, mid, "Acme Corp")
        _project(conn, root)
        page = root / "Entities" / "Acme Corp.md"
        before = page.stat()
        report = _project(conn, root)

    after = page.stat()
    assert report.written == [], report.written
    assert report.unchanged == [page.relative_to(root)]
    assert after.st_mtime_ns == before.st_mtime_ns


def test_a_hand_edit_outside_the_markers_survives_ten_projections(db, root):
    """The card's AC, in full: ten runs must not disturb the human region."""
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, mid, "Acme Corp")
        _project(conn, root)
        page = root / "Entities" / "Acme Corp.md"
        original = page.read_text(encoding="utf-8")
        assert "My own notes about Acme." not in original
        # The human region is everything after the frontmatter and before the
        # first marker: exactly where the user's own prose belongs.
        at = original.index(AUTO_BEGIN.format(section="facts"))
        page.write_text(
            original[:at] + "My own notes about Acme.\n\n" + original[at:], encoding="utf-8"
        )
        # And a note after the last marker: the suffix must survive too, or
        # "only auto-sections are rewritten" is only half true.
        with page.open("a", encoding="utf-8", newline="") as handle:
            handle.write("\nA closing thought about Acme.\n")
        for _ in range(10):
            report = _project(conn, root)
        after = page.read_text(encoding="utf-8")

    assert after.count("My own notes about Acme.") == 1
    assert after.count("A closing thought about Acme.") == 1
    # And the auto section still tracks the store rather than freezing.
    assert "Acme Corp uses Globex for hosting." in _section(after, "facts")
    assert report.written == [], report.written


def test_forget_removes_the_line_from_the_entity_page(db, root):
    saved, _path = db
    with saved.writer() as conn:
        forgotten = _remember(conn, "Acme Corp uses Globex for hosting.")
        kept = _remember(conn, "Acme Corp ships widgets.")
        _link_to(conn, forgotten, "Acme Corp")
        _link_to(conn, kept, "Acme Corp")
        _project(conn, root)
        _forget(conn, forgotten)
        report = _project(conn, root)
        text = (root / "Entities" / "Acme Corp.md").read_text(encoding="utf-8")

    body = _section(text, "facts")
    assert "Globex for hosting" not in body
    assert "Acme Corp ships widgets." in body
    assert report.written == [Path("Entities") / "Acme Corp.md"]


def test_forget_clears_the_relation_that_memory_put_there(db, root):
    saved, _path = db
    with saved.writer() as conn:
        base = _remember(conn, "Acme Corp ships widgets.")
        _link_to(conn, base, "Acme Corp")
        source = _remember(conn, "Acme Corp contracts with Globex.")
        _link_to(conn, source, "Acme Corp")
        entities = EntityStore(conn)
        globex = entities.get_or_create_entity("Globex", scope=OWNER)
        entities.add_relation(
            scope=OWNER,
            subject_id=entities.find_entity("Acme Corp"),
            predicate="contracts_with",
            object_id=globex,
            memory_id=source,
        )
        _project(conn, root)
        before = _section(
            (root / "Entities" / "Acme Corp.md").read_text(encoding="utf-8"), "relations"
        )
        assert "contracts_with" in before

        _forget(conn, source)
        _project(conn, root)
        after = _section(
            (root / "Entities" / "Acme Corp.md").read_text(encoding="utf-8"), "relations"
        )

    assert "contracts_with" not in after


def test_an_entity_whose_rows_are_all_forgotten_has_its_page_erased(db, root):
    """Forgetting must not leave the old page standing with the old line."""
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp hosts its rack in Initech Park.")
        _link_to(conn, mid, "Acme Corp")
        _project(conn, root)
        page = root / "Entities" / "Acme Corp.md"
        assert "Initech Park" in page.read_text(encoding="utf-8")

        _forget(conn, mid)
        report = _project(conn, root)
        text = page.read_text(encoding="utf-8")

    assert "Initech Park" not in text
    assert report.written == [Path("Entities") / "Acme Corp.md"]


# --- lint -----------------------------------------------------------------


def test_a_file_whose_markers_were_deleted_is_left_untouched_and_reported(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, mid, "Acme Corp")
        _project(conn, root)
        page = root / "Entities" / "Acme Corp.md"
        stripped = "\n".join(
            line
            for line in page.read_text(encoding="utf-8").splitlines()
            if "entropicmem:auto" not in line
        )
        page.write_text(stripped + "\nMy replacement text.\n", encoding="utf-8")
        before = page.read_text(encoding="utf-8")
        report = _project(conn, root)
        after = page.read_text(encoding="utf-8")
        problems = lint(root)

    assert after == before, "the projection must not recreate a file the user gutted"
    assert report.missing_markers == [Path("Entities") / "Acme Corp.md"]
    assert [p.problem for p in problems] == ["missing_markers"], problems
    assert all(isinstance(p, LintProblem) for p in problems)


def test_lint_reports_a_page_whose_begin_marker_has_no_end(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, mid, "Acme Corp")
        _project(conn, root)
        page = root / "Entities" / "Acme Corp.md"
        page.write_text(
            page.read_text(encoding="utf-8").replace(AUTO_END.format(section="facts"), ""),
            encoding="utf-8",
        )
        problems = lint(root)

    assert problems, "an unbalanced marker is exactly what lint exists for"
    assert [p.problem for p in problems] == ["unbalanced_markers"]
    assert problems[0].path == Path("Entities") / "Acme Corp.md"


def test_lint_is_quiet_on_a_healthy_vault(db, root):
    saved, _path = db
    with saved.writer() as conn:
        _remember(conn, "The fern prefers morning light.")
        _project(conn, root)
        assert lint(root) == []


def test_lint_says_nothing_about_a_directory_it_was_not_given(db, root):
    assert lint(root) == []
    assert lint(root / "nope") == []


def test_the_projection_never_escapes_the_vault_root(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, mid, "Acme Corp")
        _project(conn, root)

    files = list(root.rglob("*.md"))
    assert files, "the projection wrote nothing"
    for path in files:
        assert root.resolve() in path.resolve().parents


# --- journal and unfiled --------------------------------------------------


def test_the_journal_page_lists_that_days_episodes_with_decisions(db, root):
    saved, _path = db
    with saved.writer() as conn:
        EpisodeStore(conn).add_episode(
            scope=OWNER,
            kind="manual",
            title="Acme quarterly sync",
            summary="Reviewed the Globex migration.",
            decisions=["Move the last rack on Friday."],
            open_loops=["Confirm the Globex window."],
        )
        _project(conn, root)
        pages = sorted((root / "Journal").glob("*.md"))

    assert len(pages) == 1, pages
    text = pages[0].read_text(encoding="utf-8")
    assert "Acme quarterly sync" in text
    assert "Move the last rack on Friday." in text
    assert "Confirm the Globex window." in text
    assert "entropic_vault: journal" in text


def test_a_journals_day_page_is_emptied_once_its_episodes_are_gone(db, root):
    saved, _path = db
    with saved.writer() as conn:
        episode_id = EpisodeStore(conn).add_episode(
            scope=OWNER,
            kind="manual",
            title="Acme quarterly sync",
            summary="Reviewed the Globex migration.",
        )
        _project(conn, root)
        page = next((root / "Journal").glob("*.md"))
        assert "Acme quarterly sync" in page.read_text(encoding="utf-8")

        conn.execute("DELETE FROM episodes WHERE id=?", (episode_id,))
        _project(conn, root)
        text = page.read_text(encoding="utf-8")

    assert "Acme quarterly sync" not in text
    assert AUTO_BEGIN.format(section="episodes") in text


def test_unfiled_lists_active_memories_with_no_entity_link(db, root):
    saved, _path = db
    with saved.writer() as conn:
        linked = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, linked, "Acme Corp")
        _remember(conn, "The fern prefers morning light.")
        _project(conn, root)
        text = (root / "Memories" / "Unfiled.md").read_text(encoding="utf-8")

    assert "The fern prefers morning light." in text
    assert "Acme Corp uses Globex for hosting." not in text


def test_the_unfiled_page_is_emptied_once_every_line_is_forgotten(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "The fern prefers morning light.")
        _project(conn, root)
        page = root / "Memories" / "Unfiled.md"
        assert "The fern" in page.read_text(encoding="utf-8")

        _forget(conn, mid)
        report = _project(conn, root)
        text = page.read_text(encoding="utf-8")

    assert "The fern" not in text
    assert report.written == [Path("Memories") / "Unfiled.md"]


# --- privacy and scope ----------------------------------------------------


def test_a_secret_memory_never_reaches_the_vault(db, root):
    """The tiers are withheld even from the owner's own projection."""
    saved, _path = db
    with saved.writer() as conn:
        linked_secret = _seed_secret(conn, "Acme Corp merger terms stay sealed until Friday.")
        _link_to(conn, linked_secret, "Acme Corp")
        _link_to(conn, _remember(conn, "Acme Corp ships widgets."), "Acme Corp")
        _seed_secret(conn, "The quarterly bonus figures are not shared widely.")
        _remember(conn, "The fern prefers morning light.")
        # Both rows must be live and only *secret* — otherwise the status
        # filter, not the tier bar, would be doing this test's work for it.
        rows = conn.execute(
            "SELECT content, status, sensitivity FROM memories WHERE sensitivity='secret'"
        ).fetchall()
        assert len(rows) == 2, rows
        assert {row["status"] for row in rows} == {"active"}, rows

        _project(conn, root)
        entity_page = (root / "Entities" / "Acme Corp.md").read_text(encoding="utf-8")
        unfiled = (root / "Memories" / "Unfiled.md").read_text(encoding="utf-8")

    # The page exists *because* of the internal row — so this proves the
    # secret row was filtered out of a page that was written anyway.
    assert "Acme Corp ships widgets." in entity_page
    assert "The fern prefers morning light." in unfiled
    for page in root.rglob("*.md"):
        text = page.read_text(encoding="utf-8")
        assert "merger terms stay sealed" not in text, page
        assert "bonus figures are not shared" not in text, page


def test_a_sensitive_memory_never_reaches_the_vault(db, root):
    saved, _path = db
    with saved.writer() as conn:
        _link_to(
            conn,
            _remember(conn, "Acme Corp renegotiates salaries.", sensitivity="sensitive"),
            "Acme Corp",
        )
        _link_to(conn, _remember(conn, "Acme Corp ships widgets."), "Acme Corp")
        row = conn.execute(
            "SELECT status FROM memories WHERE content='Acme Corp renegotiates salaries.'"
        ).fetchone()
        assert row["status"] == "active", row
        _project(conn, root)
        body = _section(
            (root / "Entities" / "Acme Corp.md").read_text(encoding="utf-8"), "facts"
        )

    assert "Acme Corp ships widgets." in body
    assert "renegotiates salaries" not in body
    for page in root.rglob("*.md"):
        assert "renegotiates salaries" not in page.read_text(encoding="utf-8"), page


def test_a_user_scope_sees_only_its_own_rows(db, root):
    saved, _path = db
    with saved.writer() as conn:
        _remember(conn, "Alice Example prefers decaf.", scope=ALICE)
        _remember(conn, "Bob Example prefers tea.", scope=BOB)
        _project(conn, root, scope=ALICE)
        text = (root / "Memories" / "Unfiled.md").read_text(encoding="utf-8")

    assert "Alice Example prefers decaf." in text
    assert "Bob Example prefers tea." not in text


def test_a_profile_scope_does_not_render_a_users_scoped_rows(db, root):
    saved, _path = db
    with saved.writer() as conn:
        _remember(conn, "Alice Example prefers decaf.", scope=ALICE)
        _remember(conn, "The fern prefers morning light.")
        _project(conn, root, scope=OWNER)
        text = (root / "Memories" / "Unfiled.md").read_text(encoding="utf-8")

    assert "Alice Example prefers decaf." not in text
    assert "The fern prefers morning light." in text


# --- modes, reporting and collisions --------------------------------------


def test_mode_none_writes_nothing(db, root):
    saved, _path = db
    with saved.writer() as conn:
        _remember(conn, "Acme Corp uses Globex for hosting.")
        report = _project(conn, root, modes=())

    assert report.written == []
    assert not root.exists()


def test_an_unknown_mode_is_refused_rather_than_rendering_nothing(db, root):
    saved, _path = db
    with saved.writer() as conn:
        with pytest.raises(ValueError, match="unknown projection mode"):
            _project(conn, root, modes=("entities", "legacy"))
    assert not root.exists()


def test_the_report_counts_what_it_did(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, mid, "Acme Corp")
        _remember(conn, "The fern prefers morning light.")
        report = _project(conn, root)

    assert isinstance(report, ProjectionReport)
    assert report.pages_written == 2
    assert sorted(report.written) == [
        Path("Entities") / "Acme Corp.md",
        Path("Memories") / "Unfiled.md",
    ]


def test_two_entities_sanitising_to_one_name_get_distinct_files(db, root):
    """`Acme/Corp` and `Acme Corp` are one filename after sanitisation.

    Seeded directly, because the linker resolves both spellings to one alias
    and would never create the second entity — the collision is a *filename*
    fact, not a linking one.
    """
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp ships widgets.")
        now = to_iso(utc_now())
        for name in ("Acme Corp", "Acme/Corp"):
            entity_id = new_id("ent")
            conn.execute(
                "INSERT INTO entities (id, scope_profile, name, kind, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?)",
                (entity_id, OWNER.profile, name, "thing", now, now),
            )
            conn.execute(
                "INSERT INTO memory_entities (memory_id, entity_id, role) VALUES (?,?,?)",
                (mid, entity_id, "mention"),
            )
        report = _project(conn, root)
        pages = sorted(p.name for p in (root / "Entities").glob("*.md"))

    assert len(pages) == 2, pages
    assert len(report.written) == 2


def test_an_entity_with_no_active_memory_gets_no_page(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, mid, "Acme Corp")
        _forget(conn, mid)
        _project(conn, root)

    assert list((root / "Entities").glob("*.md")) == []


def test_writes_leave_no_temp_files_behind(db, root):
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, mid, "Acme Corp")
        _project(conn, root)
        _forget(conn, mid)
        _project(conn, root)

    strays = [p for p in root.rglob("*") if p.is_file() and p.suffix != ".md"]
    assert strays == [], strays


def test_a_crlf_vault_stays_crlf_after_a_projection(db, root):
    """Windows invariant: a CRLF vault must not come back half-LF.

    Raw ``open(newline="")`` both ways: ``Path.read_text`` is universal-newline
    and would hand the test an already-translated string, so it could not see
    what the projection actually left on disk.
    """
    saved, _path = db
    with saved.writer() as conn:
        mid = _remember(conn, "Acme Corp uses Globex for hosting.")
        _link_to(conn, mid, "Acme Corp")
        _project(conn, root)
        page = root / "Entities" / "Acme Corp.md"
        with page.open("r", encoding="utf-8", newline="") as handle:
            lf_text = handle.read()
        with page.open("w", encoding="utf-8", newline="") as handle:
            handle.write(lf_text.replace("\n", "\r\n"))
        other = _remember(conn, "Acme Corp ships widgets.")
        _link_to(conn, other, "Acme Corp")
        _project(conn, root)
        with page.open("r", encoding="utf-8", newline="") as handle:
            text = handle.read()

    assert "Acme Corp ships widgets." in text
    assert "\r\n" in text
    assert "\n" not in text.replace("\r\n", "")
