"""The embeddings key is resolved per call, not frozen when the client is built.

Regression for the reply on the 3.0.1 post: the key moved to
``agent.secret_scope`` in 3.0.1, but it was read once in ``__init__`` and stored
on the backend. A host that builds the client under profile A and later serves a
turn for profile B on the same instance still sends A's key, because the object
outlives the scope it was built in. ``EmbeddingService``'s own docstring invited
exactly that shape ("Construct once per process/worker").

The contract: an explicit constructor key and an injected ``env`` mapping still
win (the injectable seam), and everything else follows the scope as it is when
the request is made.

Invented data only: Acme.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.embeddings import backends  # noqa: E402
from em.embeddings.backends import OpenAICompatBackend  # noqa: E402
from em.embeddings.service import EmbeddingService  # noqa: E402

KEY = "ENTROPICMEM_EMBEDDINGS_API_KEY"


class _Scope:
    """A stand-in for the host's profile secret scope: one value, switchable."""

    def __init__(self, value: str) -> None:
        self.value = value
        self.seen: list[str] = []

    def __call__(self, name, default=""):
        self.seen.append(name)
        return self.value


def _capture_wire(monkeypatch) -> list[str]:
    """Stub the HTTP hop and record each Authorization header sent."""
    sent: list[str] = []

    def fake_post(url, payload, headers, timeout):
        sent.append(headers.get("Authorization", ""))
        return {
            "data": [{"embedding": [0.1, 0.2]} for _ in payload["input"]],
            "model": "m",
        }

    monkeypatch.setattr(backends, "_post_json", fake_post)
    return sent


def test_a_client_built_under_one_profile_uses_the_next_profiles_key(monkeypatch):
    scope = _Scope("key-A")
    monkeypatch.setattr(backends, "get_secret", scope)
    sent = _capture_wire(monkeypatch)

    backend = OpenAICompatBackend(base_url="https://acme.invalid/v1")
    service = EmbeddingService(":memory:", backend=backend, model="m")

    service.embed_texts(["under profile A"])

    scope.value = "key-B"  # the same process now serves profile B
    service.embed_texts(["under profile B"])

    assert sent == ["Bearer key-A", "Bearer key-B"], (
        "one cached client must follow the scope at request time, "
        f"not the scope it was constructed in: {sent}"
    )


def test_the_constructor_key_still_wins_after_a_scope_change(monkeypatch):
    scope = _Scope("scoped-key")
    monkeypatch.setattr(backends, "get_secret", scope)
    sent = _capture_wire(monkeypatch)

    service = EmbeddingService(
        ":memory:",
        backend=OpenAICompatBackend(base_url="https://acme.invalid/v1", api_key="explicit-key"),
        model="m",
    )
    scope.value = "another-profile-key"
    service.embed_texts(["x"])

    assert sent == ["Bearer explicit-key"]


def test_an_injected_env_mapping_still_wins_after_a_scope_change(monkeypatch):
    scope = _Scope("scoped-key")
    monkeypatch.setattr(backends, "get_secret", scope)
    sent = _capture_wire(monkeypatch)

    service = EmbeddingService(
        ":memory:",
        backend=OpenAICompatBackend(
            env={
                "ENTROPICMEM_EMBEDDINGS_BASE_URL": "https://acme.invalid/v1",
                KEY: "injected-key",
            }
        ),
        model="m",
    )
    scope.value = "another-profile-key"
    service.embed_texts(["x"])

    assert sent == ["Bearer injected-key"]


def test_an_unscoped_host_sends_no_authorization_header(monkeypatch):
    """Fail closed on the wire: no scope means no key, never the launch profile's."""
    sent = _capture_wire(monkeypatch)
    monkeypatch.setenv(KEY, "launch-profile-key")  # present in the process env
    monkeypatch.setattr(backends, "get_secret", lambda name, default="": default)

    service = EmbeddingService(
        ":memory:",
        backend=OpenAICompatBackend(base_url="https://acme.invalid/v1"),
        model="m",
    )
    service.embed_texts(["x"])

    assert sent == [""], "a missing scope must not fall back to a process environment key"
