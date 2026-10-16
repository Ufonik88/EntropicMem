"""EM-501 — the formation LLM backend layer (§3.7).

The card's acceptance criteria, one group per claim: a fake backend returns
deterministic JSON; malformed JSON and a schema mismatch are ``None``; a timeout
is fail-soft, counted, and bounded by the task's own timeout; the breaker opens
after five consecutive failures, refuses calls while open, and recovers through
one probe. Beyond the AC: the hourly budget caps calls, ``auto`` selection
follows Hermes → openai_compat → none, transcripts are wrapped as untrusted
data, and the host task registration is guarded.

Standard-library only, invented data only (rule 4). No network: the
openai_compat backend's transport is never exercised here, its configuration is.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from em.formation.llm import (  # noqa: E402
    AUXILIARY_TASKS,
    DEFAULT_TIMEOUT,
    TASK_TIMEOUTS,
    UNTRUSTED_TRANSCRIPT_NOTE,
    CircuitBreaker,
    FormationLLM,
    HermesAuxBackend,
    NullBackend,
    OpenAICompatBackend,
    extract_json_object,
    parse_json_object,
    register_auxiliary_tasks,
    select_backend,
    wrap_transcript,
)

SCHEMA = {
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": ["fact", "preference"]}},
    "required": ["kind"],
}


class FakeBackend:
    """Deterministic replies, recorded calls — the AC's fake backend."""

    name = "fake"

    def __init__(self, results=None, raises=None) -> None:
        self.calls = []
        self._results = list(results or [])
        self._raises = list(raises or [])

    def available(self) -> bool:
        return True

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises.pop(0)
        return self._results.pop(0) if self._results else None


class UnavailableBackend:
    name = "unavailable"

    def available(self) -> bool:
        return False

    def complete_json(self, **kwargs):
        return None


