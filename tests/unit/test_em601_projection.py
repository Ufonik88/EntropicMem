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


# --- month paging (chunk 48 — the card's deferred "paged by month if > 200") ---

UNFILED_PAGE = Path("Memories") / "Unfiled.md"


def _remember_in_month(conn, content, month):
    """Remember, then place the row in ``month`` (``YYYY-MM``) deterministically.

    The projection buckets a row by its ``updated_at``'s first seven
    characters, so the test pins the stamp directly rather than trying to make
    the clock say September.
    """
    mid = _remember(conn, content)
    conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (f"{month}-15T12:00:00Z", mid))
    return mid


def _unfiled_rows(text, section="unfiled"):
    """The bullet lines of one auto-section."""
    return [
        line
        for line in _section(text, section).splitlines()
        if line.startswith("- ")
    ]


def test_unfiled_paging_activates_past_200_and_pages_completed_months(db, root):
    """Past 200 rows the newest month stays on Unfiled.md; older months page out."""
    saved, _path = db
    with saved.writer() as conn:
        for i in range(150):
            _remember_in_month(conn, f"September fact {i} for the fern.", "2026-09")
        for i in range(60):
            _remember_in_month(conn, f"October fact {i} for Acme.", "2026-10")
        _project(conn, root, modes=("unfiled",))
        unfiled = (root / "Memories" / "Unfiled.md").read_text(encoding="utf-8")
        archive = (root / "Memories" / "Unfiled-2026-09.md").read_text(encoding="utf-8")

    here = _unfiled_rows(unfiled)
    old = _unfiled_rows(archive, section="unfiled-2026-09")
    assert len(here) == 60, here
    assert all("October fact" in line for line in here)
    assert not any("September" in line for line in here)
    assert len(old) == 150, len(old)
    assert all("September fact" in line for line in old)
    # Every row renders exactly once across the pages — a row lost or shown
    # twice is a projection that cannot be trusted as the human view.
    assert len(here) + len(old) == 210


def test_unfiled_paging_stays_off_at_the_limit(db, root):
    """Exactly 200 rows: one page, no archive files (the boundary)."""
    saved, _path = db
    with saved.writer() as conn:
        for i in range(200):
            _remember_in_month(conn, f"September fact {i}.", "2026-09")
        _project(conn, root, modes=("unfiled",))
        text = (root / "Memories" / "Unfiled.md").read_text(encoding="utf-8")
        strays = list((root / "Memories").glob("Unfiled-*.md"))

    assert len(_unfiled_rows(text)) == 200
    assert strays == [], strays


def test_paging_stays_off_at_the_limit_across_two_months(db, root):
    """200 rows in two months still make one page.

    The single-month boundary above is invariant to the limit — no month
    boundary exists to split on — so this is where a lowered limit (paging on
    whenever any rows exist) actually shows.
    """
    saved, _path = db
    with saved.writer() as conn:
        for i in range(120):
            _remember_in_month(conn, f"September fact {i}.", "2026-09")
        for i in range(80):
            _remember_in_month(conn, f"October fact {i}.", "2026-10")
        _project(conn, root, modes=("unfiled",))
        text = (root / "Memories" / "Unfiled.md").read_text(encoding="utf-8")
        strays = list((root / "Memories").glob("Unfiled-*.md"))

    assert len(_unfiled_rows(text)) == 200
    assert strays == [], strays


def test_a_single_month_never_splits_even_past_the_limit(db, root):
    """205 rows in one month stay whole: the spec's letter is 'paged by month'."""
    saved, _path = db
    with saved.writer() as conn:
        for i in range(205):
            _remember_in_month(conn, f"September fact {i}.", "2026-09")
        _project(conn, root, modes=("unfiled",))
        text = (root / "Memories" / "Unfiled.md").read_text(encoding="utf-8")
        strays = list((root / "Memories").glob("Unfiled-*.md"))

    assert len(_unfiled_rows(text)) == 205
    assert strays == [], strays


def test_a_forgotten_memory_leaves_its_month_archive_page(db, root):
    """The erasure rule reaches the archive pages: forget clears its line there."""
    saved, _path = db
    with saved.writer() as conn:
        ids = [
            _remember_in_month(conn, f"September fact {i}.", "2026-09") for i in range(200)
        ]
        _remember_in_month(conn, "The fern prefers morning light.", "2026-10")
        _remember_in_month(conn, "A second October row for Acme.", "2026-10")
        _project(conn, root, modes=("unfiled",))
        archive = root / "Memories" / "Unfiled-2026-09.md"
        assert "September fact 7." in archive.read_text(encoding="utf-8")

        _forget(conn, ids[7])
        _project(conn, root, modes=("unfiled",))
        text = archive.read_text(encoding="utf-8")
        unfiled = (root / "Memories" / "Unfiled.md").read_text(encoding="utf-8")

    assert "September fact 7." not in text
    assert len(_unfiled_rows(text, section="unfiled-2026-09")) == 199
    # And the working page is untouched by the archive's update.
    assert len(_unfiled_rows(unfiled)) == 2


