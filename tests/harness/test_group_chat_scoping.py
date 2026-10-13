"""EM-402's acceptance criterion: a group chat with three authors.

One chat, three human authors (plus one bot), driven through FakeHost exactly
the way Hermes drives a shared session. Two properties, both §3.5:

* **Attribution** — a memory written on an author's turn belongs to that author
  (``scope_user=<author>``, ``visibility='user'``, ``author_id`` stamped), and a
  bot author's memory is profile-wide, never user-scoped.
* **No leak** — one author's user-private memory never reaches another author's
  prefetch, **including through the prefetch cache**: the same question asked by
  two authors must produce two blocks, because today's cache keys on the query
  alone and would hand author B author A's block verbatim.

The store is a v3 store so the §3.5 rules are the ones enforced (``em.store``
scopes rows per user); a v2 store is single-owner by construction and cannot
express the scenario.
"""

from __future__ import annotations

import sys
from pathlib import Path

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

ALICE = {"id": "u-alice", "name": "Alice Example", "is_bot": False}
BOB = {"id": "u-bob", "name": "Bob Example", "is_bot": False}
CARA = {"id": "u-cara", "name": "Cara Example", "is_bot": False}
RELAY = {"id": "relay-bot", "name": "RelayBot", "is_bot": True}

GROUP_KWARGS = {
    "user_id": "u-alice",
    "chat_id": "chat-group-1",
    "chat_name": "Acme ops",
    "chat_type": "group",
}

QUERY = "where is the staging deploy key kept?"

ALICE_SECRET = "Alice Example keeps the staging deploy key in the Acme vault under ops/deploy"
BOB_SECRET = "Bob Example keeps his laptop refresh budget in the Globex tracker"
CARA_SECRET = "Cara Example's on-call rotation is the Initech Tuesday shift"
SHARED = "The team standup is at 09:00 on the Acme bridge"


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
def group_chat(home_a):
    """A v3 store + provider + FakeHost running one group session."""
    db = _v3_store(home_a / "entropicmem" / "memory.db")
    provider = EntropicMemMemoryProvider(config={
        "owner_user_ids": ["u-alice"],
        "vault_path": str(home_a / "entropicmem" / "vault"),
        "index_db": str(home_a / "entropicmem" / "index.db"),
        "memory_db": str(db),
    })
    host = FakeHost(
        provider,
        hermes_home=home_a,
        platform="telegram",
        agent_context="primary",
        init_kwargs=dict(GROUP_KWARGS),
    )
    host.start()
    yield host, provider
    host.shutdown()


def _rows(host) -> list:
    """Every memory row in the v3 store, as dicts (read-only)."""
    db = host.hermes_home / "entropicmem" / "memory.db"
    store = Store(str(db))
    try:
        conn = store.reader()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT id, content, scope_user, visibility, author_id, sensitivity, status"
                " FROM memories ORDER BY rowid"
            )]
        finally:
            conn.close()
    finally:
        store.close()


def test_each_author_s_memory_is_attributed_to_that_author(group_chat):
    host, provider = group_chat

    host.turn("Remember this for me.", author=ALICE, assistant_text="Noted.")
    host.tool("entropicmem_remember", {"content": ALICE_SECRET, "sensitivity": "sensitive"})
    host.turn("Remember mine too.", author=BOB, assistant_text="Noted.")
    host.tool("entropicmem_remember", {"content": BOB_SECRET, "sensitivity": "sensitive"})
    host.turn("And mine.", author=CARA, assistant_text="Noted.")
    host.tool("entropicmem_remember", {"content": CARA_SECRET, "sensitivity": "sensitive"})

    by_content = {r["content"]: r for r in _rows(host)}
    for content, author in ((ALICE_SECRET, "u-alice"), (BOB_SECRET, "u-bob"), (CARA_SECRET, "u-cara")):
        row = by_content.get(content)
        assert row is not None, f"missing row: {content[:30]!r}"
        assert row["scope_user"] == author, f"{content[:30]!r} must be scoped to {author}"
        assert row["visibility"] == "user"
        assert row["author_id"] == author


def test_a_bot_author_never_creates_a_user_scoped_memory(group_chat):
    host, provider = group_chat

    host.turn("Posting a relay line.", author=RELAY, assistant_text="Noted.")
    host.tool("entropicmem_remember", {"content": SHARED, "sensitivity": "internal"})

    rows = [r for r in _rows(host) if r["content"] == SHARED]
    assert rows, "the bot's memory must land"
    assert rows[0]["scope_user"] == "", "a bot author's memory is profile-wide, never user-scoped"
    assert rows[0]["visibility"] == "profile"
    assert rows[0]["author_id"] == "relay-bot", "but it is still attributed"


