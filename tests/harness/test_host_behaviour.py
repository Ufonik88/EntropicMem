"""Behaviour-contract tests: FakeHost's host-mimicry, proven with test doubles.

Each test pins one verified MemoryManager behaviour (hermes-agent, 2026-09-23):
the 8 s prefetch join and stuck-provider skip, the >10k output spill, byte-
identical replay of prior <memory-context> blocks, signature-filtered
sync_turn kwargs, /new serialization, /undo rewound=True, compression v2
checkpoint fail-closed, and the bounded shutdown drain.
"""

import threading
import time
from pathlib import Path

import pytest
from fake_host import FakeHost


class Stub:
    """Minimal provider duck; subclasses override what they care about."""

    pre_compress_checkpoint_api_version = 2
    name = "stub"

    def __init__(self):
        self.calls = []
        self.switch_kwargs = {}
        self.checkpoint_mode = "success"
        self.pre_compress_messages = None
        self.require_checkpoint_seen = None
        self.shutdown_called = False
        self.session_end_messages = None

    def _rec(self, name):
        self.calls.append(name)

    def names(self):
        return list(self.calls)

    def is_available(self):
        return True

    def initialize(self, session_id, **kwargs):
        self._rec("initialize")

    def system_prompt_block(self):
        return "STUB SYSTEM"

    def prefetch(self, query, *, session_id=""):
        self._rec("prefetch")
        return "stub memory"

    def queue_prefetch(self, query, *, session_id=""):
        self._rec("queue_prefetch")

    def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None,
                  turn_author=None):
        self._rec("sync_turn")

    def on_turn_start(self, turn_number, message, **kwargs):
        self._rec("on_turn_start")

    def on_session_end(self, messages):
        self._rec("on_session_end")
        self.session_end_messages = messages

    def on_session_switch(self, new_session_id, *, parent_session_id="", reset=False,
                          rewound=False, **kwargs):
        self._rec("on_session_switch")
        self.switch_kwargs = dict(parent_session_id=parent_session_id, reset=reset,
                                  rewound=rewound, reason=kwargs.get("reason"))

    def on_pre_compress(self, messages, require_checkpoint=False, **kwargs):
        self._rec("on_pre_compress")
        self.pre_compress_messages = messages
        self.require_checkpoint_seen = require_checkpoint
        if self.checkpoint_mode == "raise":
            raise RuntimeError("checkpoint persist failed")
        return "stub constraints"

    def on_delegation(self, task, result, *, child_session_id="", **kwargs):
        self._rec("on_delegation")

    def get_tool_schemas(self):
        return []

    def shutdown(self):
        self.shutdown_called = True


def test_stuck_prefetch_times_out_then_skips_provider_until_it_returns(home_a):
    release = threading.Event()

    class Slow(Stub):
        def prefetch(self, query, *, session_id=""):
            self._rec("prefetch")
            release.wait(30)
            return "late memory"

    stub = Slow()
    host = FakeHost(stub, hermes_home=home_a)
    host.start()
    import fake_host

    saved = fake_host.EXTERNAL_PREFETCH_TIMEOUT_S
    fake_host.EXTERNAL_PREFETCH_TIMEOUT_S = 0.2
    try:
        block, _ = host.turn("first question about zyx widgets")
        assert block == ""  # timed out
        assert host.metrics["prefetch_timeouts"] == 1
        block2, _ = host.turn("second question about zyx widgets")
        assert block2 == ""  # skipped while the first call is stuck
        assert host.metrics["prefetch_stuck_skips"] >= 1
        release.set()
        deadline = time.monotonic() + 5
        while any(t.is_alive() for t in host._prefetch_threads.values()) and time.monotonic() < deadline:
            time.sleep(0.01)
        # after the stuck call returns, prefetch runs again
        block3, _ = host.turn("third question about zyx widgets")
        assert "late memory" in block3
    finally:
        fake_host.EXTERNAL_PREFETCH_TIMEOUT_S = saved
    host.shutdown()


def test_oversized_prefetch_spills_to_disk(home_a):
    class Big(Stub):
        def prefetch(self, query, *, session_id=""):
            return "X" * 12_000

    host = FakeHost(Big(), hermes_home=home_a)
    host.start()
    block, _ = host.turn("tell me a very long story about zyx")
    assert host.metrics["spill_count"] == 1
    assert len(block) <= 10_000 + 1000  # preview stays bounded
    assert block.startswith("<memory-context>")
    spill = list((home_a / "hook_outputs").rglob("prefetch-*.txt"))
    assert spill and spill[0].read_text(encoding="utf-8") == "X" * 12_000
    host.shutdown()


def test_prior_blocks_replay_into_prompt_and_cumulate_tokens(home_a):
    class Counting(Stub):
        def __init__(self):
            super().__init__()
            self.n = 0

        def prefetch(self, query, *, session_id=""):
            self.n += 1
            return f"fact number {self.n}: the widget needs zyx setting {self.n}"

    stub = Counting()
    host = FakeHost(stub, hermes_home=home_a)
    host.start()
    blocks = []
    prev_cum = 0
    for i in range(5):
        block, _ = host.turn(f"how does widget setting {i} work")
        blocks.append(block)
        cum = host.prompt_tokens()
        # replay: every earlier block stays in the prompt → monotonic growth
        assert cum > prev_cum
        prev_cum = cum
    # earlier user rows still carry their injected block verbatim (api_content sidecar)
    user_rows = [r for r in host.transcript if r["role"] == "user"]
    assert any("api_content" in r and blocks[0] in r["api_content"] for r in user_rows)
    for i, r in enumerate(r for r in host.transcript if r["role"] == "user"):
        if i < len(blocks) and blocks[i]:
            assert blocks[i] in (r.get("api_content") or r["content"]), "replay must be byte-identical"
    host.shutdown()


