"""F-004's own finding, resolved and pinned: two gateway users, one profile.

`tests/regressions/test_findings_v27.py::test_f004_cross_user_isolation` is the
finding — the shape here is the *fix's* evidence surface, driven beside the
group-chat harness (`test_group_chat_scoping.py`, which covers one host with
per-turn authors). The F-004 shape is different and worth its own surface: two
*providers* (two Hermes sessions, each with its own gateway principal) sharing
one profile's v3 store.

Pinned end to end (plan §9 item 9's (a)+(c)):

* writes are attributed to each gateway user (``scope_user``/``visibility``);
* prefetch, the search tool, search-by-ids, update (edit and supersedes),
  forget (by id and through the confirm-token flow), the four review actions
  and the episode reads all refuse or omit the other user's rows;
* profile-wide rows stay shared across both users — the migration ruling
  (plan §9 item 9 (b), keep profile-wide) — for a bot-author write.

The store is a v3 store, created up front: ``em.facade.select`` resolves a
store that does not exist yet to the v2 engine, and the v2 engine has no scope
columns at all. The shared-profile scenario only has full per-user isolation on
the v3 line — which is exactly the state the owner's cutover produces, so this
harness certifies that state as it will be.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from fake_host import FakeHost  # noqa: E402
from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

from em.store.db import Store  # noqa: E402
from em.store.migrations import migrate  # noqa: E402

ALICE_ID = "user_alice"
BOB_ID = "user_bob"

QUERY = "what is the passphrase prefix"

ALICE_SECRET = "Alpha secret passphrase prefix: al-seven"
BOB_SECRET = "Beta secret passphrase prefix: be-nine"
SHARED_NOTE = "The profile wallpaper choice is the Acme meadow green"

BOT_AUTHOR = {"id": "relay-bot", "name": "RelayBot", "is_bot": True}


def _v3_store(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(path))
    try:
        with store.writer() as conn:
            migrate(conn)
    finally:
        store.close()
    return path


@pytest.fixture()
def shared_profile(home_a):
    """Two providers + hosts over one v3 profile: alice and bob, one pool."""
    db = _v3_store(home_a / "entropicmem" / "memory.db")
    kwargs = {
        "vault_path": str(home_a / "entropicmem" / "vault"),
        "index_db": str(home_a / "entropicmem" / "index.db"),
        "memory_db": str(db),
    }
    provider_a = EntropicMemMemoryProvider(config=dict(kwargs))
    provider_b = EntropicMemMemoryProvider(config=dict(kwargs))
    host_a = FakeHost(
        provider_a,
        hermes_home=home_a,
        agent_identity="homeA",
        init_kwargs={"user_id": ALICE_ID, "chat_id": "chat_1"},
    )
    host_b = FakeHost(
        provider_b,
        hermes_home=home_a,
        agent_identity="homeA",
        init_kwargs={"user_id": BOB_ID, "chat_id": "chat_1"},
    )
    host_a.start()
    host_b.start()
    try:
        # The v3 drive is the certification's subject: assert neither provider
        # silently degraded to the v2 engine, which cannot express the buckets.
        assert provider_a._v3_store() is True
        assert provider_b._v3_store() is True
        yield host_a, host_b, provider_a, provider_b
    finally:
        host_a.shutdown()
        host_b.shutdown()


def _both_secrets(host_a: FakeHost, host_b: FakeHost) -> None:
    """alice and bob each remember their own secret through the tool."""
    host_a.tool("entropicmem_remember", {"content": ALICE_SECRET, "domain": "Credentials"})
    host_b.tool("entropicmem_remember", {"content": BOB_SECRET, "domain": "Credentials"})


def _alice_row_id(home_a: Path) -> str:
    store = Store(str(home_a / "entropicmem" / "memory.db"))
    try:
        conn = store.reader()
        try:
            row = conn.execute(
                "SELECT id FROM memories WHERE content=?", (ALICE_SECRET,)
            ).fetchone()
            assert row is not None, "the fixture write did not land"
            return str(row[0])
        finally:
            conn.close()
    finally:
        store.close()


def _tool_json(host: FakeHost, name: str, args: dict[str, Any]) -> Any:
    return json.loads(host.tool(name, args))


def _rows_of(payload: Any) -> list[dict[str, Any]]:
    """The row list from whatever shape a tool result carries."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    for key in ("rows", "results", "memories"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


# -- writes are bucketed ------------------------------------------------------


