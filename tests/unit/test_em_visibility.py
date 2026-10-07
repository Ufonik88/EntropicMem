"""Chunk 13 — §3.5's `visibility` half: the write stamp and the read guard.

Two halves, and the *direction* is the point. The store used to stamp **every**
write `visibility='user'` (the `MemoryDraft` default, which nothing overrode),
so a profile-wide row carried a stamp §3.5 pairs with a *user-scoped* write. §3.5
makes exactly that combination owner-only — so implementing the read clause alone
would have hidden every profile-wide memory from non-owners, the opposite of what
§3.5 intends. The write stamp is the real fix; the read guard is the defence for
rows that already exist or that a caller deliberately stamps.

**The regression guard is the test that matters:** a non-owner must still see an
ordinary profile-wide memory. Everything else is a consequence.

Invented data only (rule 4): Acme / Globex / Initech, Alice / Bob Example.
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
from em.store.migrations import LATEST, discover, migrate  # noqa: E402
from em.store.types import (  # noqa: E402
    MemoryDraft,
    Scope,
    row_is_owner_only,
)

OWNER = Scope(profile="default")
ALICE = Scope(profile="default", user="alice")
BOB = Scope(profile="default", user="bob")
SCOPED_OWNER = Scope(profile="default", user="alice", is_owner=True)
OTHER_PROFILE = Scope(profile="other")


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as conn:
        migrate(conn)
    yield s
    s.close()


def remember(store, content, *, scope=OWNER, **kw) -> str:
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(content=content, **kw), scope=scope, actor="tester"
        )
    assert result.ok, result
    return result.id


def row(store, memory_id: str) -> dict:
    return dict(store.reader().execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone())


def visibility_of(store, memory_id: str) -> str:
    return row(store, memory_id)["visibility"]


def outbox_rows(store, memory_id: str) -> int:
    return store.reader().execute(
        "SELECT COUNT(*) FROM sync_outbox WHERE fact_id=?", (memory_id,)
    ).fetchone()[0]


def visible_by_id(store, scope) -> set:
    """ids the §3.5 predicate admits, via the SQL helper the generators use."""
    clause, params = scope_sql(scope)
    return {
        r["id"]
        for r in store.reader().execute(f"SELECT id FROM memories m WHERE {clause}", params)
    }


# --- the write stamp ------------------------------------------------------

#: The column's CHECK constraint; the store must never write anything else.
LEGAL_VISIBILITIES = ("user", "chat", "profile", "shared")


def test_a_profile_wide_write_is_stamped_profile(store):
    """§3.5 pairs a profile-wide write (`scope_user=''`) with `visibility='profile'`."""
    assert visibility_of(store, remember(store, "shared knowledge", scope=OWNER)) == "profile"


def test_a_user_scoped_write_is_stamped_user(store):
    assert visibility_of(store, remember(store, "alice's own fact", scope=ALICE)) == "user"


def test_the_derived_stamp_is_always_a_legal_value(store):
    """The `MemoryDraft` default is `''`, a sentinel; it must never reach the column."""
    for scope in (OWNER, ALICE, BOB, OTHER_PROFILE):
        mid = remember(store, f"derived for {scope.user or 'profile'}", scope=scope)
        assert visibility_of(store, mid) in LEGAL_VISIBILITIES


def test_an_explicit_visibility_is_preserved(store):
    """`'shared'` and `'chat'` are only ever deliberate; a caller's word stands."""
    for index, value in enumerate(LEGAL_VISIBILITIES):
        mid = remember(store, f"explicit {value} number {index}", scope=ALICE, visibility=value)
        assert visibility_of(store, mid) == value


def test_an_explicit_user_stamp_on_a_profile_wide_write_survives(store):
    """The caller's explicit intent is not overridden by the derivation."""
    mid = remember(store, "written for one user", scope=OWNER, visibility="user")
    assert visibility_of(store, mid) == "user"


# --- the read guard -------------------------------------------------------


