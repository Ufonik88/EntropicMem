"""EM-402's evaluation half: the `multi_user` isolation category (§3.5).

The card's AC — "multi_user eval category = 1.0" — is the **isolation**
reading, ruled by the owner on 2026-10-13: user X's private fact must never
appear for user Y. That is what these tests measure at the layer the category
runs on:

* the dataset carries an asker (``Turn.as_user``) and a sensitivity
  (``Memory.sensitivity``) as optional fields — the frozen suites' files are
  byte-identical and parse exactly as before;
* ``score_turn`` hands the turn to the adapter before it queries, so a scoped
  adapter answers as the asker;
* the v3 adapter loads ``scope_user`` and answers under the asker's scope —
  one user's rows never reach another user's search hits or prefetch block,
  and owner-only rows never reach a non-owner.

The category itself lives in ``evals/datasets_multi_user/isolation.jsonl`` and
is scored by ``python -m evals run --suite multi_user --adapter v3``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import datasets  # noqa: E402
from evals.adapters.base import AdapterBase, EvalHandle  # noqa: E402
from evals.adapters.engine_v3 import EngineV3Adapter  # noqa: E402
from evals.dataset import Scenario, Turn, load_scenarios, parse_scenario  # noqa: E402
from evals.runner import score_turn  # noqa: E402

# -- the dataset fields -------------------------------------------------------


def test_a_turn_may_name_an_asker_and_a_memory_a_sensitivity():
    sc = parse_scenario({
        "id": "s1", "category": "multi_user",
        "memories": [{"content": "Acme deploys on Tuesdays", "scope_user": "u-a",
                      "sensitivity": "sensitive"}],
        "turns": [{"query": "when?", "as_user": "u-a"}],
    })
    assert sc.memories[0].scope_user == "u-a"
    assert sc.memories[0].sensitivity == "sensitive"
    assert sc.turns[0].as_user == "u-a"


def test_the_fields_are_optional_so_the_frozen_suites_parse_unchanged():
    sc = parse_scenario({
        "id": "s1", "category": "update",
        "memories": [{"content": "Acme deploys on Tuesdays"}],
        "turns": [{"query": "when?"}],
    })
    assert sc.memories[0].scope_user == ""
    assert sc.memories[0].sensitivity == "internal"
    assert sc.turns[0].as_user == ""


def test_the_multi_user_suite_is_registered():
    paths = datasets.suite_paths("multi_user")
    assert paths, "the multi_user suite must resolve to its dataset files"
    scenarios = [s for p in paths for s in load_scenarios(p)]
    assert scenarios, "and it must carry scenarios"
    assert all(s.category == "multi_user" for s in scenarios)


# -- the runner seam ----------------------------------------------------------


def test_score_turn_hands_the_turn_to_the_adapter_before_querying():
    """The adapter must know WHO is asking before it answers."""
    calls = []

    class Recording(AdapterBase):
        name = "recording"

        def set_turn_scope(self, handle, turn):
            calls.append(turn.as_user)

        def load(self, scenario):
            return EvalHandle(scenario=scenario)

        def search(self, handle, query, k=5):
            return []

        def prefetch(self, handle, query):
            return ""

    sc = Scenario(scenario_id="s", category="multi_user", memories=[], noise=None,
                  turns=[Turn(query="q", as_user="u-a")])
    handle = EvalHandle(scenario=sc)
    score_turn(sc, sc.turns[0], Recording(), handle, k=5)
    assert calls == ["u-a"]


def test_an_adapter_without_the_seam_still_works():
    """v2 cannot scope; the no-op default keeps every frozen run unchanged."""
    assert hasattr(AdapterBase, "set_turn_scope")
    base = AdapterBase()
    handle = EvalHandle(scenario=None)
    base.set_turn_scope(handle, Turn(query="q"))  # must not raise


# -- the v3 adapter isolates --------------------------------------------------


def _load(adapter, memories, turns):
    sc = parse_scenario({
        "id": "iso", "category": "multi_user",
        "memories": memories,
        "turns": turns,
    })
    return sc, adapter.load(sc)


@pytest.fixture()
def adapter():
    a = EngineV3Adapter(disable_embeddings=True)
    yield a
    a.shutdown()


def test_one_user_s_private_memory_is_invisible_to_another_user(adapter):
    """User-private = user-scoped (§3.5's group-chat rule). The row tiers stay
    ordinary: a ``sensitive``-tier row is owner-only even to its own user under
    the pinned ``row_is_owner_only`` rule (test_em_owner_only_reads), and that
    rule is not this card's to change."""
    sc, handle = _load(
        adapter,
        [
            {"content": "Alice Example keeps the staging deploy key in the Acme vault",
             "scope_user": "u-alice"},
            {"content": "Bob Example keeps his laptop refresh budget in the Globex tracker",
             "scope_user": "u-bob"},
            {"content": "The team standup is at 09:00 on the Acme bridge"},
        ],
        [{"query": "where is the staging deploy key kept?", "as_user": "u-alice"}],
    )
    assert sc.scoped is True
    alice_ids = {handle.ref_ids["$0"]}
    bob_ids = {handle.ref_ids["$1"]}
    shared_ids = {handle.ref_ids["$2"]}

    adapter.set_turn_scope(handle, Turn(query="", as_user="u-alice"))
    hits_alice = {h.id for h in adapter.search(handle, "where is the staging deploy key kept?", k=10)}
    block_alice = adapter.prefetch(handle, "where is the staging deploy key kept?")
    assert alice_ids & hits_alice, "Alice must find her own memory"
    assert "staging deploy key" in block_alice, "and it must reach her block"
    assert not bob_ids & hits_alice, "and never see Bob's"

    adapter.set_turn_scope(handle, Turn(query="", as_user="u-bob"))
    hits_bob = {h.id for h in adapter.search(handle, "where is the staging deploy key kept?", k=10)}
    block_bob = adapter.prefetch(handle, "where is the staging deploy key kept?")
    assert not alice_ids & hits_bob, "Bob must not retrieve Alice's private memory"
    assert "staging deploy key" not in block_bob, "and it must not reach his block"
    assert shared_ids, "the shared row is still in the store"


def test_an_owner_only_row_never_reaches_a_non_owner(adapter):
    sc, handle = _load(
        adapter,
        [
            {"content": "The Acme production root password rotates on the first Monday",
             "sensitivity": "sensitive"},
            {"content": "The Initech office plants are watered on Fridays"},
        ],
        [{"query": "when does the production root password rotate?"}],
    )
    secret = handle.ref_ids["$0"]

    adapter.set_turn_scope(handle, Turn(query="", as_user=""))  # owner context
    hits_owner = {h.id for h in adapter.search(handle, "when does the production root password rotate?", k=10)}
    assert secret in hits_owner, "the owner reads owner-only rows"

    adapter.set_turn_scope(handle, Turn(query="", as_user="u-guest"))
    hits_guest = {h.id for h in adapter.search(handle, "when does the production root password rotate?", k=10)}
    block_guest = adapter.prefetch(handle, "when does the production root password rotate?")
    assert secret not in hits_guest, "a non-owner never reads owner-only rows"
    assert "root password" not in block_guest


def test_the_default_scope_is_profile_wide_and_unchanged_for_frozen_runs(adapter):
    """No as_user anywhere in the frozen suites: the load and query path must
    behave exactly as before EM-402."""
    sc, handle = _load(
        adapter,
        [{"content": "Acme deploys on Tuesdays"}, {"content": "Globex bills monthly"}],
        [{"query": "when does Acme deploy?"}],
    )
    assert handle.extra["scope"].user == ""
    hits = {h.id for h in adapter.search(handle, "when does Acme deploy?", k=10)}
    assert handle.ref_ids["$0"] in hits
    assert handle.ref_ids["$1"] in hits, "profile-wide reads see every profile-wide row"


def test_a_scenario_without_askers_loads_scope_user_profile_wide(adapter):
    """The frozen suites' ``scope_user`` values are honoured only in scoped
    scenarios (turns with askers) — no adapter ever honoured them before
    EM-402, and the committed baselines (hard multi_user recall 0.90, its
    rows written profile-wide) measure exactly that. Honouring them for
    asker-less scenarios would silently rewrite every frozen number."""
    sc, handle = _load(
        adapter,
        [{"content": "Alice Example keeps the staging deploy key in the Acme vault",
          "scope_user": "u-alice"}],
        [{"query": "where is the staging deploy key kept?"}],
    )
    assert sc.scoped is False
    hits = {h.id for h in adapter.search(handle, "where is the staging deploy key kept?", k=10)}
    assert handle.ref_ids["$0"] in hits, "profile-wide load: the frozen semantics"

    scoped_sc, scoped_handle = _load(
        adapter,
        [{"content": "Alice Example keeps the staging deploy key in the Acme vault",
          "scope_user": "u-alice"}],
        [{"query": "where is the staging deploy key kept?", "as_user": "u-alice"}],
    )
    assert scoped_sc.scoped is True
    store = scoped_handle.extra["store"]
    conn = store.reader()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT scope_user FROM memories WHERE id=?", (scoped_handle.ref_ids["$0"],)
        )]
    finally:
        conn.close()
    assert rows and rows[0]["scope_user"] == "u-alice", "scoped scenario: written in its bucket"