def test_remember_buckets_each_write_to_its_gateway_user(shared_profile, home_a):
    host_a, host_b, _, _ = shared_profile
    _both_secrets(host_a, host_b)

    store = Store(str(home_a / "entropicmem" / "memory.db"))
    try:
        conn = store.reader()
        try:
            rows = [
                dict(r) for r in conn.execute(
                    "SELECT content, scope_user, visibility FROM memories ORDER BY rowid"
                )
            ]
        finally:
            conn.close()
    finally:
        store.close()

    by_content = {r["content"]: r for r in rows}
    assert by_content[ALICE_SECRET]["scope_user"] == ALICE_ID
    assert by_content[ALICE_SECRET]["visibility"] == "user"
    assert by_content[BOB_SECRET]["scope_user"] == BOB_ID
    assert by_content[BOB_SECRET]["visibility"] == "user"


# -- the user blocks (prefetch + the search tool) -----------------------------


def test_prefetch_isolates_both_directions(shared_profile):
    host_a, host_b, _, _ = shared_profile
    _both_secrets(host_a, host_b)

    block_a, _ = host_a.turn(QUERY, assistant_text="Checking.")
    block_b, _ = host_b.turn(QUERY, assistant_text="Checking.")

    assert "al-seven" in block_a
    assert "be-nine" not in block_a, "bob's memory leaked into alice's context"
    assert "be-nine" in block_b
    assert "al-seven" not in block_b, "alice's memory leaked into bob's context"


def test_the_search_tool_isolates_both_directions(shared_profile):
    host_a, host_b, _, _ = shared_profile
    _both_secrets(host_a, host_b)

    found_a = _rows_of(_tool_json(host_a, "entropicmem_search", {"query": "passphrase prefix"}))
    found_b = _rows_of(_tool_json(host_b, "entropicmem_search", {"query": "passphrase prefix"}))
    own_a = [r["id"] for r in found_a if "al-seven" in r.get("content", "")]
    own_b = [r["id"] for r in found_b if "be-nine" in r.get("content", "")]

    assert own_a and own_b, "each user's own secret must surface for them"
    assert not (set(own_a) & set(own_b))


def test_search_by_another_user_s_id_answers_missing(shared_profile, home_a):
    host_a, host_b, _, _ = shared_profile
    _both_secrets(host_a, host_b)

    alice_id = _alice_row_id(home_a)
    out_b = host_b.tool("entropicmem_search", {"ids": [alice_id]})
    assert "al-seven" not in out_b, "another user's id must not resolve a row for bob"
    out_a = host_a.tool("entropicmem_search", {"ids": [alice_id]})
    assert "al-seven" in out_a, "her own id must still resolve for alice"


# -- the keyed writes (update / forget / review) --------------------------------


def test_update_and_supersede_refuse_another_user_s_row(shared_profile, home_a):
    host_a, host_b, _, _ = shared_profile
    _both_secrets(host_a, host_b)
    target = _alice_row_id(home_a)

    for mode in ("edit", "supersede"):
        out = host_b.tool(
            "entropicmem_update",
            {"id": target, "content": "bob's rewrite", "mode": mode},
        )
        assert "not_found" in out, f"{mode} on alice's row must refuse: {out}"
        # and alice still owns the row: her own edit attempt is not refused
        if mode == "edit":
            own = host_a.tool(
                "entropicmem_update",
                {"id": target, "content": f"{ALICE_SECRET} (noted)", "mode": mode},
            )
            assert '"ok": true' in own, f"alice must still edit her own row: {own}"


def test_forget_by_id_refuses_another_user_s_row(shared_profile, home_a):
    host_a, host_b, _, _ = shared_profile
    _both_secrets(host_a, host_b)
    target = _alice_row_id(home_a)

    out = host_b.tool("entropicmem_forget", {"id": target})
    assert "not_found" in out, f"forget on alice's row must refuse: {out}"
    still_there = _alice_row_id(home_a)
    assert still_there == target, "the refused forget must not have deleted the row"


def test_the_forget_confirm_flow_never_offers_another_user_s_row(shared_profile):
    host_a, host_b, _, _ = shared_profile
    _both_secrets(host_a, host_b)

    parsed_b = _tool_json(host_b, "entropicmem_forget", {"query": "passphrase prefix"})
    contents_b = " ".join(c.get("content", "") for c in parsed_b.get("candidates", []))
    assert "al-seven" not in contents_b, "bob's forget preview must not offer alice's row"
    if parsed_b.get("confirm_token"):
        # Whatever bob could preview, confirming it must not delete alice's row.
        result_b = host_b.tool(
            "entropicmem_forget", {"confirm_token": parsed_b["confirm_token"]}
        )
        assert "al-seven" not in result_b


def test_the_review_actions_refuse_another_user_s_row(shared_profile, home_a):
    host_a, host_b, _, _ = shared_profile
    _both_secrets(host_a, host_b)
    target = _alice_row_id(home_a)

    cases = (
        {"action": "promote", "id": target},
        {"action": "discard", "id": target},
        {"action": "restore", "id": target},
        {"action": "feedback", "id": target, "signal": "helpful"},
    )
    for args in cases:
        out = host_b.tool("entropicmem_review", args)
        assert "not_found" in out, f"{args['action']} on alice's row must refuse: {out}"