def test_one_author_s_private_memory_never_reaches_another_author_s_prefetch(group_chat):
    host, provider = group_chat

    host.turn("Remember this for me.", author=ALICE, assistant_text="Noted.")
    host.tool("entropicmem_remember", {"content": ALICE_SECRET, "sensitivity": "sensitive"})
    host.turn("Remember this too.", author=BOB, assistant_text="Noted.")
    host.tool("entropicmem_remember", {"content": BOB_SECRET, "sensitivity": "sensitive"})

    block_alice, _ = host.turn(QUERY, author=ALICE, assistant_text="Checking.")
    assert "staging deploy key" in block_alice, "Alice's own memory must reach Alice"

    block_bob, _ = host.turn(QUERY, author=BOB, assistant_text="Checking.")
    assert "staging deploy key" not in block_bob, (
        "Bob's turn must never see Alice's user-private memory"
    )
    assert "laptop refresh budget" not in block_bob, (
        "and Bob must not be answered with Alice's cached block in place of his own"
    )

    block_cara, _ = host.turn(QUERY, author=CARA, assistant_text="Checking.")
    assert "staging deploy key" not in block_cara
    assert "laptop refresh budget" not in block_cara


def test_the_same_question_by_two_authors_returns_two_blocks_not_one_cached(group_chat):
    """The prefetch cache is keyed by the scope, not the query alone.

    Both authors ask the identical question within the cache TTL; a cache keyed
    on the query alone replays author A's block to author B — the leak this
    card exists to close.
    """
    host, provider = group_chat

    host.turn("Remember this for me.", author=ALICE, assistant_text="Noted.")
    host.tool("entropicmem_remember", {"content": ALICE_SECRET, "sensitivity": "sensitive"})

    first, _ = host.turn(QUERY, author=ALICE, assistant_text="Checking.")
    second, _ = host.turn(QUERY, author=BOB, assistant_text="Checking.")

    assert "staging deploy key" in first
    assert "staging deploy key" not in second, "a cached block must not cross authors"
    # Bob has no memory matching the question: his own block is legitimately
    # empty, and only Alice's replayed block would be non-empty here.
    assert second.strip() == "", "and his block must be his own (empty is correct)"


def test_profile_wide_knowledge_stays_shared_across_the_chat(group_chat):
    host, provider = group_chat

    host.turn("Remember this for everyone.", author=RELAY, assistant_text="Noted.")
    host.tool("entropicmem_remember", {"content": SHARED, "sensitivity": "internal"})

    block_bob, _ = host.turn("when is the team standup?", author=BOB, assistant_text="Checking.")
    assert "team standup" in block_bob, "profile-wide rows are shared knowledge (§3.5)"


# -- session scope resolution (the from_init_kwargs half of §3.5) -------------


def test_initialize_resolves_the_session_scope_from_the_host_kwargs(home_a):
    """The gateway identity, not the author, is the bucket for a turn without
    one — a provider that skips this resolution flattens every user into one
    pool."""
    provider = EntropicMemMemoryProvider(config={
        "vault_path": str(home_a / "entropicmem" / "vault"),
        "index_db": str(home_a / "entropicmem" / "index.db"),
        "memory_db": str(home_a / "entropicmem" / "memory.db"),
    })
    host = FakeHost(
        provider,
        hermes_home=home_a,
        platform="telegram",
        agent_context="primary",
        init_kwargs={"user_id": "u-dana", "chat_id": "chat-2", "chat_type": "group"},
    )
    host.start()
    try:
        ctx = provider._state.scope
        assert ctx.user == "u-dana", "user mode buckets the gateway user"
        assert ctx.chat == "", "user mode does not stamp the chat"
        assert ctx.chat_type == "group"
        assert ctx.is_owner is True, "no owner_user_ids configured: no guests (EM-118)"
    finally:
        host.shutdown()


def test_initialize_respects_an_explicit_chat_scope_mode(home_a):
    home_a.joinpath("config.yaml").write_text(
        "plugins:\n"
        "  entropicmem:\n"
        f"    vault_path: {home_a / 'entropicmem' / 'vault'}\n"
        f"    index_db: {home_a / 'entropicmem' / 'index.db'}\n"
        f"    memory_db: {home_a / 'entropicmem' / 'memory.db'}\n"
        "    scope_mode: chat\n",
        encoding="utf-8",
    )
    provider = EntropicMemMemoryProvider(config={})
    host = FakeHost(
        provider,
        hermes_home=home_a,
        platform="telegram",
        agent_context="primary",
        init_kwargs={"user_id": "u-dana", "chat_id": "chat-2", "chat_type": "group"},
    )
    host.start()
    try:
        ctx = provider._state.scope
        assert ctx.chat == "chat-2", "chat mode stamps the chat id"
        assert ctx.to_scope().chat == "chat-2"
    finally:
        host.shutdown()


def test_initialize_derives_guests_from_the_owner_list(home_a):
    provider = EntropicMemMemoryProvider(config={
        "owner_user_ids": ["u-ann"],
        "vault_path": str(home_a / "entropicmem" / "vault"),
        "index_db": str(home_a / "entropicmem" / "index.db"),
        "memory_db": str(home_a / "entropicmem" / "memory.db"),
    })
    host = FakeHost(
        provider,
        hermes_home=home_a,
        platform="telegram",
        agent_context="primary",
        init_kwargs={"user_id": "u-dana", "chat_type": "dm"},
    )
    host.start()
    try:
        assert provider._is_guest() is True, "u-dana is not in owner_user_ids"
        assert provider._state.scope.is_owner is False
    finally:
        host.shutdown()