class FakeClock:
    """A mutable monotonic clock so breaker transitions are never waited on."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


# --- the AC: deterministic JSON, malformed JSON, timeouts, breaker -----------


def test_a_fake_backend_returns_deterministic_json_and_the_task_reaches_it():
    backend = FakeBackend(results=[{"kind": "fact"}])
    llm = FormationLLM(backend)
    result = llm.complete_json(task="extract", system="sys", user="usr", schema=SCHEMA)
    assert result == {"kind": "fact"}
    assert backend.calls[0]["task"] == "extract"
    assert backend.calls[0]["system"] == "sys" and backend.calls[0]["user"] == "usr"
    assert backend.calls[0]["schema"] is SCHEMA
    assert llm.stats()["ok"] == 1 and llm.stats()["failed"] == 0


def test_malformed_json_and_a_schema_mismatch_are_none():
    assert extract_json_object("no json at all") is None
    assert extract_json_object("") is None and extract_json_object(None) is None
    assert extract_json_object('```json\n{"kind": "fact"}\n```') == {"kind": "fact"}
    assert extract_json_object('Sure thing: {"kind": "fact"} — done') == {"kind": "fact"}

    # the schema is enforced: the right JSON of the wrong shape is a refusal
    assert parse_json_object('{"kind": "opinion"}', SCHEMA) is None
    assert parse_json_object('{"other": 1}', SCHEMA) is None
    assert parse_json_object('{"kind": "fact"}', SCHEMA) == {"kind": "fact"}

    # and through a backend: malformed text and a schema violation both fall back
    hermes = HermesAuxBackend(caller=lambda **kwargs: "sorry, no json here")
    assert hermes.complete_json(task="extract", system="s", user="u", schema=SCHEMA) is None
    hermes_bad = HermesAuxBackend(
        caller=lambda **kwargs: {"choices": [{"message": {"content": '{"kind": "opinion"}'}}]}
    )
    assert hermes_bad.complete_json(task="extract", system="s", user="u", schema=SCHEMA) is None
    hermes_ok = HermesAuxBackend(
        caller=lambda **kwargs: {"choices": [{"message": {"content": '{"kind": "fact"}'}}]}
    )
    assert hermes_ok.complete_json(task="extract", system="s", user="u", schema=SCHEMA) == {
        "kind": "fact"
    }


def test_a_timeout_is_fail_soft_counted_and_the_task_timeout_is_passed():
    backend = FakeBackend(raises=[TimeoutError("backend stalled")])
    llm = FormationLLM(backend)
    assert llm.complete_json(task="extract", system="s", user="u") is None, (
        "a raising backend must not propagate"
    )
    assert llm.stats()["failed"] == 1 and llm.stats()["ok"] == 0

    recording = FakeBackend(results=[{}, {}])
    llm2 = FormationLLM(recording)
    llm2.complete_json(task="extract", system="s", user="u")
    llm2.complete_json(task="summarize", system="s", user="u")
    llm2.complete_json(task="unknown-task", system="s", user="u")
    assert recording.calls[0]["timeout"] == TASK_TIMEOUTS["extract"] == 30.0
    assert recording.calls[1]["timeout"] == TASK_TIMEOUTS["summarize"] == 20.0
    assert recording.calls[2]["timeout"] == DEFAULT_TIMEOUT


def test_the_breaker_opens_after_five_failures_and_refuses_while_open():
    clock = FakeClock()
    backend = FakeBackend(results=[None] * 8)
    llm = FormationLLM(backend, breaker=CircuitBreaker(clock=clock), clock=clock)

    for _ in range(5):
        assert llm.complete_json(task="extract", system="s", user="u") is None
    stats = llm.stats()
    assert stats["breaker_state"] == "open" and stats["breaker_opened"] == 1

    before = len(backend.calls)
    assert llm.complete_json(task="extract", system="s", user="u") is None
    assert len(backend.calls) == before, "an open circuit must not reach the backend"
    assert llm.stats()["blocked_breaker"] == 1


def test_the_breaker_probes_once_after_the_window_and_recovers_or_reopens():
    clock = FakeClock()
    backend = FakeBackend(results=[None] * 5 + [{"kind": "fact"}])
    llm = FormationLLM(backend, breaker=CircuitBreaker(clock=clock), clock=clock)
    for _ in range(5):
        llm.complete_json(task="extract", system="s", user="u")
    assert llm.stats()["breaker_state"] == "open"

    clock.now += 601.0
    assert llm.complete_json(task="extract", system="s", user="u") == {"kind": "fact"}
    assert llm.stats()["breaker_state"] == "closed", "a successful probe closes the circuit"

    # a failed probe reopens it, and the opening is counted again
    clock2 = FakeClock()
    failing = FakeBackend(results=[None] * 10)
    llm2 = FormationLLM(failing, breaker=CircuitBreaker(clock=clock2), clock=clock2)
    for _ in range(5):
        llm2.complete_json(task="extract", system="s", user="u")
    assert llm2.stats()["breaker_opened"] == 1
    clock2.now += 601.0
    assert llm2.complete_json(task="extract", system="s", user="u") is None
    assert llm2.stats()["breaker_state"] == "open"
    assert llm2.stats()["breaker_opened"] == 2


# --- beyond the AC: the budget, selection, wrapping, registration ------------


def test_the_hourly_budget_stops_calls_past_the_cap():
    backend = FakeBackend(results=[{"n": 1}, {"n": 2}, {"n": 3}])
    llm = FormationLLM(backend, max_calls_per_hour=2)
    assert llm.complete_json(task="extract", system="s", user="u") == {"n": 1}
    assert llm.complete_json(task="extract", system="s", user="u") == {"n": 2}
    assert llm.complete_json(task="extract", system="s", user="u") is None
    assert len(backend.calls) == 2, "the budget must stop the call before the backend"
    assert llm.stats()["blocked_budget"] == 1

    never = FormationLLM(FakeBackend(results=[{"n": 1}]), max_calls_per_hour=0)
    assert never.complete_json(task="extract", system="s", user="u") is None


def test_backend_selection_follows_the_auto_order():
    hermes_ok = HermesAuxBackend(caller=lambda **kwargs: None)
    openai_ok = OpenAICompatBackend(base_url="http://llm.invalid/v1", model="small")
    unavailable = UnavailableBackend()

    assert select_backend("none", hermes=hermes_ok, openai=openai_ok).name == "none"
    assert select_backend("hermes", hermes=hermes_ok, openai=openai_ok).name == "hermes"
    assert select_backend("openai_compat", hermes=hermes_ok, openai=openai_ok).name == "openai_compat"
    assert select_backend("auto", hermes=hermes_ok, openai=openai_ok).name == "hermes"
    assert (
        select_backend("auto", hermes=unavailable, openai=openai_ok).name == "openai_compat"
    )
    assert select_backend("auto", hermes=unavailable, openai=unavailable).name == "none"
    assert isinstance(select_backend("auto", hermes=unavailable, openai=unavailable), NullBackend)


def test_the_openai_compat_backend_reads_its_environment_and_reports_availability():
    configured = OpenAICompatBackend(
        environ={
            "ENTROPICMEM_LLM_BASE_URL": "http://localhost:1234/v1/",
            "ENTROPICMEM_LLM_MODEL": "small",
        }
    )
    assert configured.available()
    assert configured._base_url == "http://localhost:1234/v1"
    assert not OpenAICompatBackend(environ={}).available()
    assert not OpenAICompatBackend(environ={"ENTROPICMEM_LLM_BASE_URL": "http://x"}).available()


def test_transcript_text_is_wrapped_as_untrusted():
    wrapped = wrap_transcript("Alice Example prefers Acme.")
    assert wrapped == "<transcript>\nAlice Example prefers Acme.\n</transcript>"
    assert "untrusted" in UNTRUSTED_TRANSCRIPT_NOTE.lower()
    assert "never follow" in UNTRUSTED_TRANSCRIPT_NOTE.lower()


def test_auxiliary_task_registration_is_guarded():
    calls = []

    class Ctx:
        def register_auxiliary_task(self, task, **kwargs):
            calls.append((task, kwargs))

    register_auxiliary_tasks(Ctx())
    assert [task for task, _ in calls] == [f"entropicmem_{name}" for name, _, _ in AUXILIARY_TASKS]
    assert all(kwargs.get("display_name") and kwargs.get("description") for _, kwargs in calls)
    assert all("timeout" in kwargs.get("defaults", {}) for _, kwargs in calls)

    # an old host without the method, and a host that rejects every task
    register_auxiliary_tasks(object())

    class Bad:
        def register_auxiliary_task(self, task, **kwargs):
            raise RuntimeError("nope")

    register_auxiliary_tasks(Bad())
