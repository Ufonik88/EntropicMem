"""EM-211 Chunk 10.3: the CLI refuses its v2-only features on a v3 store, by name.

The facade covers the provider's calls and (Chunks 10.1/10.2) the CLI's read and
maintenance calls. A handful of CLI features have **no v3 backing store at all** —
knowledge triples, the embeddings rebuild, vault projection, the shared
publish/pull log, and the v2 provenance migration. The CLI is routed onto the
facade in 10.4; without these guards those commands would then fail with an
`AttributeError`, and a stack trace is not an answer.

So each refuses up front, before `_engine()` is reached, naming the card that will
bring it. These tests are written to prove exactly that ordering: `_engine` is
monkeypatched to raise, so a test that passes is a test where the guard fired
first. That is what makes them meaningful *now*, while 10.0's coarser refusal is
still in force — after 10.4 these guards are the only thing standing between a v3
store and the AttributeError.

Rules: invented data only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
FIXTURES = REPO / "tests" / "fixtures" / "db"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import entropicmem  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.migrations import migrate  # noqa: E402


def make_v3(tmp_path: Path) -> Path:
    path = tmp_path / "v3" / "memory.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(path))
    try:
        with store.writer() as conn:
            migrate(conn)
    finally:
        store.close()
    return path


def make_v2(tmp_path: Path) -> Path:
    import shutil

    dest = tmp_path / "v2" / "memory.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "v2_7_0.db", dest)
    return dest


@pytest.fixture
def engine_bomb(monkeypatch):
    """Make reaching `_engine()` a test failure: the guard must fire first."""

    def _boom(*a, **k):
        raise AssertionError("_engine() was reached; the refusal must come first")

    monkeypatch.setattr(entropicmem, "_engine", _boom)


def on_v3(monkeypatch, path: Path):
    monkeypatch.setenv("ENTROPICMEM_MEMORY_DB", str(path))


# --- the helper ---------------------------------------------------------------


def test_store_is_v3_detects_each_store(tmp_path, monkeypatch):
    on_v3(monkeypatch, make_v3(tmp_path))
    assert entropicmem._store_is_v3() is True
    on_v3(monkeypatch, make_v2(tmp_path))
    assert entropicmem._store_is_v3() is False
    on_v3(monkeypatch, tmp_path / "does-not-exist-yet.db")
    assert entropicmem._store_is_v3() is False


def test_a_v2_store_is_never_refused(tmp_path, monkeypatch):
    """Every guard must be inert on the line users are on today."""
    on_v3(monkeypatch, make_v2(tmp_path))
    for feature in entropicmem._V3_UNAVAILABLE:
        entropicmem._refuse_on_v3(feature)  # must not raise


def test_the_refusal_names_the_card(tmp_path, monkeypatch):
    on_v3(monkeypatch, make_v3(tmp_path))
    with pytest.raises(SystemExit) as exc:
        entropicmem._refuse_on_v3("triple")
    message = str(exc.value)
    assert "v3 store" in message and "S5" in message, message


# --- every guarded command ----------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda a: entropicmem.cmd_triple(a),
        lambda a: entropicmem.cmd_embed(a),
        lambda a: entropicmem.cmd_memory(a),
        lambda a: entropicmem.cmd_publish(a),
        lambda a: entropicmem.cmd_pull(a),
        lambda a: entropicmem.cmd_migrate(a),
        # `cmd_recall` is deliberately absent: plain recall is *ported* and must
        # not refuse. Only its two v2-only forms do, tested separately below.
    ],
)
def test_each_v2_only_command_refuses_on_v3(call, tmp_path, monkeypatch, engine_bomb):
    """`_engine` raises if reached, so passing proves the order."""
    on_v3(monkeypatch, make_v3(tmp_path))
    args = argparse.Namespace(
        triple_command="stats",
        embed_command=None,
        rebuild=True,          # cmd_embed's refused branch
        memory_command="project",
        scope="own",
        related=None,
        query="anything",
        top_k=5,
        domain=None,
        status=False,
    )
    with pytest.raises(SystemExit) as exc:
        call(args)
    assert "v3 store" in str(exc.value)


def test_recall_with_a_shared_scope_refuses_on_v3(tmp_path, monkeypatch, engine_bomb):
    on_v3(monkeypatch, make_v3(tmp_path))
    args = argparse.Namespace(scope="shared", query="anything", related=None, top_k=5, domain=None)
    with pytest.raises(SystemExit) as exc:
        entropicmem.cmd_recall(args)
    assert "S5" in str(exc.value)


def test_recall_with_related_refuses_on_v3(tmp_path, monkeypatch, engine_bomb):
    on_v3(monkeypatch, make_v3(tmp_path))
    args = argparse.Namespace(scope="own", query=None, related="abcdef0123456789", top_k=5)
    with pytest.raises(SystemExit) as exc:
        entropicmem.cmd_recall(args)
    assert "S6" in str(exc.value)


def test_every_refusal_message_states_a_trigger(tmp_path, monkeypatch):
    """A refusal that does not say when it lifts is just a wall."""
    on_v3(monkeypatch, make_v3(tmp_path))
    for feature in entropicmem._V3_UNAVAILABLE:
        with pytest.raises(SystemExit) as exc:
            entropicmem._refuse_on_v3(feature)
        assert any(card in str(exc.value) for card in ("S3", "S5", "S6", "migration")), (
            feature, str(exc.value)
        )
