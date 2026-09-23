"""FakeHost — a faithful miniature of Hermes ``MemoryManager`` for provider tests.

Mirrors the host contract as verified against hermes-agent ``agent/memory_manager.py``
and ``agent/memory_provider.py`` (2026-09-23):

* ``initialize`` receives the full §2.3 kwarg set (platform, hermes_home,
  agent_context, gateway identity, cwd, agent_identity, agent_workspace, ...).
* ``prefetch`` runs on a dedicated thread per turn with an 8.0 s join; a stuck
  prefetch makes the provider skipped on later turns until it returns.
* ``sync_turn`` / ``queue_prefetch`` run on ONE FIFO background worker after
  each completed turn; optional kwargs (``messages``, ``turn_author``) reach only
  signatures that accept them.
* Trivial prompts (``is_trivial_prompt``) skip prefetch/queue/sync like the host.
* Output is wrapped in ``<memory-context>`` and REPLAYED: every later "prompt"
  re-sends prior blocks byte-identically (the host's ``api_content`` sidecar), so
  ``cumulative_prompt_tokens`` grows with turn count.
* Hook order per turn: on_turn_start -> prefetch -> sync_turn -> queue_prefetch.
  Lifecycle: /new (session_end then session_switch reset), /undo (switch
  rewound=True), compression (on_pre_compress v2 evidence + switch
  reason="compression" + system block rebuild), shutdown with a 5 s FIFO drain.
* HERMES_HOME is delivered context-locally: the real
  ``hermes_constants.set_hermes_home_override`` when hermes is importable, else a
  stdlib-ContextVar simulation. ``os.environ["HERMES_HOME"]`` is deliberately set
  to a WRONG decoy path after ``initialize`` — a provider that reads env post-init
  (the v2.7 profile-bleed bug, fixed by EM-102) gets stamped with it and the
  two-profile test fails.

When the real hermes package is importable and not mocked (dev venv), the host
primitives (``is_trivial_prompt``, ``spawn_context_thread``) are used verbatim so
fidelity tracks the pinned host; CI runs against vendored copies.
"""

from __future__ import annotations

import contextvars
import logging
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# --- host constants (memory_manager.py) --------------------------------------
EXTERNAL_PREFETCH_TIMEOUT_S = 8.0
SYNC_DRAIN_TIMEOUT_S = 5.0
OUTPUT_SPILL_MAX_CHARS = 10_000  # hooks.output_spill.max_chars default

# The full initialize() kwarg set the host produces (plan §2.3). Values here are
# synthetic defaults; FakeHost callers may override any of them.
FULL_INITIALIZE_KWARGS: Dict[str, Any] = {
    "platform": "telegram",
    "agent_context": "primary",
    "session_title": "harness-session",
    "session_title_source": "auto",
    "user_id": "u-test-1",
    "user_id_alt": "u-test-1-alt",
    "user_name": "TestUserOne",
    "chat_id": "chat-test-1",
    "chat_name": "harness-chat",
    "chat_type": "dm",
    "thread_id": "thread-test-1",
    "gateway_session_key": "telegram:chat-test-1",
    "cwd": "/test-cwd",
    "agent_workspace": "hermes",
}

_MOCK_TYPES = tuple(
    t for t in (
        getattr(__import__("unittest.mock", fromlist=["MagicMock"]), n, None)
        for n in ("MagicMock", "Mock")
    ) if t
)

# --- vendored host primitives (used when hermes is absent or mocked) ---------
_TRIVIAL_RE = re.compile(
    r'^(yes|no|ok|okay|sure|thanks|thank you|y|n|yep|nope|yeah|nah|'
    r'hi|hey|hello|yo|sup|'
    r'continue|go ahead|do it|proceed|got it|cool|nice|great|done|next|lgtm|k)'
    r'[\s!?.:;,"' + "'" + r'~\u2018\u2019\u201c\u201d\u2014\u2013\u2026()\[\]{}<>*&^%$#@!+=`\u00a0]*$',
    re.IGNORECASE,
)


