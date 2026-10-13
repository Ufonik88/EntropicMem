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
import time
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


# --- the EM-403 execution seams (deadline / order / runner) ----------------
#
# §4.2 runs the generators in priority order under a deadline and marks the
# result `partial` when the deadline passes. These three optional seams are how
# the prefetch service asks for exactly that without a second pipeline; with
# none of them passed, `retrieve` must behave exactly as it always has.


def test_the_default_run_is_whole_and_unmarked(conn):
    outcome = pipeline.retrieve(conn, scope=SCOPE, query=QUERY, with_gate=True)
    assert outcome.rankings, "the on-topic memory must survive the default gate"
    assert outcome.partial is False
    assert outcome.generators_skipped == ()


def test_an_expired_deadline_skips_every_generator_and_marks_partial(conn):
    ran = []

    def spy(name, fn, ctx):
        ran.append(name)
        return fn(ctx)

    outcome = pipeline.retrieve(
        conn,
        scope=SCOPE,
        query=QUERY,
        with_gate=True,
        deadline=0.0,
        generator_runner=spy,
    )
    assert ran == [], "a generator whose deadline has passed must do no work"
    assert outcome.partial is True
    assert tuple(outcome.generators_skipped) == tuple(pipeline.candidates.GENERATORS)
    assert outcome.rankings == []


def test_the_deadline_reaches_the_generator_context(conn):
    seen = {}

    def spy(name, fn, ctx):
        seen[name] = ctx.deadline
        return fn(ctx)

    far = time.monotonic() + 60.0
    pipeline.retrieve(conn, scope=SCOPE, query=QUERY, deadline=far, generator_runner=spy)
    assert seen, "the generators must have run"
    assert all(value == far for value in seen.values())


def test_a_runner_may_abandon_a_call_and_the_rest_is_skipped(conn):
    seen = []

    def runner(name, fn, ctx):
        seen.append(name)
        if name == "entity":
            raise pipeline.GeneratorDeadline("entity")
        return fn(ctx)

    outcome = pipeline.retrieve(
        conn,
        scope=SCOPE,
        query=QUERY,
        with_gate=True,
        generator_order=("pinned", "bm25", "entity", "episodic"),
        generator_runner=runner,
    )
    assert seen == ["pinned", "bm25", "entity"]
    assert outcome.partial is True
    assert tuple(outcome.generators_skipped) == ("entity", "episodic")
    assert outcome.rankings, "the generators that finished must still be fused"


def test_generator_order_is_the_run_order(conn):
    seen = []

    def spy(name, fn, ctx):
        seen.append(name)
        return fn(ctx)

    pipeline.retrieve(
        conn,
        scope=SCOPE,
        query=QUERY,
        generator_order=("pinned", "bm25", "recent"),
        generator_runner=spy,
    )
    assert seen == ["pinned", "bm25", "recent"]


def test_an_unknown_generator_name_is_refused(conn):
    with pytest.raises(ValueError):
        pipeline.retrieve(
            conn, scope=SCOPE, query=QUERY, generator_order=("bm25", "telepathy")
        )
