"""``fail_soft`` — the §4.1 hook wrapper (EM-401).

Every lifecycle hook the host calls is wrapped by :func:`fail_soft`, which the
master plan's EM-401 card specifies: *"Each hook body is wrapped by
``@fail_soft(budget_ms=…, metric="hook.<name>")`` which logs over-budget calls
at WARNING and swallows exceptions (except ``on_pre_compress`` under
``require_checkpoint``)."*

Two deliberate strengthenings over that sentence, both recorded here rather
than left to be discovered:

* **Fail-closed hooks.** ``on_pre_compress`` (and ``initialize``/``save_config``
  /``backup_paths`` — see :data:`FAIL_CLOSED_HOOKS`) re-raise instead of
  swallowing. The reason is §4.6's promise: *a non-empty return implies steps 2
  and 4 committed*, and the host counts **any** non-raising return as success.
  Swallowing a failed checkpoint therefore claims a persist that never
  happened, so the hook must raise and let §4.6's own fail-soft paths (a
  skipped or absent checkpoint) live in the body, where they return ``""``.
* **No content in the log.** An over-budget line and a failure line carry the
  hook name, the millisecond figure and the exception *type* — never the
  exception message, which for a tool handler can contain the user's text. The
  full exception reaches DEBUG only, where an operator has already opted in.

The metrics are counters and totals, not a distribution: a per-hook histogram
is EM-403's prefetch work and S8's, and calling ``avg_ms`` a percentile would be
a lie.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections import Counter
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("em.provider.hooks")

#: §4.1's per-hook budgets, in milliseconds. A hook wrapped by ``fail_soft``
#: without an explicit ``budget_ms`` must appear here; an unknown name is a
#: programming error and raises at decoration time rather than silently
#: enforcing nothing.
#:
#: ``prefetch`` is §4.1's p95 target (150 ms); the 1.5 s hard internal cap is
#: EM-403's. ``handle_tool_call`` takes §4.1's write bound (500 ms) because the
#: read/write split (300/500) is EM-404's per-tool work.
HOOK_BUDGETS: Dict[str, float] = {
    "name": 1.0,
    "get_tool_schemas": 5.0,
    "is_available": 5.0,
    "unavailable_reason": 1.0,
    "initialize": 150.0,
    "system_prompt_block": 20.0,
    "on_turn_start": 5.0,
    "prefetch": 150.0,
    "recall_status": 1.0,
    "queue_prefetch": 50.0,
    "sync_turn": 30.0,
    "handle_tool_call": 500.0,
    "on_memory_write": 50.0,
    "on_session_switch": 30.0,
    "on_pre_compress": 2000.0,
    "on_delegation": 30.0,
    "identity_signature": 5.0,
    "on_session_end": 300.0,
    "backup_paths": 50.0,
    "shutdown": 2000.0,
    "get_config_schema": 50.0,
    "save_config": 500.0,
}

#: Hooks whose failure the host must see. See the module docstring: a swallowed
#: exception here would let a failed act read as a successful one.
FAIL_CLOSED_HOOKS = frozenset(
    {
        "on_pre_compress",  # §4.6: any non-raising return counts as success
        "initialize",  # a half-initialised provider must not look ready
        "save_config",  # §4.1: raises on failure, visible to the setup UI
        "backup_paths",  # §4.1: must resolve or fail loudly, never guess
    }
)


class HookMetrics:
    """Thread-safe per-hook counters and millisecond totals.

    ``record`` is called once per hook invocation, on the hook's own thread, so
    the counters are the only place a caller can learn that a hook ran at all.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: Counter[str] = Counter()
        self._errors: Counter[str] = Counter()
        self._over_budget: Counter[str] = Counter()
        self._total_ms: Counter[str] = Counter()

    def record(self, name: str, *, ms: float, ok: bool, over_budget: bool) -> None:
        with self._lock:
            self._calls[name] += 1
            self._total_ms[name] += ms
            if not ok:
                self._errors[name] += 1
            if over_budget:
                self._over_budget[name] += 1

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        """``{hook_name: {"calls", "errors", "over_budget", "total_ms", "avg_ms"}}``."""
        with self._lock:
            calls, errors, over = self._calls, self._errors, self._over_budget
            totals = self._total_ms
        return {
            name: {
                "calls": calls[name],
                "errors": errors[name],
                "over_budget": over[name],
                "total_ms": totals[name],
                "avg_ms": (totals[name] / count) if count else 0.0,
            }
            for name, count in sorted(calls.items())
        }

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()
            self._errors.clear()
            self._over_budget.clear()
            self._total_ms.clear()


#: The process-wide metrics the wrapper writes to. One instance per process;
#: ``reset_metrics()`` exists for tests, never for product code.
_METRICS = HookMetrics()


def metrics() -> HookMetrics:
    return _METRICS


def reset_metrics() -> None:
    _METRICS.reset()


def fail_soft(
    budget_ms: Optional[float] = None,
    *,
    metric: Optional[str] = None,
    fallback: Optional[Callable[..., Any]] = None,
    fail_closed: Optional[bool] = None,
):
    """Wrap a hook body: time it, count it, and survive it.

    Usable bare (``@fail_soft``) or with arguments
    (``@fail_soft(budget_ms=…)``); the bare form is the usual one and reads
    :data:`HOOK_BUDGETS` by the wrapped function's name.

    Parameters
    ----------
    budget_ms:
        Over-budget threshold. ``None`` reads :data:`HOOK_BUDGETS`.
    metric:
        Metric name; defaults to ``hook.<function name>`` (§4.1).
    fallback:
        ``fallback(*args, **kwargs)`` returning the value a swallowed failure
        yields. ``None`` (i.e. the hook returns ``None``) unless the hook's
        return type demands otherwise — ``handle_tool_call`` returns an error
        JSON because §4.4 requires a JSON string always.
    fail_closed:
        Re-raise instead of swallowing. Defaults to membership in
        :data:`FAIL_CLOSED_HOOKS`.
    """
    if callable(budget_ms) and metric is None and fallback is None and fail_closed is None:
        return fail_soft()(budget_ms)

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        name = fn.__name__
        if budget_ms is None:
            if name not in HOOK_BUDGETS:
                raise KeyError(
                    f"fail_soft: no §4.1 budget for hook {name!r}; add one to "
                    "em.provider.hooks.HOOK_BUDGETS or pass budget_ms explicitly"
                )
            budget = HOOK_BUDGETS[name]
        else:
            budget = float(budget_ms)
        metric_name = metric or f"hook.{name}"
        closed = (name in FAIL_CLOSED_HOOKS) if fail_closed is None else bool(fail_closed)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                _METRICS.record(
                    metric_name,
                    ms=elapsed_ms,
                    ok=False,
                    over_budget=elapsed_ms > budget,
                )
                if closed:
                    raise
                # Type only: a tool handler's message can carry the user's text.
                log.error(
                    "%s failed (%s); exception detail at DEBUG level",
                    metric_name,
                    type(exc).__name__,
                )
                log.debug("%s exception detail", metric_name, exc_info=True)
                if fallback is None:
                    return None
                return fallback(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            over = elapsed_ms > budget
            _METRICS.record(metric_name, ms=elapsed_ms, ok=True, over_budget=over)
            if over:
                log.warning(
                    "%s over budget: %.1f ms > %.0f ms",
                    metric_name,
                    elapsed_ms,
                    budget,
                )
            return result

        wrapper.__fail_soft__ = {  # type: ignore[attr-defined]
            "metric": metric_name,
            "budget_ms": budget,
            "fail_closed": closed,
        }
        return wrapper

    return decorate
