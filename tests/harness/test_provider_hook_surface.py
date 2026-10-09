"""EM-401's first acceptance criterion: the harness drives every hook.

The turn path (initialize -> system_prompt_block -> on_turn_start -> prefetch ->
sync_turn -> queue_prefetch) is driven by FakeHost exactly the way Hermes
MemoryManager does; the hooks that only fire at a boundary or on a tool call are
driven directly. The evidence is not "we called them and nothing crashed" — the
``fail_soft`` metrics record one entry per hook invocation, so the test asserts
**every** row of :data:`em.provider.provider.implemented` has a recorded call and
none of them recorded an error.

That is the property the card asks for: a hook the provider stops implementing,
or implements in a way that now raises, fails here rather than going unnoticed
by every other test.
"""

from __future__ import annotations

import json
import logging
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

from em.provider.hooks import metrics, reset_metrics  # noqa: E402
from em.provider.provider import implemented  # noqa: E402

MESSAGES = [
    {"role": "user", "content": "Remember: never push to main without CI."},
    {"role": "assistant", "content": "Noted — green CI on the exact SHA first."},
    {"role": "user", "content": "We decided to use the Acme staging cluster."},
    {"role": "assistant", "content": "Logged: Acme staging is the default."},
]

#: The hooks the turn path does not reach, and how this test drives each one.
DRIVEN_DIRECTLY = {
    "is_available": lambda prov: prov.is_available(),
    "unavailable_reason": lambda prov: prov.unavailable_reason(),
    "recall_status": lambda prov: prov.recall_status(),
    "get_tool_schemas": lambda prov: prov.get_tool_schemas(),
    "handle_tool_call": lambda prov: prov.handle_tool_call("entropicmem_stats", {}),
    "get_config_schema": lambda prov: prov.get_config_schema(),
    "on_memory_write": lambda prov: prov.on_memory_write(
        "add", "memory", "Acme bills through Globex"
    ),
    "on_session_switch": lambda prov: prov.on_session_switch("sess-harness-2", reset=True),
    "on_session_end": lambda prov: prov.on_session_end(MESSAGES),
    "on_pre_compress": lambda prov: prov.on_pre_compress(MESSAGES),
    "backup_paths": lambda prov: prov.backup_paths(),
    "save_config": lambda prov, home: prov.save_config({"min_relevance_score": 0.4}, str(home)),
    "shutdown": lambda prov, home: prov.shutdown(),
}


def _drive(provider, home, name):
    """Drive *name*; ``save_config``/``shutdown`` also need the fake home."""
    if name in ("save_config", "shutdown"):
        DRIVEN_DIRECTLY[name](provider, home)
    else:
        DRIVEN_DIRECTLY[name](provider)