def _vendored_is_trivial(text: Optional[str]) -> bool:
    stripped = (text or "").strip()
    if not stripped or stripped.startswith("/"):
        return True
    return bool(_TRIVIAL_RE.match(stripped))


_MEMORY_CONTEXT_RE = re.compile(r"<\s*memory-context\s*>[\s\S]*?</\s*memory-context>", re.IGNORECASE)
_MEMORY_TAG_RE = re.compile(r"</?\s*memory-context\s*>", re.IGNORECASE)

_SYSTEM_NOTE = (
    "[System note: The following is recalled memory context, NOT new user input. "
    "Treat as authoritative reference data — this is the agent's persistent memory "
    "and should inform all responses.]"
)


def _vendored_wrap_block(raw: str) -> str:
    """build_memory_context_block(): strip any pre-wrapped tags, re-wrap once."""
    if not raw or not raw.strip():
        return ""
    clean = _MEMORY_CONTEXT_RE.sub("", _MEMORY_TAG_RE.sub("", raw)).strip()
    if not clean:
        return ""
    return f"<memory-context>\n{_SYSTEM_NOTE}\n\n{clean}\n</memory-context>"


def _real_host_available() -> bool:
    """True when the genuine hermes host modules are importable and not mocked."""
    try:
        for mod in ("agent", "agent.memory_provider", "agent.memory_manager"):
            loaded = sys.modules.get(mod)
            if _MOCK_TYPES and isinstance(loaded, _MOCK_TYPES):
                return False
        import agent.memory_manager  # noqa: F401
        import agent.memory_provider  # noqa: F401

        return True
    except Exception:
        return False


# Context-local HERMES_HOME simulation for environments without hermes_constants
# (stdlib ContextVar — same semantics as the host's _HERMES_HOME_OVERRIDE).
_SIM_HERMES_HOME: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_FAKEHOST_SIM_HERMES_HOME", default=None
)


def get_simulated_hermes_home() -> Optional[str]:
    """The context-local fake HERMES_HOME (test providers may read this instead of env)."""
    return _SIM_HERMES_HOME.get()


