"""EM-402: §3.5's scope resolution (``em.policy.scopes``).

The truth table §3.5 draws, asserted as one table rather than prose: which
``scope_mode`` a session resolves to, which bucket each mode writes and reads
under, who the owner is, what a per-turn author does, and what a bot author may
never do. Plus the cache contract for ``scope_key``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins" / "entropicmem" / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from em.policy.scopes import (  # noqa: E402
    DEFAULT_OWNER_USER_ID,
    SCOPE_MODES,
    ScopeContext,
    resolve_scope_mode,
)

GATEWAY = {
    "agent_identity": "acme",
    "user_id": "u-bob",
    "chat_id": "chat-9",
    "chat_type": "group",
}
LOCAL = {"agent_identity": "acme"}


# -- scope_mode resolution ----------------------------------------------------


def test_the_modes_are_the_three_the_table_names():
    assert SCOPE_MODES == ("profile", "user", "chat")


def test_explicit_scope_mode_wins_over_the_gateway_default():
    assert resolve_scope_mode(GATEWAY, {"scope_mode": "profile"}) == "profile"
    assert resolve_scope_mode(GATEWAY, {"scope_mode": "chat"}) == "chat"
    assert resolve_scope_mode(LOCAL, {"scope_mode": "user"}) == "user"


def test_gateway_identity_defaults_to_user_mode_and_local_to_profile():
    """§3.5: ``user`` is the default when a gateway ``user_id`` is present."""
    assert resolve_scope_mode(GATEWAY, {}) == "user"
    assert resolve_scope_mode({"chat_id": "c-1"}, {}) == "user"
    assert resolve_scope_mode(LOCAL, {}) == "profile"


def test_an_invalid_scope_mode_is_ignored_for_the_default(caplog):
    with caplog.at_level("WARNING"):
        assert resolve_scope_mode(GATEWAY, {"scope_mode": "sideways"}) == "user"
    assert any("scope_mode" in r.message for r in caplog.records)


# -- from_init_kwargs: the §3.5 table ----------------------------------------


def test_profile_mode_writes_and_reads_profile_wide():
    ctx = ScopeContext.from_init_kwargs(GATEWAY, {"scope_mode": "profile"})
    assert ctx.user == ""
    assert ctx.chat == ""
    assert ctx.to_scope().user == ""


def test_user_mode_buckets_the_gateway_user_and_keeps_no_chat():
    ctx = ScopeContext.from_init_kwargs(GATEWAY, {})
    assert ctx.user == "u-bob"
    assert ctx.chat == ""
    assert ctx.chat_type == "group"
    assert ctx.profile == "acme"


def test_chat_mode_adds_the_chat_stamp():
    ctx = ScopeContext.from_init_kwargs(GATEWAY, {"scope_mode": "chat"})
    assert ctx.user == "u-bob"
    assert ctx.chat == "chat-9"


def test_local_user_mode_falls_back_to_the_owner_bucket():
    """§3.5's local-CLI bullet: ``meta.owner_user_id`` (default "owner") and
    ``is_owner=True``. Config ``owner_user_id`` is the recorded stand-in."""
    ctx = ScopeContext.from_init_kwargs(LOCAL, {"scope_mode": "user"})
    assert ctx.user == DEFAULT_OWNER_USER_ID == "owner"
    assert ctx.is_owner is True

    ctx = ScopeContext.from_init_kwargs(LOCAL, {"scope_mode": "user",
                                                "owner_user_id": "the-boss"})
    assert ctx.user == "the-boss"
    assert ctx.is_owner is True


def test_owner_ids_are_carried_for_per_turn_re_derivation():
    ctx = ScopeContext.from_init_kwargs(GATEWAY, {"owner_user_ids": ["u-bob", "u-ann"]})
    assert ctx.owner_user_ids == ("u-bob", "u-ann")


# -- the owner rule (EM-118, unchanged) --------------------------------------


@pytest.mark.parametrize(
    "user_id, owners, is_owner",
    [
        ("u-bob", [], True),          # no list: nobody is a guest (v2 pool)
        ("u-bob", ["u-bob"], True),   # the owner
        ("u-bob", ["u-ann"], False),  # a guest
        (None, ["u-ann"], True),      # no gateway identity: owner context
        ("", ["u-ann"], True),
    ],
)
def test_is_owner_follows_em118_exactly(user_id, owners, is_owner):
    kw = dict(GATEWAY)
    if user_id is None:
        kw.pop("user_id")
    else:
        kw["user_id"] = user_id
    ctx = ScopeContext.from_init_kwargs(kw, {"scope_mode": "profile", "owner_user_ids": owners})
    assert ctx.is_owner is is_owner
    assert ctx.is_guest is (not is_owner)


# -- with_author: the per-turn bucket ----------------------------------------


def test_a_non_bot_author_is_the_bucket_and_the_attribution():
    ctx = ScopeContext.from_init_kwargs(GATEWAY, {"owner_user_ids": ["u-ann"]})
    turn = ctx.with_author("u-cara", is_bot=False)
    assert turn.user == "u-cara"
    assert turn.author == "u-cara"
    assert turn.to_scope().author == "u-cara"
    assert turn.is_owner is False, "u-cara is not in owner_user_ids"


def test_the_owner_author_keeps_owner_role_in_a_group_chat():
    ctx = ScopeContext.from_init_kwargs(GATEWAY, {"owner_user_ids": ["u-ann"]})
    turn = ctx.with_author("u-ann", is_bot=False)
    assert turn.user == "u-ann"
    assert turn.is_owner is True


def test_a_bot_author_never_creates_user_scoped_memories():
    ctx = ScopeContext.from_init_kwargs(GATEWAY, {"owner_user_ids": ["u-ann"]})
    turn = ctx.with_author("relay-bot", is_bot=True)
    # The bot is still the bucket for reads (§3.5: the author is the bucket)...
    assert turn.user == "relay-bot"
    assert turn.author == "relay-bot"
    # ...but its writes are profile-wide and attributed, never user-scoped.
    write = turn.write_scope()
    assert write.user == ""
    assert write.author == "relay-bot"
    # A human author's writes are ordinary user-scoped rows.
    assert ctx.with_author("u-cara").write_scope().user == "u-cara"


def test_an_absent_author_keeps_the_bucket_but_a_bot_flag_still_applies():
    ctx = ScopeContext.from_init_kwargs(GATEWAY, {})
    assert ctx.with_author(None).user == ctx.user
    assert ctx.with_author(None, is_bot=True).write_scope().user == ""
    assert ctx.with_author("").author == ""


def test_bot_write_rows_derive_profile_visibility_not_the_owner_only_shape():
    """A profile-wide row stamped ``'user'`` *is* owner-only (§3.5), so a bot's
    profile-wide write must derive ``'profile'`` — the ordinary derivation rule
    applied to the write scope must not produce the owner-only shape."""
    from em.store.memories import _resolved_visibility
    from em.store.types import MemoryDraft, row_is_owner_only

    draft = MemoryDraft(content="Acme deploys on Tuesdays.")
    bot_write = ScopeContext.from_init_kwargs(GATEWAY, {}).with_author("relay-bot", is_bot=True).write_scope()
    human_write = ScopeContext.from_init_kwargs(GATEWAY, {}).with_author("u-cara").write_scope()

    bot_visibility = _resolved_visibility(draft, bot_write)
    assert bot_visibility == "profile"
    assert row_is_owner_only(
        {"sensitivity": "internal", "scope_user": "", "visibility": bot_visibility}
    ) is False
    assert _resolved_visibility(draft, human_write) == "user"


# -- scope_key: the cache contract -------------------------------------------


def test_scope_key_is_stable_and_sensitive_to_every_read_rule():
    base = ScopeContext.from_init_kwargs(GATEWAY, {"owner_user_ids": ["u-ann"]})
    assert base.scope_key == base.scope_key, "stable across calls"
    same = ScopeContext.from_init_kwargs(GATEWAY, {"owner_user_ids": ["u-ann"]})
    assert base.scope_key == same.scope_key, "stable across instances"

    assert base.with_author("u-cara").scope_key != base.scope_key
    assert base.with_author("u-cara").scope_key != base.with_author("u-dan").scope_key
    # chat scoping is what makes two same-author contexts read different rows;
    # in user mode the chat id is not stamped, so equal keys there are correct.
    chat_a = ScopeContext.from_init_kwargs(
        {**GATEWAY, "chat_id": "chat-9"}, {"scope_mode": "chat", "owner_user_ids": ["u-ann"]}
    )
    chat_b = ScopeContext.from_init_kwargs(
        {**GATEWAY, "chat_id": "chat-elsewhere"}, {"scope_mode": "chat", "owner_user_ids": ["u-ann"]}
    )
    assert chat_a.with_author("u-cara").scope_key != chat_b.with_author("u-cara").scope_key
    assert (
        ScopeContext.from_init_kwargs(GATEWAY, {"owner_user_ids": ["u-ann"]}).with_author("u-cara").scope_key
        == ScopeContext.from_init_kwargs(
            {**GATEWAY, "chat_id": "chat-elsewhere"}, {"owner_user_ids": ["u-ann"]}
        ).with_author("u-cara").scope_key
    )


def test_two_contexts_with_one_key_read_the_same_rows():
    """The property the prefetch cache is allowed to rely on."""
    a = ScopeContext.from_init_kwargs(GATEWAY, {"owner_user_ids": ["u-ann"]}).with_author("u-cara")
    b = ScopeContext.from_init_kwargs(GATEWAY, {"owner_user_ids": ["u-ann"]}).with_author("u-cara")
    assert a.scope_key == b.scope_key
    assert a.to_scope() == b.to_scope()


# -- with_user (the legacy seam) ---------------------------------------------


def test_with_user_re_derives_owner_role():
    ctx = ScopeContext.from_init_kwargs(GATEWAY, {"owner_user_ids": ["u-ann"]})
    assert ctx.with_user("u-ann").is_owner is True
    assert ctx.with_user("u-zoe").is_owner is False
    assert ctx.with_user("").is_owner is True