# -- episodes ------------------------------------------------------------------


def test_timeline_does_not_carry_another_user_s_episodes(shared_profile):
    host_a, host_b, _, _ = shared_profile
    host_a.delegate("check the passphrase ledger", "found one line")

    out_a = host_a.tool("entropicmem_timeline", {"query": "passphrase ledger"})
    assert "passphrase ledger" in out_a, "alice's own episode must reach alice"

    out_b = host_b.tool("entropicmem_timeline", {"query": "passphrase ledger"})
    assert "passphrase ledger" not in out_b, "bob's timeline must not see alice's episodes"


def test_episode_search_isolates_both_directions(shared_profile):
    host_a, host_b, _, _ = shared_profile
    host_a.delegate("write the Acme annual summary", "done")
    host_b.delegate("write the Globex quarterly summary", "done")

    out_a = host_a.tool("entropicmem_timeline", {"query": "summary"})
    out_b = host_b.tool("entropicmem_timeline", {"query": "summary"})
    assert "Acme annual" in out_a, "alice's own episode must reach alice"
    assert "Globex quarterly" not in out_a, "bob's episode must not reach alice"
    assert "Globex quarterly" in out_b, "bob's own episode must reach bob"
    assert "Acme annual" not in out_b, "alice's episode must not reach bob"


# -- the recorded asymmetry (episodes) -----------------------------------------


def test_a_profile_wide_episode_is_under_read_for_a_user_bucket(shared_profile):
    """The episodes read rule is exact-bucket — recorded, pinned, not changed.

    ``em.store.episodes``' reads filter ``scope_user = <bucket>`` with **no**
    ``OR scope_user=''`` half, while the memories' ``scope_sql`` rule shares
    profile-wide rows with every user (pinned above by the ruling-(b) test).
    So a profile-wide episode — the shape a bot/flush digest takes — is
    invisible to a user-mode caller. F-004's own axis is cross-user *leak*,
    and this is an under-read (nothing moves in the other direction), so the
    F-004 chunk records and pins it instead of widening §3.5's semantics
    silently; the semantic call rides the cutover card with the other
    default-flip items.
    """
    host_a, host_b, provider_a, _ = shared_profile
    db = host_a.hermes_home / "entropicmem" / "memory.db"

    from em.store.db import Store
    from em.store.episodes import EpisodeStore
    from em.store.types import Scope

    # The bot-author stamp for an episode in this profile: the session's own
    # profile/chat, user='' (the §3.5 bot rule, the migration's shape).
    turn_scope = provider_a._state.scope.to_scope()
    profile_id = turn_scope.profile or "default"
    store = Store(str(db))
    try:
        with store.writer() as conn:
            EpisodeStore(conn).add_episode(
                scope=Scope(profile=profile_id, user="", chat=turn_scope.chat),
                kind="manual",
                title="the shared profile flush digest",
                session_id="sess-flush-1",
            )
    finally:
        store.close()

    out_a = host_a.tool("entropicmem_timeline", {"query": "flush digest"})
    out_b = host_b.tool("entropicmem_timeline", {"query": "flush digest"})
    assert "flush digest" not in out_a, "the exact-bucket rule hides '' episodes from alice (recorded)"
    assert "flush digest" not in out_b, "and from bob — under-read, a leak in neither direction"


# -- the migration ruling's shared half ----------------------------------------


def test_profile_wide_rows_stay_shared_between_the_two_users(shared_profile):
    """(b) ruled: existing profile-wide facts keep profile-wide reads.

    A bot-author write lands profile-wide (§3.5), and after the cutover's
    migration the ~1,700 existing facts land exactly there — both users must
    still read them.
    """
    host_a, host_b, _, _ = shared_profile

    host_a.turn("note it.", author=BOT_AUTHOR, assistant_text="Noted.")
    host_a.tool("entropicmem_remember", {"content": SHARED_NOTE, "sensitivity": "internal"})

    block_a, _ = host_a.turn("what is the wallpaper choice", assistant_text="Checking.")
    block_b, _ = host_b.turn("what is the wallpaper choice", assistant_text="Checking.")
    assert "meadow green" in block_a
    assert "meadow green" in block_b, "a profile-wide row must stay shared (ruling (b))"


def test_the_shared_profile_harness_drives_the_v3_engine(shared_profile):
    """A silent degradation would re-open F-004 by construction."""
    _, _, provider_a, provider_b = shared_profile
    assert provider_a._v3_store() is True
    assert provider_b._v3_store() is True
