"""Host-contract tests for FakeHost: what hooks fire, in what order, with what kwargs.

FakeHost must call the provider exactly the way Hermes MemoryManager does
(pinned hermes-agent, agent/memory_manager.py, 2026-09-23):
  initialize(full §2.3 kwarg set) -> on_turn_start -> prefetch (own thread, 8 s join)
  -> sync_turn -> queue_prefetch (FIFO worker), in real order, with real signature
  filtering.
"""

import threading

import pytest
from fake_host import FULL_INITIALIZE_KWARGS, FakeHost


class Recorder:
    """Duck-typed provider recording every call: (name, thread, session_id)."""

    pre_compress_checkpoint_api_version = 2
    name = "recorder"

    def __init__(self):
        self.calls = []
        self.init_kwargs = {}
        self.lock = threading.Lock()

    def _rec(self, name):
        with self.lock:
            self.calls.append((name, threading.current_thread().name))

    def names(self):
        return [c[0] for c in self.calls]

    # -- core lifecycle ----------------------------------------------------
    def is_available(self):
        return True

    def initialize(self, session_id, **kwargs):
        self._rec("initialize")
        self.init_kwargs = kwargs
        self.session_id = session_id

    def system_prompt_block(self):
        self._rec("system_prompt_block")
        return "REC SYSTEM BLOCK"

    def prefetch(self, query, *, session_id=""):
        self._rec("prefetch")
        return f"REC MEMORY for {query[:30]}"

    def queue_prefetch(self, query, *, session_id=""):
        self._rec("queue_prefetch")

    def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None):
        self._rec("sync_turn")

    def get_tool_schemas(self):
        return []

    def handle_tool_call(self, tool_name, args, **kwargs):
        self._rec(f"tool:{tool_name}")
        return '{"ok": true}'

    def shutdown(self):
        self._rec("shutdown")

    # -- hooks --------------------------------------------------------------
    def on_turn_start(self, turn_number, message, **kwargs):
        self._rec("on_turn_start")
        self.last_turn_kwargs = kwargs

    def on_session_end(self, messages):
        self._rec("on_session_end")

    def on_session_switch(self, new_session_id, *, parent_session_id="", reset=False,
                          rewound=False, **kwargs):
        self._rec("on_session_switch")
        self.switch_kwargs = dict(parent_session_id=parent_session_id, reset=reset,
                                  rewound=rewound, reason=kwargs.get("reason"))

    def on_pre_compress(self, messages, require_checkpoint=False, **kwargs):
        self._rec("on_pre_compress")
        self.pre_compress_kwargs = {"require_checkpoint": require_checkpoint,
                                    "messages": messages}
        return "REC CONSTRAINTS"

    def on_delegation(self, task, result, *, child_session_id="", **kwargs):
        self._rec("on_delegation")
        self.delegation = (task, result, child_session_id)


@pytest.fixture()
def rec(tmp_path):
    return Recorder()


def test_initialize_receives_full_hermes_kwarg_set(rec, home_a):
    host = FakeHost(rec, hermes_home=home_a, platform="telegram")
    host.start()
    got = rec.init_kwargs
    missing = set(FULL_INITIALIZE_KWARGS) - set(got)
    assert not missing, f"initialize() kwargs missing: {sorted(missing)}"
    assert got["hermes_home"] == str(home_a)
    assert got["platform"] == "telegram"
    assert got["agent_workspace"] == "hermes"
    assert got["agent_context"] == "primary"
    host.shutdown()


def test_normal_turn_hook_order_and_return_contract(rec, home_a):
    host = FakeHost(rec, hermes_home=home_a)
    host.start()
    block, latency = host.turn("How do I configure the zyx widget?")
    assert host.drain(timeout=5.0), "FIFO worker did not drain"
    names = rec.names()
    assert names[:2] == ["initialize", "system_prompt_block"]
    assert names.index("on_turn_start") < names.index("prefetch") < names.index("sync_turn") < names.index("queue_prefetch")
    # output wrapped in <memory-context> and latency is a positive float in ms
    assert block.startswith("<memory-context>\n") and block.endswith("\n</memory-context>")
    assert "REC MEMORY" in block
    assert isinstance(latency, float) and latency >= 0.0
    # author trio reaches on_turn_start (gateway identity)
    assert rec.last_turn_kwargs["author_is_bot"] is False
    host.shutdown()
    assert "shutdown" in rec.names()


def test_prefetch_runs_on_separate_thread_from_sync_worker(rec, home_a):
    host = FakeHost(rec, hermes_home=home_a)
    host.start()
    host.turn("what does the widget need")
    assert host.drain(timeout=5.0)
    calls = dict(rec.calls)  # name -> thread
    assert calls["prefetch"] != threading.main_thread().name
    assert calls["sync_turn"] == calls["queue_prefetch"]  # single FIFO worker
    assert calls["sync_turn"] != calls["prefetch"]  # different from prefetch thread
    host.shutdown()


def test_fifo_worker_serializes_turns_in_order(tmp_path, home_a):
    class OrderRec(Recorder):
        def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None):
            self._rec(f"sync:{user_content.split()[3]}")

    rec = OrderRec()
    host = FakeHost(rec, hermes_home=home_a)
    host.start()
    for i in range(10):
        host.turn(f"turn question number {i} about zyx")
    assert host.drain(timeout=8.0)
    syncs = [c[0] for c in rec.calls if c[0].startswith("sync:")]
    assert syncs == [f"sync:{i}" for i in range(10)], "FIFO order violated"
    host.shutdown()


def test_trivial_prompts_skip_prefetch(rec, home_a):
    host = FakeHost(rec, hermes_home=home_a)
    host.start()
    for prompt in ("hi", "thanks!", "continue", "/new"):
        block, _ = host.turn(prompt)
        assert block == ""
    assert "prefetch" not in rec.names()
    host.shutdown()


def test_sync_turn_kwargs_are_signature_filtered(home_a):
    """Hermes passes messages/turn_author ONLY when the signature accepts them."""

    class BareSync(Recorder):
        def sync_turn(self, user_content, assistant_content, *, session_id=""):
            self._rec("sync_turn")
            self.sync_kwargs = {"messages": session_id}  # noqa — placeholder

    prov = BareSync()
    host = FakeHost(prov, hermes_home=home_a)
    host.start()
    host.turn("does profile work", author={"id": "u1", "name": "Ann", "is_bot": False})
    assert host.drain(timeout=5.0)
    # provider must not have received turn_author/messages kwargs (TypeError otherwise
    # — the test passes if the call landed at all); on_turn_start still gets the trio.
    assert "sync_turn" in prov.names()
    assert prov.last_turn_kwargs["author_name"] == "Ann"
    host.shutdown()
