"""EM-401: ``fail_soft``, the §4.1 budgets, and the per-session state.

These are the pieces the installed provider's hooks are built from, so they are
tested against a stand-in class that carries the same signatures the host
filters on — not against the provider, which needs a whole Hermes home. The
harness drives the real provider (``tests/harness/test_provider_hook_surface.py``)
and the contract test pins the surface (``tests/test_provider_contract.py``).
"""

from __future__ import annotations

import inspect
import logging
import threading

import pytest

from em.provider.hooks import (
    FAIL_CLOSED_HOOKS,
    HOOK_BUDGETS,
    HookMetrics,
    fail_soft,
    metrics,
    reset_metrics,
)
from em.provider.state import PRIMARY, ProviderState


@pytest.fixture(autouse=True)
def _clean_metrics():
    reset_metrics()
    yield
    reset_metrics()


# ── the decorator, in isolation ───────────────────────────────────────────────


def test_returns_the_wrapped_value_and_counts_it():
    @fail_soft
    def recall_status(self):
        return "ok"

    assert recall_status(object()) == "ok"
    assert metrics().snapshot()["hook.recall_status"]["calls"] == 1
    assert metrics().snapshot()["hook.recall_status"]["errors"] == 0


def test_swallows_an_exception_and_logs_it_without_the_message(caplog):
    """Privacy: the log carries the exception TYPE, never its message.

    A tool handler's message can contain the user's text (``_tool_error(str(e))``
    passes it straight through), so the ERROR line names the type only. The full
    exception is a DEBUG record — an operator who raised the level opted in, and
    this test reads at INFO precisely so that is visible.
    """

    @fail_soft
    def prefetch(self, query):
        raise RuntimeError("SECRET-MARKER-do-not-log-7f3a")

    with caplog.at_level(logging.INFO, logger="em.provider.hooks"):
        assert prefetch(object(), "what did we decide") is None
    assert "SECRET-MARKER-do-not-log-7f3a" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert metrics().snapshot()["hook.prefetch"]["errors"] == 1


def test_fallback_receives_the_hook_arguments():
    seen = {}

    def _fallback(*args, **kwargs):
        seen.update({"args": args, "kwargs": kwargs})
        return "FALLBACK"

    @fail_soft(fallback=_fallback)
    def handle_tool_call(self, tool_name, args):
        raise ValueError("boom")

    assert handle_tool_call(object(), "entropicmem_remember", {"content": "x"}) == "FALLBACK"
    assert seen["args"][1] == "entropicmem_remember"


def test_over_budget_logs_a_warning_and_counts_it(caplog):
    @fail_soft(budget_ms=1.0)
    def initialize(self):
        import time

        time.sleep(0.01)
        return "done"

    with caplog.at_level(logging.INFO, logger="em.provider.hooks"):
        assert initialize(object()) == "done"
    assert "over budget" in caplog.text
    assert metrics().snapshot()["hook.initialize"]["over_budget"] == 1


def test_within_budget_is_silent(caplog):
    @fail_soft(budget_ms=5000.0)
    def recall_status(self):
        return None

    with caplog.at_level(logging.INFO, logger="em.provider.hooks"):
        recall_status(object())
    assert "over budget" not in caplog.text
    assert metrics().snapshot()["hook.recall_status"]["over_budget"] == 0


def test_an_unknown_hook_without_a_budget_is_a_programming_error():
    with pytest.raises(KeyError, match="no .* budget"):

        @fail_soft
        def not_a_hook(self):
            return None


def test_metric_name_defaults_to_the_hook_name():
    @fail_soft
    def sync_turn(self):
        return None

    sync_turn(object())
    assert "hook.sync_turn" in metrics().snapshot()


def test_fail_closed_hooks_raise_instead_of_swallowing():
    for name in ("on_pre_compress", "initialize", "save_config", "backup_paths"):
        assert name in FAIL_CLOSED_HOOKS

    @fail_soft
    def on_pre_compress(self, messages, require_checkpoint=False):
        raise RuntimeError("checkpoint persist failed")

    with pytest.raises(RuntimeError, match="checkpoint persist failed"):
        on_pre_compress(object(), [])
    # A fail-closed hook still records the failure it raises.
    assert metrics().snapshot()["hook.on_pre_compress"]["errors"] == 1


def test_only_the_named_hooks_are_fail_closed():
    """The carve-out list is closed: a new fail-closed hook must be added to
    FAIL_CLOSED_HOOKS deliberately, not inherited by accident."""
    import types

    def _hook_named(name):
        def fn(self):
            raise RuntimeError("x")

        # The decorator reads fn.__name__, so the name is set before wrapping.
        return types.FunctionType(fn.__code__, fn.__globals__, name, fn.__defaults__, fn.__closure__)

    swallowed = fail_soft(_hook_named("on_session_end"))
    assert swallowed(object()) is None

    closed = fail_soft(_hook_named("on_pre_compress"))
    with pytest.raises(RuntimeError):
        closed(object())


def test_the_wrapper_preserves_the_signature_the_host_filters_on():
    """The host passes ``messages``/``turn_author``/the author trio only to
    signatures that accept them; ``functools.wraps`` must keep that readable."""

    @fail_soft
    def on_turn_start(
        self,
        turn_number,
        message,
        *,
        author_id=None,
        author_name=None,
        author_is_bot=False,
        **kwargs,
    ):
        return None

    params = inspect.signature(on_turn_start).parameters
    for expected in ("turn_number", "message", "author_id", "author_name", "author_is_bot"):
        assert expected in params
    assert "kwargs" in params  # unknown host extras still land somewhere


def test_the_wrapper_is_thread_safe_enough_to_count_every_call():
    @fail_soft
    def queue_prefetch(self, query):
        return None

    threads = [threading.Thread(target=lambda: queue_prefetch(object(), "q")) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert metrics().snapshot()["hook.queue_prefetch"]["calls"] == 16


def test_every_surface_hook_has_a_budget():
    from em.provider.provider import implemented

    missing = [name for name in implemented() if name not in HOOK_BUDGETS]
    assert not missing, f"implemented hooks without a §4.1 budget: {missing}"


def test_metrics_snapshot_shape_and_reset():
    m = HookMetrics()
    m.record("hook.x", ms=2.0, ok=True, over_budget=False)
    m.record("hook.x", ms=6.0, ok=False, over_budget=True)
    snap = m.snapshot()
    assert snap["hook.x"] == {
        "calls": 2,
        "errors": 1,
        "over_budget": 1,
        "total_ms": 8.0,
        "avg_ms": 4.0,
    }
    m.reset()
    assert m.snapshot() == {}


# ── ProviderState ─────────────────────────────────────────────────────────────


def test_state_defaults_to_the_primary_context():
    state = ProviderState()
    assert state.session_id == ""
    assert state.agent_context == PRIMARY
    assert state.last_recall_count == 0
    assert state.writes_allowed() is True


@pytest.mark.parametrize("context", ["subagent", "cron", "flush", ""])
def test_state_refuses_writes_outside_the_primary_context(context):
    state = ProviderState(agent_context=context)
    assert state.writes_allowed() is False


def test_state_records_the_last_recall_count():
    state = ProviderState()
    state.note_recall(3)
    assert state.last_recall_count == 3
    state.note_recall(0)
    assert state.last_recall_count == 0
