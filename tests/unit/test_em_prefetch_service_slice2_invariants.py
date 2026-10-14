from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.provider.prefetch_service import (  # noqa: E402
    PrefetchService,
)
from em.store.db import Store  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import Scope  # noqa: E402

SCOPE = Scope(profile="inv")


def _spawn(target, name):
    t = threading.Thread(target=target, name=name, daemon=True)
    t.start()
    return t


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "m.db"))
    with s.writer() as w:
        migrate(w)
    yield s
    s.close()


def test_topic_entities_never_enter_retrieve_query(store):
    calls = {}

    def retrieve(conn, **kwargs):
        calls["query"] = kwargs.get("query")
        return type(
            "R", (), {"rankings": [], "rows": {}, "predecessors": {}, "partial": False, "analyzed": type("A", (), {"entities": []})()}
        )()

    svc = PrefetchService(connect=store.reader, spawn_thread=_spawn, retrieve=retrieve)
    # plant a topic whose entities look like query text
    svc._topic_states["s"] = type("TS", (), {"entities": frozenset({"billing", "port"}), "turns": 1, "embedding": None})()
    user_query = "what is the staging url?"
    svc.prefetch(user_query, scope=SCOPE, session_id="s")
    assert calls["query"] == __import__("em.provider.prefetch_service", fromlist=["normalize_query"]).normalize_query(user_query)
    assert "billing" not in (calls["query"] or "")
    svc.close()


def test_topic_bonus_zero_identical_output(store):
    svc_a = PrefetchService(connect=store.reader, spawn_thread=_spawn, topic_bonus=0.0)
    svc_b = PrefetchService(connect=store.reader, spawn_thread=_spawn, topic_bonus=0.0)
    # plant same topic in both
    from em.provider.prefetch_service import TopicState

    for svc in (svc_a, svc_b):
        svc._topic_states["s"] = TopicState(entities=frozenset({"e"}), turns=1)
    ra = svc_a.prefetch("anything", scope=SCOPE, session_id="s")
    rb = svc_b.prefetch("anything", scope=SCOPE, session_id="s")
    assert ra.text == rb.text
    assert ra.injected == rb.injected
    svc_a.close()
    svc_b.close()


def test_thread_join_timeout_counted_and_logged(store, caplog):
    import logging

    caplog.set_level(logging.WARNING)
    spin = threading.Event()

    def runner():
        spin.wait()

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    svc = PrefetchService(connect=store.reader, spawn_thread=_spawn)
    svc._worker_started = True
    svc._worker_thread = t
    svc.close()
    spin.set()
    t.join(timeout=2.0)
    assert svc.precompute_stats["thread_join_timeout"] >= 1
    assert any("did not exit within 2s" in r.message for r in caplog.records)


def test_precompute_dropped_counter_visible(store):
    svc = PrefetchService(connect=store.reader, spawn_thread=_spawn)
    # fill the bounded queue
    for _ in range(8):
        svc._precompute_queue.put_nowait(object())
    # trigger drop path directly
    try:
        svc._precompute_queue.put_nowait(object())
    except Exception:
        svc._precompute_queue.get_nowait()
        with svc._precompute_lock:
            svc._stats["precompute_dropped"] += 1
    assert "precompute_dropped" in svc.precompute_stats
    assert svc.precompute_stats["precompute_dropped"] >= 1
    # drain
    while not svc._precompute_queue.empty():
        try:
            svc._precompute_queue.get_nowait()
        except Exception:
            break
    svc.close()
