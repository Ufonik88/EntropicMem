"""A selected backends with no key warns once, instead of degrading silently.

The wire behaviour is already pinned next door (`test_em_embeddings_key_scope.py`):
no scope means no `Authorization` header, so the endpoint refuses on the first
call and the caller falls back to lexical. That refusal is the correct failure,
but it is only *visible* if something says so: the per-call log line is
``debug``, which is off in any normal deployment, so a key that is missing or
mis-scoped looked exactly like a box with no embeddings configured at all.

One warning per backend instance, not per call: the condition is a
configuration fact that cannot fix itself mid-session, and a warning on every
embed would be noise on a hot path.

Invented data only: Acme.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.embeddings import backends  # noqa: E402
from em.embeddings.backends import OpenAICompatBackend  # noqa: E402


def _stub_wire(monkeypatch) -> list[str]:
    sent: list[str] = []

    def fake_post(url, payload, headers, timeout):
        sent.append(headers.get("Authorization", ""))
        return {"data": [{"embedding": [0.1, 0.2]} for _ in payload["input"]]}

    monkeypatch.setattr(backends, "_post_json", fake_post)
    return sent


def _keyless(monkeypatch) -> OpenAICompatBackend:
    monkeypatch.setattr(backends, "get_secret", lambda name, default="": default)
    return OpenAICompatBackend(base_url="https://acme.invalid/v1")


def _warnings(records) -> list[str]:
    return [r.getMessage() for r in records if r.levelno == logging.WARNING]


def test_a_keyless_backend_warns_on_the_first_request(monkeypatch, caplog):
    _stub_wire(monkeypatch)
    backend = _keyless(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="em.embeddings.backends"):
        backend.embed(["hello"])

    said = _warnings(caplog.records)
    assert len(said) == 1, f"expected exactly one warning, got {said}"
    assert "no entropicmem_embeddings_api_key" in said[0].lower()
    # The message must name the variable, or the reader cannot act on it.
    assert "ENTROPICMEM_EMBEDDINGS_API_KEY" in said[0]


def test_the_warning_is_once_per_instance_not_per_call(monkeypatch, caplog):
    _stub_wire(monkeypatch)
    backend = _keyless(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="em.embeddings.backends"):
        for _ in range(3):
            backend.embed(["hello"])

    assert len(_warnings(caplog.records)) == 1, "a hot path must not repeat the same warning"


def test_a_keyed_backend_says_nothing(monkeypatch, caplog):
    _stub_wire(monkeypatch)
    monkeypatch.setattr(backends, "get_secret", lambda name, default="": "scoped-key")
    backend = OpenAICompatBackend(base_url="https://acme.invalid/v1")

    with caplog.at_level(logging.WARNING, logger="em.embeddings.backends"):
        backend.embed(["hello"])

    assert _warnings(caplog.records) == []


def test_the_warning_fires_before_the_request_is_attempted(monkeypatch, caplog):
    """A reader must see the cause even when the endpoint raises on contact."""
    calls: list[int] = []

    def refusing_post(url, payload, headers, timeout):
        calls.append(1)
        raise OSError("simulated 401 from the endpoint")

    monkeypatch.setattr(backends, "_post_json", refusing_post)
    backend = _keyless(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="em.embeddings.backends"):
        with pytest.raises(OSError):
            backend.embed(["hello"])

    assert len(_warnings(caplog.records)) == 1, "the cause must be logged, not only the symptom"
    assert calls == [1], "the request still goes out; the warning is not a substitute for it"
