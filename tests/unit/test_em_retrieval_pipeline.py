"""Pipeline overrides — the calibration seam (EM-306).

``pipeline.retrieve`` takes optional ``gate_config`` and ``rank_weights`` so the tune
harness can measure a candidate without a second pipeline. Two properties matter and are
pinned here:

* **the defaults stay the spec's** — nothing the provider or the eval adapter does
  changes when no override is passed;
* **an override actually reaches the stage it names** — a gate override that stopped at
  the door would make every tuned number a lie about a pipeline nobody ran.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.retrieval import fusion, gate, pipeline  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

SCOPE = Scope(profile="pipeline-overrides")
QUERY = "where does the user live?"


@pytest.fixture()
def conn(tmp_path):
    store = Store(str(tmp_path / "memory.db"))
    with store.writer() as writer:
        migrate(writer)
    with store.transaction() as writer:
        result = MemoryStore(writer).add(
            MemoryDraft(
                content="The user's name is Alice Example and she lives in Initech",
                importance=0.9,
                source="agent",
                status="active",
            ),
            scope=SCOPE,
            actor="test",
        )
        assert result.ok
    yield store.reader()
    store.close()


def test_the_defaults_are_the_specs(conn, monkeypatch):
    """No override means ``rank`` sees ``None`` and the gate sees its default config —
    the shapes every existing caller relies on."""
    seen = {}
    real_rank = fusion.rank

    def spy_rank(fused, features, *, now, weights=None, flags=None):
        seen["weights"] = weights
        return real_rank(fused, features, now=now, weights=weights, flags=flags)

    monkeypatch.setattr(pipeline.fusion, "rank", spy_rank)
    outcome = pipeline.retrieve(conn, scope=SCOPE, query=QUERY, with_gate=True)
    assert outcome.rankings, "the on-topic memory must survive the default gate"
    assert seen["weights"] is None


def test_a_passed_gate_config_reaches_the_gate(conn):
    default = pipeline.retrieve(conn, scope=SCOPE, query=QUERY, with_gate=True)
    assert default.rankings, "the default gate must keep an on-topic hit"

    strict = pipeline.retrieve(
        conn,
        scope=SCOPE,
        query=QUERY,
        with_gate=True,
        gate_config=gate.GateConfig(min_score=1.1),
    )
    assert strict.rankings == [], "min_score above the scale must drop the unpinned hit"


def test_a_passed_rank_weights_reaches_rank(conn, monkeypatch):
    seen = {}
    real_rank = fusion.rank

    def spy_rank(fused, features, *, now, weights=None, flags=None):
        seen["weights"] = weights
        return real_rank(fused, features, now=now, weights=weights, flags=flags)

    monkeypatch.setattr(pipeline.fusion, "rank", spy_rank)
    custom = fusion.RankWeights(
        rrf=0.70, importance=0.10, recency=0.08, confidence=0.08, feedback=0.04
    )
    pipeline.retrieve(conn, scope=SCOPE, query=QUERY, rank_weights=custom)
    assert seen["weights"] is custom, "the weights must arrive, not a copy or a default"