class _AuthorRecordingProvider(EntropicMemMemoryProvider):
    """Records the §4.1 author trio ``on_turn_start`` must receive.

    The override calls ``super()`` — the fail_soft-wrapped method — so the
    metrics the surface test asserts on still record.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.seen_author = None

    def on_turn_start(
        self,
        turn_number: int,
        message: str,
        *,
        author_id=None,
        author_name=None,
        author_is_bot=False,
        **kwargs,
    ):
        self.seen_author = (author_id, author_name, author_is_bot)
        return super().on_turn_start(
            turn_number,
            message,
            author_id=author_id,
            author_name=author_name,
            author_is_bot=author_is_bot,
            **kwargs,
        )


@pytest.fixture()
def driven_provider(home_a):
    return _AuthorRecordingProvider(config={
        "vault_path": str(home_a / "entropicmem" / "vault"),
        "index_db": str(home_a / "entropicmem" / "index.db"),
        "memory_db": str(home_a / "entropicmem" / "memory.db"),
    })


def _every_hook_ran_and_none_failed() -> dict:
    snapshot = metrics().snapshot()
    # Metric names are ``hook.<name>`` (§4.1); the surface uses bare names.
    ran = {name[len("hook."):] for name, row in snapshot.items() if row["calls"] >= 1}
    failed = {name[len("hook."):] for name, row in snapshot.items() if row["errors"]}
    return {"ran": ran, "failed": failed}


def test_the_harness_drives_every_hook_and_none_of_them_fail(driven_provider, home_a):
    reset_metrics()
    provider = driven_provider
    host = FakeHost(provider, hermes_home=home_a, platform="telegram", agent_context="primary")
    host.start()

    # -- the turn path, the way Hermes drives it ---------------------------
    block, latency = host.turn(
        "what did we decide about the migration?",
        author={"id": "u-harness-1", "name": "Ann Example", "is_bot": False},
    )
    assert host.drain(timeout=8.0), "FakeHost's FIFO worker did not drain"
    assert isinstance(block, str) and isinstance(latency, float)

    # -- §4.1's author trio reaches on_turn_start --------------------------
    assert provider.seen_author == ("u-harness-1", "Ann Example", False)

    # -- the hooks that fire only at a boundary or on a tool call ----------
    for name in DRIVEN_DIRECTLY:
        assert name in implemented(), f"{name} is driven but not in the §4.1 surface"
        _drive(provider, host.hermes_home, name)

    host.shutdown()

    result = _every_hook_ran_and_none_failed()
    # `name` is a property, not a wrapped call: nothing to record for it.
    expected = set(implemented()) - {"name"}
    missing = sorted(expected - result["ran"])
    assert not missing, f"§4.1 hooks the harness did not drive: {missing}"
    assert not result["failed"], f"hooks recorded an error: {sorted(result['failed'])}"


def test_a_hook_that_raises_is_counted_and_does_not_escape(driven_provider, home_a, caplog):
    """The fail-soft promise, observed on the real provider.

    ``prefetch`` also guards its own body (returning ""), which is the older
    layer; this drives a raise through a hook that does not — the tool
    dispatcher — so ``fail_soft`` itself is what survives it, and the metrics
    record the error rather than a silent success.
    """
    provider = driven_provider
    host = FakeHost(provider, hermes_home=home_a, agent_context="primary")
    host.start()

    def _boom(args):
        raise RuntimeError("store went away")

    provider._stats = _boom
    with caplog.at_level(logging.INFO, logger="em.provider.hooks"):
        out = provider.handle_tool_call("entropicmem_stats", {})
    assert json.loads(out)["error"]
    assert "store went away" not in caplog.text  # privacy: type only
    assert metrics().snapshot()["hook.handle_tool_call"]["errors"] == 1

    host.shutdown()


def test_a_tool_call_still_returns_json_when_a_handler_raises(driven_provider, home_a):
    """§4.4: handle_tool_call returns a JSON string always — the fail_soft
    fallback is what makes that true when a handler's own guard misses."""
    provider = driven_provider
    host = FakeHost(provider, hermes_home=home_a, agent_context="primary")
    host.start()

    def _boom(args):
        raise RuntimeError("store went away")

    provider._stats = _boom
    out = provider.handle_tool_call("entropicmem_stats", {})
    assert json.loads(out)["error"]

    host.shutdown()


def test_recall_status_reports_the_last_prefetch_only(driven_provider, home_a, monkeypatch):
    """§4.1: the count describes the LAST prefetch, never a stale one.

    The host's ``RecallStatus`` is a dataclass; the test mock hands the plugin a
    MagicMock for ``agent.memory_provider``, so a stand-in is installed for this
    test only (the deferred import inside the method is what makes that
    possible).
    """
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class FakeRecallStatus:
        provider_label: str
        count: int

    monkeypatch.setattr(sys.modules["agent.memory_provider"], "RecallStatus", FakeRecallStatus)

    provider = driven_provider
    assert provider.recall_status() is None  # nothing injected yet
    host = FakeHost(provider, hermes_home=home_a, agent_context="primary")
    host.start()

    # Store one fact, then ask a question that matches it.
    provider.handle_tool_call(
        "entropicmem_remember", {"content": "Acme bills every invoice through Globex"}
    )
    provider.prefetch("how does Acme bill its invoices?")
    status = provider.recall_status()
    assert status is not None, "a prefetch that injected a fact must report a count"
    assert status.provider_label == "EntropicMem"
    assert status.count >= 1

    # A prefetch that injected nothing reports nothing — not the last real count.
    provider.prefetch("zzzz unmatched query about nothing at all")
    assert provider.recall_status() is None

    host.shutdown()


def test_the_state_holder_survives_a_session_switch(driven_provider, home_a):
    provider = driven_provider
    host = FakeHost(provider, hermes_home=home_a, agent_context="cron")
    host.start()
    assert provider._state.agent_context == "cron"
    assert provider._writes_allowed() is False
    provider.on_session_switch("sess-next", parent_session_id="sess-harness-1", reset=True)
    assert provider._state.session_id == "sess-next"
    host.shutdown()
