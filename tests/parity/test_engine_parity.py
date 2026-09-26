"""EM-211 foundation: behavioural parity suite for provider-facing engines.

Every test here runs against every engine in ``ENGINES``: today the v2
``MemoryEngine``, and after EM-211 the v3 facade too. Each test pins one
behaviour from ``em.facade.contract.BEHAVIOURS``, the semantics the Hermes
provider depends on that no signature shows. The facade is done when it passes
this whole file unchanged.

Rules for editing:

- Assert behaviour the provider relies on, never an implementation detail
  (exact ranking scores, id format, table names).
- A test that the facade cannot pass for a principled reason is not deleted or
  xfailed quietly. Change ``BEHAVIOURS`` and the provider together, and say so
  in CHANGELOG.
- Only invented data: Acme/Globex/Initech, Alice/Bob Example, example.com.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.facade.contract import BEHAVIOURS  # noqa: E402

COVERED: dict[str, list[str]] = {}


def behaviour(key: str):
    """Tie a test to a BEHAVIOURS id (checked by test_every_behaviour_is_covered)."""
    assert key in BEHAVIOURS, f"unknown behaviour {key!r}"

    def mark(fn):
        COVERED.setdefault(key, []).append(fn.__name__)
        return fn

    return mark


def _v2(tmp_path: Path):
    from memory_engine import MemoryEngine

    return MemoryEngine(tmp_path / "memory.db", profile_id="default", hermes_home=tmp_path / "hermes")


#: name -> factory(tmp_path) returning an engine usable as a context manager.
#: EM-211: add ("v3-facade", _v3) here.
ENGINES: dict[str, Callable[[Path], object]] = {"v2": _v2}


@pytest.fixture(params=sorted(ENGINES))
def engine(request, tmp_path):
    eng = ENGINES[request.param](tmp_path)
    with eng as e:
        yield e


def _make_id(content: str) -> str:
    from memory_engine import StoredFact

    return StoredFact.make_id(content)


SEED = [
    ("Acme deploys the billing service with a blue-green rollout.", "Knowledge"),
    ("Globex keeps its staging cluster in the Frankfurt region.", "Knowledge"),
    ("Alice Example prefers short status updates on Fridays.", "People"),
    ("Initech rotates API credentials every ninety days.", "Knowledge"),
    ("Bob Example owns the nightly backup verification job.", "People"),
    ("The Acme billing service exposes metrics on port 9102.", "Knowledge"),
]


def _seed(engine) -> list[str]:
    return [engine.remember(content=c, title=c[:40], domain=d, source="agent") for c, d in SEED]


# --- identity -------------------------------------------------------------


@behaviour("id-from-content")
def test_get_fact_by_content_derived_id(engine):
    content = "Mirrored: Alice Example uses the example.com staging tenant."
    engine.remember(content=content, title=content[:60], domain="People", tags=["mirrored", "user"], source="built_in_memory")
    fact = engine.get_fact(_make_id(content))
    assert fact is not None, "the provider's mirror lookup (make_id(content)) must resolve"
    assert fact.content == content
    assert "mirrored" in fact.tags


@behaviour("remember-idempotent")
def test_remembering_the_same_content_twice_keeps_one_row(engine):
    content = "Acme's on-call rotation changes every Monday."
    a = engine.remember(content=content)
    before = engine.stats()["fact_count"]
    b = engine.remember(content=content)
    assert a == b
    assert engine.stats()["fact_count"] == before


@behaviour("tags-are-a-list")
def test_tags_round_trip_as_a_list(engine):
    fid = engine.remember(content="Globex uses weekly release trains.", tags=["mirrored", "memory"])
    fact = engine.get_fact(fid)
    assert isinstance(fact.tags, list)
    assert set(fact.tags) >= {"mirrored", "memory"}


# --- forget ---------------------------------------------------------------


@behaviour("forget-needs-confirm")
def test_forget_requires_confirmation(engine):
    fid = engine.remember(content="Initech archives logs after 400 days.")
    with pytest.raises(ValueError):
        engine.forget(fid)
    assert engine.get_fact(fid) is not None, "an unconfirmed forget must delete nothing"
    assert engine.forget(fid, confirm=True) is True
    assert engine.get_fact(fid) is None
    assert engine.forget(fid, confirm=True) is False


# --- recall ---------------------------------------------------------------


@behaviour("scores-in-unit-range")
def test_recall_with_relevance_is_scored_sorted_and_filtered(engine):
    _seed(engine)
    results = engine.recall_with_relevance("Acme billing service", top_k=5, min_relevance=0.05)
    assert results, "a query matching two seeded facts must return something"
    scores = [r.relevance_score for r in results]
    assert all(0.0 <= s <= 1.0 for s in scores), scores
    assert scores == sorted(scores, reverse=True)
    assert all(s >= 0.05 for s in scores)
    assert all(isinstance(r.why_retrieved, list) for r in results)
    assert "billing" in results[0].content.lower()


@behaviour("scores-in-unit-range")
def test_recall_hybrid_without_embeddings_still_answers(engine):
    _seed(engine)
    results = engine.recall_hybrid("staging cluster region", top_k=3, fts_weight=0.6, vec_weight=0.4, expand_links=False)
    assert results and "Frankfurt" in results[0].content
    assert all(0.0 <= r.relevance_score <= 1.0 for r in results)


def test_recall_of_an_unrelated_query_returns_nothing_relevant(engine):
    _seed(engine)
    results = engine.recall_with_relevance("zzqx nonexistent vocabulary", top_k=5, min_relevance=0.35)
    assert results == []


# --- touch ----------------------------------------------------------------


@behaviour("touch-counts")
def test_touch_refreshes_last_accessed(engine):
    ids = _seed(engine)[:2]
    before = [engine.get_fact(i).last_accessed for i in ids]
    time.sleep(0.01)  # timestamps have sub-second precision in both engines
    assert engine.touch(ids + ["no-such-id"]) == 2
    after = [engine.get_fact(i).last_accessed for i in ids]
    assert all(a and a != b for a, b in zip(after, before)), (before, after)
    assert engine.touch([]) == 0


# --- episodes -------------------------------------------------------------


@behaviour("episode-waves-monotonic")
def test_episode_waves_count_up_from_one(engine):
    base = "ep_sess_parity"
    assert engine.next_episode_wave(base) == 1
    engine.add_episode(title="Wave 1", summary="Discussed the Acme rollout.", source_session="parity", episode_id=f"{base}_w1")
    engine.add_episode(title="Wave 2", summary="Reviewed the Globex region move.", source_session="parity", episode_id=f"{base}_w2")
    assert engine.next_episode_wave(base) == 3


# --- lifecycle ------------------------------------------------------------


@behaviour("context-manager-releases")
def test_engine_can_be_reopened_after_an_exception_inside_with(tmp_path):
    for name, factory in ENGINES.items():
        path = tmp_path / name
        path.mkdir()
        with pytest.raises(RuntimeError):
            with factory(path) as e:
                e.remember(content="Acme uses feature flags for launches.")
                raise RuntimeError("boom")
        with factory(path) as e:  # the write lock was released
            e.remember(content="Globex uses canary deploys.")
            assert e.stats()["fact_count"] == 2


def test_stats_and_consolidate_dry_run_shapes(engine):
    _seed(engine)
    assert engine.stats()["fact_count"] == len(SEED)
    report = engine.consolidate(max_age_days=90, min_access_count=0, dry_run=True, confirm=False, evergreen_domains=["People"])
    assert isinstance(report, dict)
    assert engine.stats()["fact_count"] == len(SEED), "a dry run must not change anything"


def test_extract_and_store_and_prune_pending_are_safe_on_empty_input(engine):
    assert engine.extract_and_store(user_text="", assistant_text="", session_id="parity") == []
    assert engine.prune_pending(older_than_days=30) >= 0


# --- coverage of the contract ---------------------------------------------


def test_every_behaviour_is_covered():
    open_items = {"mirror-scan"}  # documented as OPEN in BEHAVIOURS until EM-211
    missing = sorted(set(BEHAVIOURS) - set(COVERED) - open_items)
    assert not missing, f"behaviours with no parity test: {missing}"