def test_a_profile_wide_row_stamped_user_is_owner_only(store):
    mid = remember(store, "written for one user", scope=OWNER, visibility="user")
    assert _in_scope(row(store, mid), ALICE) is False
    assert _in_scope(row(store, mid), BOB) is False
    assert _in_scope(row(store, mid), OWNER) is True
    assert _in_scope(row(store, mid), SCOPED_OWNER) is True
    assert mid not in visible_by_id(store, ALICE)
    assert mid in visible_by_id(store, OWNER)


def test_a_user_scoped_row_stamped_user_is_not_owner_only(store):
    mid = remember(store, "alice's own fact", scope=ALICE)
    assert row(store, mid)["visibility"] == "user"
    assert _in_scope(row(store, mid), ALICE) is True
    assert mid in visible_by_id(store, ALICE)


# --- the regression guard: the test that matters --------------------------


def test_a_non_owner_still_sees_an_ordinary_profile_wide_row(store):
    """The whole point: fixing the stamp must not hide the profile's shared knowledge.

    With the read clause alone (no write fix) every pre-existing profile-wide row
    carries `'user'` and would vanish for non-owners. The write fix is what makes
    ordinary profile-wide writes readable, and this is the assertion that pins it.
    """
    mid = remember(store, "the staging server runs on port 9090", scope=OWNER)
    assert visibility_of(store, mid) == "profile"
    for scope in (ALICE, BOB, SCOPED_OWNER):
        assert _in_scope(row(store, mid), scope) is True, scope
        assert mid in visible_by_id(store, scope), scope


def test_a_non_owner_still_sees_a_profile_wide_row_of_any_ordinary_tier(store):
    for tier in ("public", "internal"):
        mid = remember(store, f"profile {tier} fact", scope=OWNER, sensitivity=tier)
        assert _in_scope(row(store, mid), ALICE) is True, tier


def test_a_non_owner_still_does_not_see_a_profile_wide_sensitive_row(store):
    """The tier half of the rule is untouched by this chunk."""
    mid = remember(store, "a profile secret", scope=OWNER, sensitivity="sensitive")
    assert _in_scope(row(store, mid), ALICE) is False
    assert _in_scope(row(store, mid), OWNER) is True


# --- the predicate's truth table ------------------------------------------


@pytest.mark.parametrize(
    "candidate,expected",
    [
        # the tier half
        ({"sensitivity": "sensitive", "scope_user": "alice", "visibility": "user"}, True),
        ({"sensitivity": "secret", "scope_user": "", "visibility": "profile"}, True),
        # the profile-wide + visibility='user' half
        ({"sensitivity": "internal", "scope_user": "", "visibility": "user"}, True),
        ({"sensitivity": "public", "scope_user": "", "visibility": "user"}, True),
        # and the combinations that are ordinary
        ({"sensitivity": "internal", "scope_user": "alice", "visibility": "user"}, False),
        ({"sensitivity": "internal", "scope_user": "", "visibility": "profile"}, False),
        ({"sensitivity": "internal", "scope_user": "", "visibility": "shared"}, False),
        ({"sensitivity": "internal", "scope_user": "alice", "visibility": "chat"}, False),
        # a row without the columns (an episode) is never owner-only
        ({}, False),
        ({"scope_profile": "default"}, False),
    ],
)
def test_row_is_owner_only_truth_table(candidate, expected):
    assert row_is_owner_only(candidate) is expected


# --- `MemoryStore.list`: why it needs no filter ---------------------------


def test_list_never_returns_a_profile_wide_row_to_a_scoped_caller(store):
    """This is why the Chunk 7.2 note is not a leak.

    `list` matches `scope_user=?` **exactly**, so a scoped caller can only ever
    receive rows already scoped to them — every one of which they may read,
    whatever its tier. The profile-wide rules govern rows it cannot return.
    """
    profile_wide = remember(store, "profile wide", scope=OWNER)
    # `secret` cannot be written through the policy (it is blocked), so the
    # most-restricted writable tier stands in — the point is only that `list`
    # cannot return a profile-wide row to a scoped caller at all.
    profile_sensitive = remember(store, "profile sensitive", scope=OWNER, sensitivity="sensitive")
    mine = remember(store, "alice's own", scope=ALICE)
    theirs = remember(store, "bob's own", scope=BOB)

    with store.transaction() as conn:
        listed = {r["id"] for r in MemoryStore(conn).list(scope=ALICE, status=("active", "pending"))}

    assert listed == {mine}
    assert not (listed & {profile_wide, profile_sensitive, theirs})