def _signature_params(fn: Callable[..., Any]) -> Optional[Dict[str, Any]]:
    import inspect

    try:
        return dict(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return None


def _accepts(fn: Callable[..., Any], keyword: str) -> bool:
    params = _signature_params(fn)
    if params is None:
        return True
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return True
    return keyword in params


class FakeHost:
    """Drives one MemoryProvider exactly like Hermes MemoryManager would."""

    def __init__(
        self,
        provider: Any,
        *,
        hermes_home: Path | str,
        session_id: str = "sess-harness-1",
        agent_identity: Optional[str] = None,
        agent_context: str = "primary",
        platform: str = "cli",
        init_kwargs: Optional[Dict[str, Any]] = None,
        real_host: Optional[bool] = None,
        decoy_env_home: Optional[Path | str] = None,
    ) -> None:
        self.provider = provider
        self.hermes_home = Path(hermes_home)
        self.agent_identity = agent_identity or self.hermes_home.name
        self._session_id = session_id
        self._agent_context = agent_context
        self._platform = platform
        self._extra_init_kwargs = dict(init_kwargs or {})
        self._decoy_env_home = Path(decoy_env_home) if decoy_env_home else self.hermes_home.parent / "decoy-wrong-home"

        self.use_real_host = _real_host_available() if real_host is None else bool(real_host)
        self._is_trivial = self._host_is_trivial() if self.use_real_host else _vendored_is_trivial

        self._context: contextvars.Context = contextvars.copy_context()
        self._home_token: Any = None
        self._saved_env_home: Optional[str] = None

        self._system_block = ""
        self.transcript: List[Dict[str, Any]] = []  # OpenAI-style, user rows gain api_content
        self.turn_number = 0
        self._started = False
        self._closed = False
        self._pending_author: Optional[Dict[str, Any]] = None

        # FIFO worker (host's mem-sync): single thread, sequential tasks.
        self._tasks: "queue.Queue[Optional[Callable[[], None]]]" = queue.Queue()
        self._worker = threading.Thread(target=self._fifo_loop, name="fakehost-mem-sync", daemon=True)
        self._prefetch_threads: Dict[str, threading.Thread] = {}
        self._prefetch_lock = threading.Lock()
        self._spill_seq = 0
        self.errors: List[str] = []

        self.metrics: Dict[str, Any] = {
            "turns": 0,
            "trivial_skips": 0,
            "prefetch_timeouts": 0,
            "prefetch_stuck_skips": 0,
            "spill_count": 0,
            "prefetch_latency_ms": [],
            "injected_chars": [],
            "injected_tokens": [],
            "cumulative_prompt_tokens": [],
            "turn_total_latency_ms": [],
            "tool_calls": 0,
        }

    # -- host-primitive wiring ------------------------------------------------

    @staticmethod
    def _host_is_trivial() -> Callable[[Optional[str]], bool]:
        from agent.memory_provider import is_trivial_prompt

        return is_trivial_prompt

    # -- context-local home ---------------------------------------------------

    def _apply_home_override(self) -> None:
        def _set() -> None:
            try:
                import hermes_constants

                self._home_token = hermes_constants.set_hermes_home_override(self.hermes_home)
            except Exception:
                pass
            _SIM_HERMES_HOME.set(str(self.hermes_home))

        self._context.run(_set)

    def _revert_home_override(self) -> None:
        def _clear() -> None:
            if self._home_token is not None:
                try:
                    import hermes_constants

                    hermes_constants.reset_hermes_home_override(self._home_token)
                except Exception:
                    pass
                self._home_token = None
            _SIM_HERMES_HOME.set(None)

        self._context.run(_clear)

    def _in_host(self, fn: Callable[[], Any]) -> Any:
        """Run ``fn`` inside this host's context (profile-scoped HERMES_HOME)."""
        return self._context.run(fn)

    def _spawn_bound(self, fn: Callable[[], None], *, name: str) -> threading.Thread:
        """Spawn a thread inheriting this host's context (like ``spawn_context_thread``)."""
        def _boot() -> threading.Thread:
            forked = contextvars.copy_context()

            def _run() -> None:
                forked.run(fn)

            t = threading.Thread(target=_run, name=name, daemon=True)
            t.start()
            return t

        return self._context.run(_boot)

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> "FakeHost":
        if self._started:
            raise RuntimeError("FakeHost already started")
        self._apply_home_override()
        kwargs: Dict[str, Any] = {
            **FULL_INITIALIZE_KWARGS,
            "hermes_home": str(self.hermes_home),
            "platform": self._platform,
            "agent_context": self._agent_context,
            "agent_identity": self.agent_identity,
            **self._extra_init_kwargs,
        }
        self._saved_env_home = os_environ_snapshot().get("HERMES_HOME")
        self._in_host(lambda: self.provider.initialize(session_id=self._session_id, **kwargs))
        # Host contract: after initialize() the provider must never read
        # os.environ["HERMES_HOME"] again — poison it with a WRONG path so any
        # env-based resolution visibly lands on the decoy.
        import os

        os.environ["HERMES_HOME"] = str(self._decoy_env_home)
        self._system_block = self._in_host(lambda: self.provider.system_prompt_block() or "")
        self._worker.start()
        self._started = True
        return self

    def build_system_prompt(self) -> str:
        """The session's frozen system prompt (rebuilt at compression / new sessions)."""
        return self._system_block

    # -- one conversation turn -------------------------------------------------

    def turn(
        self,
        user_text: str,
        *,
        author: Optional[Dict[str, Any]] = None,
        assistant_text: Optional[str] = None,
    ) -> Tuple[str, float]:
        """Drive one full host turn; returns (injected <memory-context> block, latency_ms)."""
        if not self._started:
            raise RuntimeError("FakeHost.start() must run before turn()")
        self.turn_number += 1
        self._pending_author = author
        t0 = time.perf_counter()

        author = author or {}
        tick_kwargs = {
            "author_id": author.get("id"),
            "author_name": author.get("name"),
            "author_is_bot": bool(author.get("is_bot", False)),
        }
        on_turn_start = getattr(self.provider, "on_turn_start", None)
        if on_turn_start is not None:
            def _tick() -> None:
                params = _signature_params(on_turn_start)
                if params is None or any(p.kind is p.VAR_KEYWORD for p in params.values()):
                    accepted = tick_kwargs
                else:
                    accepted = {k: v for k, v in tick_kwargs.items() if k in params}
                try:
                    on_turn_start(self.turn_number, user_text, **accepted)
                except Exception as e:  # host: fail-soft per provider
                    self._record_error(f"on_turn_start: {e}")

            self._in_host(_tick)

        # Host: trivial prompts skip prefetch entirely.
        if self._is_trivial(user_text):
            self.metrics["trivial_skips"] += 1
            block = ""
        else:
            block = self._prefetch_turn(user_text)

        injected = self._wrap_and_spill(block)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        # Host model: the block is stamped into the user row's api_content sidecar
        # and replayed byte-identically on every later request.
        user_row: Dict[str, Any] = {"role": "user", "content": user_text}
        if injected:
            user_row["api_content"] = user_text + "\n\n" + injected
        reply = assistant_text if assistant_text is not None else f"Noted: {user_text[:40]}"
        self.transcript.append(user_row)
        self.transcript.append({"role": "assistant", "content": reply})

        self.metrics["turns"] += 1
        self.metrics["prefetch_latency_ms"].append(round(latency_ms, 3))
        self.metrics["injected_chars"].append(len(injected))
        self.metrics["injected_tokens"].append(estimate_tokens(injected))
        self.metrics["cumulative_prompt_tokens"].append(self.prompt_tokens())
        self.metrics["turn_total_latency_ms"].append(round(latency_ms, 3))

        self._submit_background(self._sync_task(user_text, reply))
        return injected, latency_ms

    def _prefetch_turn(self, query: str) -> str:
        name = getattr(self.provider, "name", "provider")
        with self._prefetch_lock:
            existing = self._prefetch_threads.get(name)
            if existing is not None and existing.is_alive():
                self.metrics["prefetch_stuck_skips"] += 1
                return ""

        box: Dict[str, Any] = {}

        def _run() -> None:
            try:
                box["value"] = self.provider.prefetch(query, session_id=self._session_id) or ""
            except Exception as e:
                box["error"] = e

        thread = self._spawn_bound(_run, name=f"memory-prefetch-{name}")
        with self._prefetch_lock:
            self._prefetch_threads[name] = thread
        thread.join(EXTERNAL_PREFETCH_TIMEOUT_S)
        if thread.is_alive():
            self.metrics["prefetch_timeouts"] += 1
            logger.warning("FakeHost: prefetch timed out after %.1fs (skipped until it returns)",
                           EXTERNAL_PREFETCH_TIMEOUT_S)
            return ""
        with self._prefetch_lock:
            if self._prefetch_threads.get(name) is thread:
                self._prefetch_threads.pop(name, None)
        if "error" in box:
            self._record_error(f"prefetch: {box['error']}")
            return ""
        return box.get("value", "")

    def _wrap_and_spill(self, raw: str) -> str:
        if not raw or not raw.strip():
            return ""
        block = _vendored_wrap_block(raw)
        if len(block) > OUTPUT_SPILL_MAX_CHARS:
            self.metrics["spill_count"] += 1
            spill_dir = self.hermes_home / "hook_outputs" / self._session_id
            spill_dir.mkdir(parents=True, exist_ok=True)
            self._spill_seq += 1
            path = spill_dir / f"prefetch-{self._spill_seq}.txt"
            path.write_text(raw, encoding="utf-8")
            block = _vendored_wrap_block(
                raw[:500] + f"\n…[spilled to {path}]…\n" + raw[-500:]
            )
        return block

    def _sync_task(self, user_text: str, reply: str) -> Callable[[], None]:
        def _do() -> None:
            sync = self.provider.sync_turn
            kwargs: Dict[str, Any] = {"session_id": self._session_id}
            if _accepts(sync, "messages"):
                kwargs["messages"] = [dict(m) for m in self.transcript]
            author = self._last_author()
            if author is not None and _accepts(sync, "turn_author"):
                kwargs["turn_author"] = author
            try:
                sync(user_text, reply, **kwargs)
            except Exception as e:
                self._record_error(f"sync_turn: {e}")
            if not self._is_trivial(user_text):
                try:
                    self.provider.queue_prefetch(user_text, session_id=self._session_id)
                except Exception as e:
                    self._record_error(f"queue_prefetch: {e}")

        return _do

    def _last_author(self) -> Optional[Dict[str, Any]]:
        return getattr(self, "_pending_author", None)

    # -- FIFO background worker (host's mem-sync, single worker) ----------------

    def _submit_background(self, fn: Callable[[], None]) -> None:
        fork = self._fork_for_worker()
        self._tasks.put(lambda: fork.run(fn))

    def _fork_for_worker(self) -> contextvars.Context:
        return contextvars.copy_context()

    def _fifo_loop(self) -> None:
        while True:
            task = self._tasks.get()
            if task is None:
                return
            try:
                task()
            except Exception as e:  # pragma: no cover - tasks guard themselves
                self._record_error(f"fifo: {e}")
            finally:
                self._tasks.task_done()

    def drain(self, timeout: float = 10.0) -> bool:
        """Block until queued FIFO work has drained (False on timeout)."""
        done = threading.Event()
        self._tasks.put(done.set)
        return done.wait(timeout)

    # -- session lifecycle -------------------------------------------------------

    def new_session(self, *, new_session_id: Optional[str] = None) -> str:
        """/new: on_session_end then on_session_switch(reset) as ONE serialized FIFO task."""
        old = self._session_id
        new = new_session_id or f"{old}-next"
        snapshot = [dict(m) for m in self.transcript]

        def _boundary() -> None:
            try:
                self.provider.on_session_end(snapshot)
            except Exception as e:
                self._record_error(f"on_session_end: {e}")
            try:
                self.provider.on_session_switch(new, parent_session_id=old, reset=True, reason="new_session")
            except Exception as e:
                self._record_error(f"on_session_switch: {e}")

        self.transcript = []
        self._submit_background(_boundary)
        self._session_id = new
        self._system_block = self._in_host(lambda: self.provider.system_prompt_block() or "")
        return new

    def undo(self) -> None:
        """/undo: same session id, truncated transcript (host forwards rewound=True)."""
        def _switch() -> None:
            try:
                self.provider.on_session_switch(
                    self._session_id, parent_session_id="", reset=False, rewound=True
                )
            except Exception as e:
                self._record_error(f"on_session_switch(undo): {e}")

        self._in_host(_switch)

    def compress(self, *, evidence_messages: Optional[List[Dict[str, Any]]] = None,
                 require_checkpoint: bool = False) -> str:
        """Compression boundary: v2 evidence checkpoint, then switch reason='compression'."""
        ev = evidence_messages if evidence_messages is not None else self.evidence_snapshot()
        parts: List[str] = []
        version = getattr(self.provider, "pre_compress_checkpoint_api_version", 1)
        checkpoint_provider = version >= 2
        kwargs: Dict[str, Any] = {}
        if checkpoint_provider and _accepts(self.provider.on_pre_compress, "require_checkpoint"):
            kwargs["require_checkpoint"] = require_checkpoint

        def _pre() -> None:
            try:
                result = self.provider.on_pre_compress(ev, **kwargs)
                if result and result.strip():
                    parts.append(result)
            except Exception as e:
                self._record_error(f"on_pre_compress: {e}")
                if require_checkpoint and checkpoint_provider:
                    raise

        try:
            self._in_host(_pre)
        except Exception:
            raise
        child = f"{self._session_id}-compressed"
        old = self._session_id

        def _switch() -> None:
            try:
                self.provider.on_session_switch(child, parent_session_id=old, reset=False,
                                                reason="compression")
            except Exception as e:
                self._record_error(f"on_session_switch(compression): {e}")

        self._in_host(_switch)
        self._session_id = child
        # The host freezes the system prompt per session and REBUILDS it on compression.
        self._system_block = self._in_host(lambda: self.provider.system_prompt_block() or "")
        return "\n\n".join(parts)

    def evidence_snapshot(self) -> List[Dict[str, Any]]:
        """Host-normalized pre-compress evidence: user/assistant rows, prior summaries removed."""
        return [
            {k: v for k, v in row.items() if k in ("role", "content", "tool_calls")}
            for row in self.transcript
            if row.get("role") in ("user", "assistant")
        ]

    def delegate(self, task: str, result: str, *, child_session_id: str = "child-1") -> None:
        def _call() -> None:
            try:
                self.provider.on_delegation(task, result, child_session_id=child_session_id)
            except Exception as e:
                self._record_error(f"on_delegation: {e}")

        self._in_host(_call)

    def tool(self, name: str, args: Dict[str, Any]) -> str:
        """handle_tool_call on the agent thread — host passes NO kwargs (§2.3)."""
        self.metrics["tool_calls"] += 1
        return self._in_host(lambda: self.provider.handle_tool_call(name, dict(args)))

    # -- shutdown ----------------------------------------------------------------

    def shutdown(self) -> Dict[str, Any]:
        """Bounded FIFO drain (5 s like the host), then provider.shutdown()."""
        state: Dict[str, Any] = {"status": "drained", "abandoned": 0}
        if self._closed:
            return state
        if not self.drain(timeout=SYNC_DRAIN_TIMEOUT_S):
            state = {"status": "timed_out", "abandoned": max(1, self._tasks.qsize())}
        self._tasks.put(None)
        if self._worker.is_alive():
            self._worker.join(timeout=1.0)
        try:
            self._in_host(lambda: self.provider.shutdown())
        except Exception as e:
            self._record_error(f"shutdown: {e}")
        if self._saved_env_home is not None:
            import os

            os.environ["HERMES_HOME"] = self._saved_env_home
            self._saved_env_home = None
        self._revert_home_override()
        self._closed = True
        return state

    # -- prompt / replay accounting -----------------------------------------------

    def prompt_chars(self) -> int:
        """Size of the request "prompt": system block + every message's api_content if present."""
        total = len(self._system_block)
        for row in self.transcript:
            total += len(row.get("api_content") or str(row.get("content") or ""))
        return total

    def prompt_tokens(self) -> int:
        return estimate_tokens_size(self.prompt_chars())

    @property
    def session_id(self) -> str:
        return self._session_id

    def summary(self) -> Dict[str, Any]:
        """Scalar roll-up of the recorded metrics (p50/p95 latency, token totals)."""
        lat = sorted(self.metrics["prefetch_latency_ms"])
        tok = self.metrics["injected_tokens"]
        return {
            **{k: v for k, v in self.metrics.items() if not isinstance(v, list)},
            "turns": self.metrics["turns"],
            "prefetch_p50_ms": lat[len(lat) // 2] if lat else 0.0,
            "prefetch_p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else 0.0,
            "injected_tokens_total": sum(tok),
            "injected_tokens": list(self.metrics["injected_tokens"]),
            "cumulative_prompt_tokens": list(self.metrics["cumulative_prompt_tokens"]),
            "cumulative_prompt_tokens_at_end": (self.metrics["cumulative_prompt_tokens"][-1]
                                                if self.metrics["cumulative_prompt_tokens"] else 0),
            "errors": list(self.errors),
        }

    def _record_error(self, msg: str) -> None:
        self.errors.append(msg)
        logger.debug("FakeHost swallowed: %s", msg)


# --- token estimation (rough chars/4; deterministic, no tokenizer dependency) ----
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def estimate_tokens_size(n_chars: int) -> int:
    return max(1, n_chars // 4) if n_chars else 0


def os_environ_snapshot() -> Dict[str, str]:
    import os

    return dict(os.environ)
