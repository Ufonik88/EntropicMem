"""EM-302 (first piece): `scope_sql`, the §3.5 rule as SQL.

Every candidate generator filters through this helper, so it is the one place the
retrieval layer can leak: get the owner-only clause wrong and a guest reads a
`sensitive` row, or the owner loses their own.

The tests deliberately **do not restate** the rule as a table of expectations.
`MemoryStore._in_scope` is the authoritative implementation of §3.5 (Chunk 7.2),
so the cross-check runs both forms over the same real rows and asserts they
select the same set. A hand-written table would only prove the two agree with my
memory; this proves they agree with each other.

Rules: invented data only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.retrieval.candidates import scope_sql  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.memories import MemoryStore, _in_scope  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

OWNER = Scope(profile="default")
GUEST = Scope(profile="default", user="alice")
SCOPED_OWNER = Scope(profile="default", user="alice", is_owner=True)
OTHER_USER = Scope(profile="default", user="bob")
OTHER_PROFILE = Scope(profile="other")

SCOPES = (OWNER, GUEST, SCOPED_OWNER, OTHER_USER, OTHER_PROFILE)


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as conn:
        migrate(conn)
    yield s
    s.close()


def seed(store) -> None:
    """One row for each (scope, tier) case the rule distinguishes.

    `secret` cannot be written through the policy, so a row is written as
    `sensitive` and restamped — the same technique the owner-only read tests use,
    and the only way to get the tier into the store at all.
    """
    cases = (
        (OWNER, "internal", "profile-wide, ordinary"),
        (OWNER, "sensitive", "profile-wide, sensitive"),
        (GUEST, "internal", "alice's own, ordinary"),
        (GUEST, "sensitive", "alice's own, sensitive"),
        (OTHER_PROFILE, "internal", "another profile, ordinary"),
        (OTHER_PROFILE, "sensitive", "another profile, sensitive"),
    )
    with store.transaction() as conn:
        mem = MemoryStore(conn)
        for scope, tier, body in cases:
            result = mem.add(
                MemoryDraft(content=body, sensitivity="internal"), scope=scope, actor="tester"
            )
            assert result.ok, result
            if tier != "internal":
                conn.execute(
                    "UPDATE memories SET sensitivity=? WHERE id=?", (tier, result.id)
                )
    # and one secret row, to cover the other owner-only tier
    with store.transaction() as conn:
        mem = MemoryStore(conn)
        result = mem.add(
            MemoryDraft(content="profile-wide, secret", sensitivity="internal"),
            scope=OWNER, actor="tester",
        )
        conn.execute("UPDATE memories SET sensitivity='secret' WHERE id=?", (result.id,))


def by_sql(store, scope) -> set:
    clause, params = scope_sql(scope)
    return {
        row["id"]
        for row in store.reader().execute(f"SELECT id FROM memories m WHERE {clause}", params)
    }


def by_predicate(store, scope) -> set:
    return {
        row["id"]
        for row in store.reader().execute("SELECT * FROM memories")
        if _in_scope(dict(row), scope)
    }


def test_sql_and_in_scope_select_the_same_rows(store):
    """The cross-check that makes drift between the two forms impossible."""
    seed(store)
    for scope in SCOPES:
        assert by_sql(store, scope) == by_predicate(store, scope), (
            f"scope_sql and _in_scope disagree for {scope!r}"
        )


def test_the_matrix_actually_discriminates(store):
    """Guard the guard: if every scope saw everything, the cross-check is vacuous."""
    seed(store)
    seen = [by_predicate(store, scope) for scope in SCOPES]
    assert len(seen[0]) > len(seen[1]), "a guest must see strictly fewer rows than the owner"
    assert len(seen[0]) > len(seen[3]), "and fewer than a different user"
    assert all(len(s) > 0 for s in seen), "every scope sees at least its own rows"


def test_the_owner_clause_is_excluded_for_the_owner_context(store):
    """A profile-wide or self-asserted owner gets no tier filter at all."""
    for scope in (OWNER, SCOPED_OWNER):
        clause, params = scope_sql(scope)
        assert "sensitivity" not in clause, clause
        assert params == [scope.profile, scope.user]


def test_the_owner_clause_is_emitted_for_a_guest(store):
    clause, params = scope_sql(GUEST)
    assert "sensitivity NOT IN (?, ?)" in clause, clause
    assert params == [GUEST.profile, GUEST.user, "sensitive", "secret"], params


def test_the_table_alias_is_configurable(store):
    aliased, _ = scope_sql(OWNER)
    bare, _ = scope_sql(OWNER, table="")
    assert aliased.startswith("m."), aliased
    assert not bare.startswith("m."), bare
    assert bare.startswith("scope_profile"), bare


def test_sensitivity_is_not_null_so_the_guest_clause_needs_no_null_escape(store):
    """The guest clause uses `NOT IN (...)`; a NULL would evaluate to unknown.

    The schema makes that impossible. This pins the assumption rather than
    leaving an untestable `IS NULL` branch in the SQL: if a future migration
    relaxes the column, this fails here instead of the retrieval layer silently
    hiding (or worse, showing) a row of unknown tier.
    """
    info = store.reader().execute(
        "SELECT name, \"notnull\" FROM pragma_table_info('memories') WHERE name='sensitivity'"
    ).fetchone()
    assert info is not None, "the memories schema changed shape"
    assert info["notnull"] == 1, "sensitivity became nullable; revisit scope_sql"
    clause, _ = scope_sql(GUEST)
    assert "IS NULL" not in clause