def test_list_gives_a_profile_wide_caller_the_profile_wide_rows(store):
    profile_wide = remember(store, "profile wide", scope=OWNER)
    with store.transaction() as conn:
        listed = {r["id"] for r in MemoryStore(conn).list(scope=OWNER, status=("active", "pending"))}
    assert profile_wide in listed


def test_list_is_an_exact_scope_match_and_must_stay_one(store):
    """Pin the invariant Chunk 13 leans on: ``list`` matches ``scope_user=?`` **exactly**.

    "Why does `list` need no tier filter?" only has an answer while the match is
    exact — a scoped caller can then receive nothing but its own rows. Widen the
    clause in either direction and this test is the thing that notices:

    * to ``scope_user=? OR scope_user=''`` → a scoped caller starts seeing
      profile-wide rows, so ``listed(ALICE)`` grows and the first assertion fails;
    * to an exact match again but *without* the equality, or with the profile-wide
      caller's user empty matching everything → ``listed(OWNER)`` grows.

    Behaviour is the pin rather than the source text, so a legitimate rewrite of
    how the clause is built is fine while a widening is not.
    """
    profile_wide = remember(store, "profile wide", scope=OWNER)
    mine = remember(store, "alice's own", scope=ALICE)
    theirs = remember(store, "bob's own", scope=BOB)

    def listed(scope) -> set:
        with store.transaction() as conn:
            return {
                r["id"]
                for r in MemoryStore(conn).list(scope=scope, status=("active", "pending"))
            }

    assert listed(ALICE) == {mine}, "a scoped caller must see only its own rows"
    assert listed(BOB) == {theirs}
    assert listed(OWNER) == {profile_wide}, "a profile-wide caller must not see user rows"


# --- publication, the consequence this change carries ---------------------


def test_a_profile_wide_write_is_queued_for_sync(store):
    """`_outbox` publishes `visibility in ('profile','shared')`.

    The old default stamped `'user'`, so a profile-wide write was never queued —
    while v2's gate was `_publish_allowed(sensitivity)`, i.e. v2 published every
    non-sensitive fact. Resolving the stamp restores that.
    """
    assert outbox_rows(store, remember(store, "publishable", scope=OWNER)) == 1


def test_a_profile_wide_sensitive_write_is_not_queued(store):
    """The tier gate, which used to be satisfied only by accident."""
    mid = remember(store, "a profile secret", scope=OWNER, sensitivity="sensitive")
    assert visibility_of(store, mid) == "profile", "the stamp is still profile"
    assert outbox_rows(store, mid) == 0, "but a sensitive row must stay local"


def test_a_user_scoped_write_is_not_queued(store):
    assert outbox_rows(store, remember(store, "alice only", scope=ALICE)) == 0


def test_an_explicitly_shared_write_is_queued(store):
    assert outbox_rows(store, remember(store, "shareable", scope=ALICE, visibility="shared")) == 1


# --- reversibility --------------------------------------------------------


def test_the_change_adds_no_migration(store):
    """Reversible: no schema change, no data rewrite, so a revert is code-only."""
    assert LATEST == 4
    assert [m.version for m in discover()] == [1, 2, 3, 4]


def test_reads_do_not_rewrite_the_stamp(store):
    """A pre-existing row keeps the value it has; only new writes derive one."""
    mid = remember(store, "pre-fix shape", scope=OWNER, visibility="user")
    visible_by_id(store, OWNER)
    with store.transaction() as conn:
        MemoryStore(conn).list(scope=OWNER, status=("active", "pending"))
    assert visibility_of(store, mid) == "user"