def test_paging_deactivates_when_the_set_falls_back_to_the_limit(db, root):
    """Back at or under 200 every row returns to Unfiled.md; the archive empties."""
    saved, _path = db
    with saved.writer() as conn:
        for i in range(150):
            _remember_in_month(conn, f"September fact {i}.", "2026-09")
        oct_ids = [
            _remember_in_month(conn, f"October fact {i}.", "2026-10") for i in range(60)
        ]
        _project(conn, root, modes=("unfiled",))
        archive = root / "Memories" / "Unfiled-2026-09.md"
        assert archive.exists()

        for mid in oct_ids:
            _forget(conn, mid)
        _project(conn, root, modes=("unfiled",))
        text = (root / "Memories" / "Unfiled.md").read_text(encoding="utf-8")
        archive_text = archive.read_text(encoding="utf-8")

    assert len(_unfiled_rows(text)) == 150
    assert "September fact" in text
    # The emptied archive page is kept, not deleted — the projection never
    # deletes a file; it rewrites its own sections down to what remains.
    assert archive.exists()
    assert _unfiled_rows(archive_text, section="unfiled-2026-09") == []


def test_a_hand_edit_on_a_month_page_survives(db, root):
    """The card's core rule, on the new page kind: the human region is the user's."""
    saved, _path = db
    with saved.writer() as conn:
        for i in range(150):
            _remember_in_month(conn, f"September fact {i}.", "2026-09")
        for i in range(60):
            _remember_in_month(conn, f"October fact {i}.", "2026-10")
        _project(conn, root, modes=("unfiled",))
        archive = root / "Memories" / "Unfiled-2026-09.md"
        original = archive.read_text(encoding="utf-8")
        assert "My own note about September." not in original
        at = original.index(AUTO_BEGIN.format(section="unfiled-2026-09"))
        archive.write_text(
            original[:at] + "My own note about September.\n\n" + original[at:],
            encoding="utf-8",
        )
        for _ in range(10):
            _project(conn, root, modes=("unfiled",))
        after = archive.read_text(encoding="utf-8")

    assert after.count("My own note about September.") == 1
    assert len(_unfiled_rows(after, section="unfiled-2026-09")) == 150


def test_paging_is_idempotent(db, root):
    """A second run over a paged vault writes nothing."""
    saved, _path = db
    with saved.writer() as conn:
        for i in range(150):
            _remember_in_month(conn, f"September fact {i}.", "2026-09")
        for i in range(60):
            _remember_in_month(conn, f"October fact {i}.", "2026-10")
        _project(conn, root, modes=("unfiled",))
        pages = [root / "Memories" / "Unfiled.md", root / "Memories" / "Unfiled-2026-09.md"]
        stamps = [page.stat().st_mtime_ns for page in pages]
        second = _project(conn, root, modes=("unfiled",))

    assert second.written == [], second.written
    assert [page.stat().st_mtime_ns for page in pages] == stamps


def test_lint_covers_month_pages(db, root):
    """A gutted archive page is reported, not silently skipped."""
    saved, _path = db
    with saved.writer() as conn:
        for i in range(150):
            _remember_in_month(conn, f"September fact {i}.", "2026-09")
        for i in range(60):
            _remember_in_month(conn, f"October fact {i}.", "2026-10")
        _project(conn, root, modes=("unfiled",))
        archive = root / "Memories" / "Unfiled-2026-09.md"
        text = archive.read_text(encoding="utf-8")
        gutted = "\n".join(
            line for line in text.splitlines() if "entropicmem:auto:" not in line
        )
        archive.write_text(gutted, encoding="utf-8")
        problems = lint(root)

    assert [(problem.path, problem.problem) for problem in problems] == [
        (Path("Memories") / "Unfiled-2026-09.md", "missing_markers")
    ]


def test_the_month_page_frontmatter_carries_the_month(db, root):
    """Written once at creation, like every other page kind's frontmatter."""
    saved, _path = db
    with saved.writer() as conn:
        for i in range(150):
            _remember_in_month(conn, f"September fact {i}.", "2026-09")
        for i in range(60):
            _remember_in_month(conn, f"October fact {i}.", "2026-10")
        _project(conn, root, modes=("unfiled",))
        archive = root / "Memories" / "Unfiled-2026-09.md"
        text = archive.read_text(encoding="utf-8")
        # A second run must not rewrite it (merge preserves the frontmatter).
        _project(conn, root, modes=("unfiled",))
        again = archive.read_text(encoding="utf-8")

    assert text.startswith("---\nentropic_vault: unfiled\nmonth: 2026-09\n---\n")
    assert again == text


def test_a_stale_archive_page_for_the_newest_month_does_not_double_render(db, root):
    """A month that becomes the newest again moves back to Unfiled.md once.

    The archive page left over from when the month was not the newest must
    empty out, or its rows would render on two pages at once.
    """
    saved, _path = db
    with saved.writer() as conn:
        for i in range(210):
            _remember_in_month(conn, f"September fact {i}.", "2026-09")
        only_october = _remember_in_month(conn, "The fern prefers morning light.", "2026-10")
        _project(conn, root, modes=("unfiled",))
        archive = root / "Memories" / "Unfiled-2026-09.md"
        assert len(_unfiled_rows(archive.read_text(encoding="utf-8"), section="unfiled-2026-09")) == 210

        _forget(conn, only_october)
        _project(conn, root, modes=("unfiled",))
        unfiled = (root / "Memories" / "Unfiled.md").read_text(encoding="utf-8")
        archive_text = archive.read_text(encoding="utf-8")

    assert len(_unfiled_rows(unfiled)) == 210
    assert _unfiled_rows(archive_text, section="unfiled-2026-09") == []