def test_sync_turn_gets_turn_author_only_when_accepted(home_a):
    received = {}

    class WithAuthor(Stub):
        name = "with_author"

        def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None,
                      turn_author=None):
            received["author"] = turn_author
            received["messages"] = messages

    host = FakeHost(WithAuthor(), hermes_home=home_a)
    host.start()
    host.turn("what about the zyx widget now", author={"id": "u2", "name": "Bob", "is_bot": True})
    assert host.drain(timeout=5)
    assert received["author"] == {"id": "u2", "name": "Bob", "is_bot": True}
    assert isinstance(received["messages"], list) and received["messages"][0]["role"] == "user"
    host.shutdown()

    class Bare(Stub):
        name = "bare"

        def sync_turn(self, user_content, assistant_content, *, session_id=""):
            received["bare_ok"] = True

    host2 = FakeHost(Bare(), hermes_home=home_a)
    host2.start()
    host2.turn("does the bare signature survive", author={"id": "u3"})
    assert host2.drain(timeout=5)
    assert received.get("bare_ok") is True  # no TypeError: kwargs were filtered out
    host2.shutdown()


def test_new_session_serializes_end_then_switch_on_fifo(home_a):
    stub = Stub()
    host = FakeHost(stub, hermes_home=home_a)
    host.start()
    old_id = host.session_id
    host.turn("some real question about zyx")
    assert host.drain(timeout=5)
    stub.calls.clear()
    new_id = host.new_session()
    assert host.drain(timeout=5)
    assert stub.names() == ["on_session_end", "on_session_switch"]
    assert stub.switch_kwargs == {"parent_session_id": old_id, "reset": True,
                                  "rewound": False, "reason": "new_session"}
    assert host.session_id == new_id
    assert stub.session_end_messages[-2]["role"] == "user"  # old transcript handed over
    host.shutdown()


def test_undo_forwards_rewound_true(home_a):
    stub = Stub()
    host = FakeHost(stub, hermes_home=home_a)
    host.start()
    host.undo()
    assert stub.switch_kwargs["rewound"] is True
    assert stub.switch_kwargs["reset"] is False
    host.shutdown()


def test_compression_v2_evidence_checkpoint_and_switch(home_a):
    stub = Stub()
    host = FakeHost(stub, hermes_home=home_a)
    host.start()
    host.turn("remember that we chose the zyx approach", assistant_text="Noted, zyx it is.")
    host.turn("and the deploy target is staging", assistant_text="Staging target recorded.")
    assert host.drain(timeout=5)
    result = host.compress(require_checkpoint=True)
    assert "stub constraints" in result
    # v2 evidence: user/assistant rows only, api_content stripped from the sidecar row
    roles = {m["role"] for m in stub.pre_compress_messages}
    assert roles == {"user", "assistant"}
    assert all("api_content" not in m for m in stub.pre_compress_messages)
    assert stub.require_checkpoint_seen is True
    assert stub.switch_kwargs["reason"] == "compression"
    assert stub.switch_kwargs["reset"] is False
    # system block rebuilt at the compression boundary
    assert host.build_system_prompt() == "STUB SYSTEM"
    host.shutdown()


def test_compression_fail_closed_propagates_when_required(home_a):
    stub = Stub()
    stub.checkpoint_mode = "raise"
    host = FakeHost(stub, hermes_home=home_a)
    host.start()
    with pytest.raises(RuntimeError, match="checkpoint persist failed"):
        host.compress(require_checkpoint=True)
    # without require_checkpoint the host swallows provider failures (fail-soft)
    stub.checkpoint_mode = "raise"
    out = host.compress(require_checkpoint=False)
    assert out == ""
    host.shutdown()


def test_delegation_hook_reaches_provider(home_a):
    stub = Stub()
    host = FakeHost(stub, hermes_home=home_a)
    host.start()
    host.delegate("research zyx widgets", "found 3 vendors", child_session_id="child-9")
    assert "on_delegation" in stub.names()
    host.shutdown()


def test_shutdown_drains_fifo_within_5s_then_shuts_provider(home_a):
    stub = Stub()
    host = FakeHost(stub, hermes_home=home_a)
    host.start()
    for i in range(5):
        host.turn(f"question {i} about the zyx widget")
    t0 = time.monotonic()
    state = host.shutdown()
    assert state["status"] == "drained"
    assert stub.shutdown_called is True
    # queued sync tasks all ran before shutdown returned
    assert stub.names().count("sync_turn") == 5
    assert time.monotonic() - t0 < 5.5
    host.shutdown()  # idempotent


def test_provider_reading_env_after_init_gets_the_decoy(home_a, monkeypatch):
    """Env-poisoning tripwire: post-initialize os.environ['HERMES_HOME'] is a WRONG path."""
    import os

    seen = {}

    class EnvReader(Stub):
        def prefetch(self, query, *, session_id=""):
            seen["env"] = os.environ.get("HERMES_HOME")
            return ""

    host = FakeHost(EnvReader(), hermes_home=home_a)
    host.start()
    assert Path(os.environ["HERMES_HOME"]) == host._decoy_env_home
    assert Path(os.environ["HERMES_HOME"]) != home_a
    host.turn("does env leak")
    assert seen["env"] != str(home_a)  # env is NOT the real home after init
    assert seen["env"] == str(host._decoy_env_home)
    host.shutdown()
    monkeypatch.undo()
