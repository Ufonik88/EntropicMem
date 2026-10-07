"""EM-211 Chunk 7.2: the §3.5 owner-only rule for sensitive reads.

The facade's reads were profile-wide: any user of a profile could read a
``sensitive`` or ``secret`` memory. This file pins the rule that closes that, in
the one place the rule lives (``em.store.memories._in_scope``) and through every
read path the plan named.

The decision this chunk had to make — and the thing most likely to be "fixed"
wrongly later:

* ``Scope.is_owner`` defaults to **False** (fail-closed). A scoped caller must
  assert ownership to read an owner-only tier. The failure mode of a wiring
  mistake is then the owner failing to see their own sensitive rows (visible),
  not a guest seeing them (silent).
* A **profile-wide** caller (``scope.user == ''``) is the owner context. That is
  the v2 single-owner, no-gateway and CLI case, and it is why the default
  ``V3Engine(db)`` keeps working.
* A **guest** is exactly a caller with a non-empty ``user`` and ``is_owner``
  False — which mirrors the provider's ``_is_guest()``: gateway user set, owner
  list non-empty, and the user not in it. The default config has an empty owner
  list, so nobody is a guest there.

Rules: invented data only (Acme/Globex/Initech, Alice/Bob Example).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins/entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.facade.engine import V3Engine  # noqa: E402
from em.store.memories import _in_scope  # noqa: E402
from em.store.types import Scope  # noqa: E402

OWNER = "sensitive content about Acme's payroll run."
PUBLIC = "Acme deploys the billing service with a blue-green rollout."
SYMBOL = "Acme exposes metrics on port 9102."


def row(*, profile: str = "default", user: str = "", sensitivity: str = "internal") -> dict:
    return {"scope_profile": profile, "scope_user": user, "sensitivity": sensitivity}


# --- the rule itself (the one function, unit-tested as a truth table) ---------


@pytest.mark.parametrize(
    "caller, the_row, visible",
    [
        # An ordinary tier is readable by anyone in scope.
        (Scope("default"), row(), True),
        (Scope("default", user="alice"), row(sensitivity="internal"), True),
        (Scope("default", user="alice"), row(user="alice", sensitivity="public"), True),
        # A profile-wide caller is the owner context.
        (Scope("default"), row(sensitivity="sensitive"), True),
        (Scope("default"), row(sensitivity="secret"), True),
        # A scoped caller without ownership is a guest: owner-only tiers are out.
        (Scope("default", user="alice"), row(sensitivity="sensitive"), False),
        (Scope("default", user="alice"), row(sensitivity="secret"), False),
        (Scope("default", user="alice"), row(user="alice", sensitivity="sensitive"), False),
        # The assertion of ownership is what lets a scoped caller read them.
        (Scope("default", user="alice", is_owner=True), row(user="alice", sensitivity="sensitive"), True),
        (Scope("default", user="alice", is_owner=True), row(sensitivity="secret"), True),
        # Scope still decides access to the row: another user's row is out even
        # for an owner, and another profile is always out.
        (Scope("default", user="alice", is_owner=True), row(user="bob", sensitivity="sensitive"), False),
        (Scope("other"), row(sensitivity="internal"), False),
        (Scope("other"), row(sensitivity="sensitive"), False),
        # A profile-wide row is shared knowledge: visible to every user in the
        # profile. Only the owner-only tiers are restricted, not profile-wide
        # rows as such.
        (Scope("default", user="bob"), row(sensitivity="internal"), True),
        (Scope("default", user="bob"), row(sensitivity="sensitive"), False),
    ],
)
def test_in_scope_truth_table(caller, the_row, visible):
    assert _in_scope(the_row, caller) is visible


def test_is_owner_defaults_closed():
    """The fail-closed default is the decision, so pin it.

    Flipping this to True silently reopens the leak this chunk closed.
    """
    assert Scope("default", user="alice").is_owner is False
    assert Scope("default").is_owner is False


# --- the facade read paths ----------------------------------------------------


@pytest.fixture
def db(tmp_path):
    return tmp_path / "memory.db"


def owner(db):
    return V3Engine(db)


def scoped(db, user, *, is_owner=False):
    return V3Engine(db, scope_user=user, is_owner=is_owner)


def seed_profile_wide(db) -> V3Engine:
    """One sensitive and one ordinary profile-wide memory, written as the owner.

    Tiers are `sensitive`, not `secret`: the write policy blocks a `secret` tier
    outright (`evaluate_write` returns "block" for it), so a secret row can only
    arrive by migration. `test_a_secret_row_is_owner_only` inserts one directly to
    cover that tier on the read side.
    """
    eng = owner(db)
    eng.remember(content=OWNER, title="Payroll", sensitivity="sensitive")
    eng.remember(content=PUBLIC, sensitivity="internal")
    eng.remember(content=SYMBOL, sensitivity="sensitive")
    return eng


def test_get_fact_hides_a_sensitive_row_from_a_guest(db):
    seed = seed_profile_wide(db)
    guest = scoped(db, "alice")
    try:
        from memory_engine import StoredFact

        mid = StoredFact.make_id(OWNER)
        assert seed.get_fact(mid) is not None, "the owner reads their own sensitive row"
        assert guest.get_fact(mid) is None, "a guest must not"
    finally:
        seed.close()
        guest.close()


def test_get_fact_still_shows_an_ordinary_row_to_a_guest(db):
    seed = seed_profile_wide(db)
    guest = scoped(db, "alice")
    try:
        from memory_engine import StoredFact

        assert guest.get_fact(StoredFact.make_id(PUBLIC)) is not None, (
            "only owner-only tiers are restricted; the rule must not hide everything"
        )
    finally:
        seed.close()
        guest.close()


def test_an_owner_that_asserts_ownership_reads_its_own_sensitive_row(db):
    alice = scoped(db, "alice", is_owner=True)
    content = "Alice Example prefers window seats on flights."
    # A scoped write deliberately does not stamp a content-derived legacy_id
    # (Chunk 5), so the id it returns is the way back to the row.
    mid = alice.remember(content=content, sensitivity="sensitive")
    assert alice.get_fact(mid) is not None
    alice.close()


def test_recall_hides_a_sensitive_row_from_a_guest(db):
    seed = seed_profile_wide(db)
    guest = scoped(db, "alice")
    try:
        keeper = seed.recall_with_relevance("payroll run", top_k=5, min_relevance=0.0)
        assert keeper, "the owner recalls their sensitive row"
        assert guest.recall_with_relevance("payroll run", top_k=5, min_relevance=0.0) == [], (
            "a guest must not recall it either"
        )
        # and the ordinary row is still recallable by the guest
        assert guest.recall_with_relevance("blue-green rollout", top_k=5, min_relevance=0.0)
    finally:
        seed.close()
        guest.close()


def test_recall_hybrid_hides_a_sensitive_row_from_a_guest(db):
    seed = seed_profile_wide(db)
    guest = scoped(db, "alice")
    try:
        assert seed.recall_hybrid("payroll run", top_k=5)
        assert guest.recall_hybrid("payroll run", top_k=5) == []
    finally:
        seed.close()
        guest.close()


def test_the_literal_like_fallback_is_not_a_way_around_the_rule(db):
    """A digits query takes the LIKE path, which must apply the same rule."""
    seed = seed_profile_wide(db)
    guest = scoped(db, "alice")
    try:
        assert seed._like_fallback("9102", 5, None, 0.0, False), "owner sees it"
        assert guest._like_fallback("9102", 5, None, 0.0, False) == [], "guest does not"
    finally:
        seed.close()
        guest.close()


def test_find_mirrored_hides_a_sensitive_mirror_from_a_guest(db):
    seed = owner(db)
    content = "Mirrored: Acme's payroll provider is Globex."
    seed.remember(content=content, tags=["mirrored", "user"],
                  source="built_in_memory", sensitivity="sensitive")
    guest = scoped(db, "alice")
    try:
        assert seed.find_mirrored("payroll provider is Globex") is not None
        assert guest.find_mirrored("payroll provider is Globex") is None, (
            "a guest must not locate a sensitive mirror, or a replace could touch it"
        )
    finally:
        seed.close()
        guest.close()


def test_a_guest_still_reads_its_own_non_sensitive_rows(db):
    """The rule restricts tiers, not users: a guest keeps its own ordinary data."""
    guest = scoped(db, "alice")
    mid = guest.remember(content="Globex uses weekly release trains.",
                         sensitivity="internal")
    assert guest.get_fact(mid)
    assert guest.recall_with_relevance("weekly release trains", top_k=5, min_relevance=0.0)
    guest.close()


def test_the_default_facade_is_the_owner_context(db):
    """No scope_user means profile-wide, which is the owner: v2's behaviour."""
    eng = V3Engine(db)
    mid = eng.remember(content="Initech rotates credentials every ninety days.",
                       sensitivity="sensitive")
    assert eng.get_fact(mid)
    eng.close()


def test_a_secret_row_is_owner_only(db):
    """`secret` cannot be written through the policy, so a migrated one is simulated.

    This is the tier the write path refuses to create, which is exactly why the
    read rule has to cover it: a row that arrived by migration still must not be
    readable by a guest.
    """
    seed = owner(db)
    content = "Globex holds the payroll master key."
    mid = seed.remember(content=content, sensitivity="sensitive")
    with seed.store.transaction() as conn:
        conn.execute("UPDATE memories SET sensitivity='secret' WHERE id=?", (mid,))

    from memory_engine import StoredFact

    legacy = StoredFact.make_id(content)
    assert seed.get_fact(legacy) is not None, "the owner reads it"
    guest = scoped(db, "alice")
    try:
        assert guest.get_fact(legacy) is None, "a guest must not"
        assert guest.recall_with_relevance("payroll master key", top_k=5,
                                           min_relevance=0.0) == []
    finally:
        seed.close()
        guest.close()
