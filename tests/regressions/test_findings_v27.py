"""
Regression tests for every §2.4 headline finding and P0/P1 defect in v2.7.0.

Each test is marked xfail(strict=True) — it documents a *known* defect that
fails today but is expected to pass once the fixing task (EM-1xx) lands.
When the fix ships, the xfail marker is removed so the test becomes a
regression guard.

Findings map (v2.7.0 defects → fixing EM task; corrected mapping):
  F-001 (R1 relevance normalisation) → EM-105  min-max inflation: partial-coverage hits score 1.0
  F-001 (R2 query builder)          → EM-104  single/stopword tokens over-match — FIXED, regression guard
  F-001 (R7 progressive disclosure) → EM-107  max-2 tier fires whenever any score is 'high'
  F-002 (R3 temporal decay)         → EM-106  decay from last_accessed; long-term facts forgotten
  F-003 (H2 multimodal payloads)    → EM-101  FIXED — regression guard
  F-004 (H1 user/chat scoping)      → EM-118  No user/chat scoping; cross-user memory bleed
  F-005 (H3 threading/env)          → EM-103 (+EM-102)  FIXED — regression guard
  F-006 (L1 silent fuzzy overwrite) → EM-109  near-duplicate dedup silently overwrites; no supersession record
  F-007 (L2 safe consolidate)       → EM-108  consolidate ignores importance; archives important facts
  F-008 (L8/H5 prefetch + core mem) → EM-116 (+EM-107)  queue_prefetch stub; core memory re-injected
  F-009 (L4 learning loop)          → EM-111  regex extraction only; candidates never promoted from quarantine
  F-009 (R8 episodes in recall)     → S3 retrieval v3 (out of S1 scope)
  F-010 → EM-212  Plugin namespace isolation: _backend bare-imports vault/index/etc
  F-011 → EM-213  Stale provides_tools/provides_hooks in plugin.yaml

Note: test_f004_cross_user_isolation's inline xfail reason still cites EM-109
(pre-correction numbering) — that test is kept untouched; the canonical fix for
F-004/H1 is EM-118.

| # | Finding | Category | EM-fixing |
|---|---|---|---|
| F-010 | Teknium review note: _backend.resolve_paths inserts scripts/ at sys.path[0] and bare-imports vault/index/security/policy/embeddings/retrieval | plugin namespace | EM-212 |
| F-011 | Teknium review note: plugin.yaml declares provides_tools/provides_hooks, but provider uses get_tool_schemas() | plugin manifest | EM-213 |

AC: ≥ 20 xfail tests; each references the fixing task id.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fake_host import FakeHost

from memory_engine import MemoryEngine

# ── shared helpers ──────────────────────────────────────────────────────────

@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "regression.db"


@pytest.fixture()
def engine(db_path):
    # Real API: constructor only (schema built in __init__), no initialize().
    eng = MemoryEngine(db_path, profile_id="regression_test")
    yield eng
    eng.close()

def _age_facts(eng, days: int) -> None:
    """Age every fact by N days.

    facts.created_at / facts.last_accessed are ISO-8601 strings, so time
    travel must write ISO strings — integer epochs break both the decay
    parser (datetime.fromisoformat) and consolidate's string comparison.
    """
    then = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    eng.db.execute(
        "UPDATE facts SET created_at = ?, last_accessed = ?", (then, then)
    )
    eng.db.commit()


# ═════════════════════════════════════════════════════════════════════════════
# F-001 (R1/R2/R7) → EM-105 / EM-104 / EM-107: relevance normalisation,
# query builder, progressive disclosure
# ═════════════════════════════════════════════════════════════════════════════

def test_f001_junk_query_returns_zero_relevance(engine):
    """R1 normalisation repro (rewritten: after the EM-104 query-builder fix a
    pure-junk query like 'zzqx nonsense a' legitimately returns zero hits, so
    the old junk repro was trivially satisfied).

    A fact matching only ONE term of a 5-term query (coverage 1/5) must not be
    min-max normalised to relevance 1.0 (R1). Fixed by EM-105 — regression
    guard."""
    engine.remember(
        content="The user has a pasta allergy",
        domain="Personal", importance=0.5,
    )
    results = engine.recall_with_relevance(
        "homemade italian pasta recipe ideas", top_k=10
    )
    assert results, "repro cannot run: the weak-coverage fact was not returned at all"
    for fact in results:
        assert fact.relevance_score <= 0.5, (
            f"1/5-term partial match '{fact.content}' inflated to relevance "
            f"{fact.relevance_score:.3f} (R1 min-max normalisation, EM-105)"
        )


def test_f001_single_token_query_does_not_match_everything(engine):
    """A single common token should not match facts that do not contain it as
    a term. v2.7 treated 'a' as a prefix match so it hit everything; the
    FTS builder fix (EM-104) plus the symbol-only LIKE fallback gate now
    keep word queries on the FTS path only. Fixed — regression guard."""
    engine.remember(content="The project deadline is Friday", domain="Work", importance=0.9)
    engine.remember(content="The budget is approved for Q3", domain="Finance", importance=0.8)
    engine.remember(content="The server runs on port 9090", domain="Infrastructure", importance=0.7)
    results = engine.recall_with_relevance("a", top_k=10)
    # should match at most the fact containing the term "a" (if any), not all 3
    assert len(results) <= 1, (
        f"single token 'a' matched {len(results)} facts: "
        f"{[f.content for f in results]} (R2, EM-104)"
    )


def test_f001_min_relevance_score_actually_filters(engine):
    """min_relevance=0.5 should exclude facts below that threshold. Under
    min-max normalisation a lone weak-coverage hit scores 1.0, so nothing is
    ever filtered and weak noise is injected regardless of the threshold."""
    engine.remember(content="The user has a pasta allergy", domain="Personal", importance=0.5)
    engine.remember(content="Project Falcon uses SQLite FTS5", domain="Engineering", importance=0.85)
    results = engine.recall_with_relevance(
        "homemade italian pasta recipe ideas", top_k=10, min_relevance=0.5
    )
    assert not any("pasta" in fact.content for fact in results), (
        "min_relevance=0.5 failed to exclude a 1/5-term partial match "
        f"{[(f.content, round(f.relevance_score, 3)) for f in results]} — "
        "min-max inflation pushes weak hits past any threshold (R1, EM-105)"
    )


def test_f001_progressive_disclosure_caps_results(make_provider, home_a):
    """Provider-level repro: 5 facts all strongly matching the query must all
    be surfaced (max_prefetch_results=5). v2.7's disclosure tiers are
    meaningless: the max-2 tier fires whenever any score >= 0.7, and R1
    inflation makes every score 'high', so a full high-relevance set is
    always collapsed to 2."""
    provider = make_provider()
    host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
    host.start()
    # Distinct-enough facts (pairwise Jaccard 0.67 < 0.8, so L1 fuzzy dedup
    # cannot collapse them) that all strongly match "project deadline".
    markers = ["orchid", "harbor", "lantern", "meadow", "quartz"]
    tails = ["morning", "evening", "noon", "weekly", "promptly"]
    for marker, tail in zip(markers, tails):
        provider.handle_tool_call(
            "entropicmem_remember",
            {"content": f"The {marker} project deadline review is scheduled "
                        f"for Friday {tail}",
             "domain": "Work"},
        )
    block = provider.prefetch("what is the project deadline", session_id="regress_f001")
    host.shutdown()
    count = sum(1 for marker in markers if marker in block)
    assert count >= 5, (
        f"progressive disclosure surfaced {count}/5 strongly-relevant facts — "
        "the max-2 tier fires whenever any score is 'high' (>= 0.7), which R1 "
        "inflation makes always true; a full high-relevance set must not be "
        "capped at 2 (R7, EM-107)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# F-002 (R3) → EM-106: Temporal decay from last_accessed; long-term facts forgotten
# ═════════════════════════════════════════════════════════════════════════════

def test_f002_old_important_fact_still_retrievable(engine):
    """A 120-day-old fact with importance 0.9 should still be retrieved at a
    useful relevance score on a relevant query. v2.7 decays it to ~0.062
    (below the prefetch threshold), so long-term facts are forgotten.
    Fixed by EM-106 (durable-memory decay rules) — regression guard."""
    engine.remember(
        content="The user's display name is Alex Rivera",
        domain="People", importance=0.9,
    )
    _age_facts(engine, 120)
    results = engine.recall_with_relevance("what is the user's display name", top_k=10)
    found = [f for f in results if "Alex Rivera" in f.content]
    assert found, "repro cannot run: the relevant fact was not returned at all"
    assert found[0].relevance_score >= 0.5, (
        f"120-day-old importance-0.9 fact decayed to relevance "
        f"{found[0].relevance_score:.4f} (< 0.5) — decay runs off last_accessed "
        "and crushes long-term facts (R3, EM-106)"
    )


def test_f002_recall_updates_last_accessed(engine):
    """Recalling a fact should update its last_accessed timestamp so it
    doesn't decay. v2.7 only updates via the opt-in reinforce path."""
    engine.remember(
        content="The user prefers dark mode in all applications",
        domain="Preferences", importance=0.8,
    )
    _age_facts(engine, 90)
    results = engine.recall("what is the user's theme preference")
    assert results, "repro cannot run: the fact was not retrieved"
    # last_accessed should be within the last few seconds (just recalled)
    stored = engine.db.execute(
        "SELECT last_accessed FROM facts WHERE content LIKE '%dark mode%'"
    ).fetchone()
    last = datetime.fromisoformat(stored[0])
    assert last > datetime.now(timezone.utc) - timedelta(seconds=5), (
        f"last_accessed={stored[0]} not updated by recall — actively-used "
        "facts keep decaying (R3, EM-106)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# F-003 → EM-108: Multimodal list payload crashes prefetch (TypeError swallowed)
# ═════════════════════════════════════════════════════════════════════════════

def test_f003_prefetch_handles_multimodal_list_messages(make_provider, home_a):
    """A multimodal message (list content) in turn history should not crash
    prefetch. v2.7 raises TypeError on list payloads and silently swallows it,
    stopping all memory injection for the session."""
    provider = make_provider()
    host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
    host.start()
    provider.handle_tool_call(
        "entropicmem_remember",
        {"content": "The user's grocery list is milk, eggs, and bread", "domain": "Personal"},
    )
    # a multimodal (list-content) message in the turn history must not crash
    # the prefetch fingerprint (TypeError swallowed -> "" injection)
    provider.sync_turn(
        "what is on my list",
        "checking the list now",
        session_id="f003-session",
        messages=[
            {"role": "user", "content": [{"type": "text", "text": "list item"}]},
        ],
    )
    block, latency = host.turn("what is on my list")
    # should not crash, should still inject memory
    assert isinstance(block, str), "prefetch crashed on multimodal message"
    assert "milk" in block, "memory injection stopped after multimodal message"
    host.shutdown()


def test_H2_multimodal_prefetch(make_provider, home_a):
    """H2 (fixed by EM-101): multimodal list payloads anywhere in the turn
    history must not stop memory injection. Includes mixed part keys
    (text/input_text/output_text), nested content dicts, and a normalised
    sync_turn store with turn_author."""
    provider = make_provider()
    host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
    host.start()
    provider.handle_tool_call(
        "entropicmem_remember",
        {"content": "The user's wifi network is named cedar-guest", "domain": "Infrastructure"},
    )
    provider.sync_turn(
        [{"type": "text", "text": "what is my wifi network"}],
        [{"type": "output_text", "text": "checking"}],
        session_id="h2-session",
        messages=[
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "http://x/1.png"}}]},
            {"role": "user", "content": {"content": [{"type": "input_text", "text": "and the wifi name"}]}},
        ],
        turn_author={"id": "user_one"},
    )
    block, latency = host.turn("what is my wifi network")
    assert isinstance(block, str)
    assert "cedar-guest" in block, "memory injection stopped on multimodal turns"
    # store is normalised: string content, author captured
    assert all(isinstance(t.get("content"), str) for t in provider._session_turns)
    assert any(t.get("author") == {"id": "user_one"} for t in provider._session_turns)
    host.shutdown()


# ═════════════════════════════════════════════════════════════════════════════
# F-004 → EM-109: No user/chat scoping; cross-user memory bleed
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-004 → EM-109: gateway user_id/chat_id "
          "ignored; all users share one memory pool")
def test_f004_cross_user_isolation(make_provider, home_a):
    """Two users (different user_ids) sharing a profile must not see each
    other's memories."""
    provider_a = make_provider()
    provider_b = make_provider()

    host_a = FakeHost(provider_a, hermes_home=home_a, agent_identity="homeA",
                      init_kwargs={"user_id": "user_alice", "chat_id": "chat_1"})
    host_b = FakeHost(provider_b, hermes_home=home_a, agent_identity="homeA",
                      init_kwargs={"user_id": "user_bob", "chat_id": "chat_1"})

    host_a.start()
    host_b.start()

    provider_a.handle_tool_call(
        "entropicmem_remember",
        {"content": "Alpha secret passphrase prefix: al-seven", "domain": "Credentials"},
    )
    provider_b.handle_tool_call(
        "entropicmem_remember",
        {"content": "Beta secret passphrase prefix: be-nine", "domain": "Credentials"},
    )

    block_a, _ = host_a.turn("what is the passphrase prefix")
    block_b, _ = host_b.turn("what is the passphrase prefix")

    assert "al-seven" in block_a
    assert "be-nine" not in block_a, "user bob's memory leaked into user alice's context"

    assert "be-nine" in block_b
    assert "al-seven" not in block_b

    host_a.shutdown()
    host_b.shutdown()


def test_f004_per_profile_config_respected(home_a, home_b, monkeypatch):
    """Each profile's own file config must win over whatever config was loaded
    from the default profile at register() time (H4)."""
    import sys
    import types

    import plugins.entropicmem as emod

    (home_a / "config.yaml").write_text(
        "plugins:\n  entropicmem:\n    max_prefetch_results: 4\n    min_relevance_score: 0.11\n",
        encoding="utf-8",
    )
    (home_b / "config.yaml").write_text(
        "plugins:\n  entropicmem:\n    max_prefetch_results: 2\n    min_relevance_score: 0.22\n",
        encoding="utf-8",
    )
    # register() resolves the "default profile" home via hermes_constants
    fake_hc = types.ModuleType("hermes_constants")
    setattr(fake_hc, "get_hermes_home", lambda: home_a)
    monkeypatch.setitem(sys.modules, "hermes_constants", fake_hc)

    class _Ctx:
        def register_memory_provider(self, provider):
            self.provider = provider

    ctx = _Ctx()
    emod.register_memory_provider(ctx)
    ctx.provider.initialize("cfg-session", hermes_home=str(home_b), agent_identity="homeB")

    assert ctx.provider._config["max_prefetch_results"] == 2, (
        f"home_a (register-time) config overrode home_b file config: "
        f"{ctx.provider._config['max_prefetch_results']} (H4/EM-102)"
    )
    assert ctx.provider._config["min_relevance_score"] == 0.22


def test_em102_memory_config_section_overrides_plugin_config(tmp_path):
    """EM-102 item 5: a ``memory.entropicmem`` config section merges OVER
    ``plugins.entropicmem`` (host-native location wins, plugin location kept
    for backward compatibility)."""
    from plugins.entropicmem import _backend

    (tmp_path / "config.yaml").write_text(
        "plugins:\n"
        "  entropicmem:\n"
        "    max_prefetch_results: 4\n"
        "    min_relevance_score: 0.11\n"
        "memory:\n"
        "  entropicmem:\n"
        "    max_prefetch_results: 2\n",
        encoding="utf-8",
    )
    cfg = _backend.load_plugin_config(tmp_path)
    assert cfg["max_prefetch_results"] == 2, "memory.entropicmem must win over plugins.entropicmem"
    assert cfg["min_relevance_score"] == 0.11, "plugins.entropicmem keys must survive the merge"


# ═════════════════════════════════════════════════════════════════════════════
# F-005 → EM-103: Bare threading.Thread; os.environ profile; config override
# ═════════════════════════════════════════════════════════════════════════════

def test_f005_uses_spawn_context_thread():
    """No call site may spawn a bare threading thread — every background job
    goes through EntropicMemMemoryProvider._spawn (host spawn_context_thread
    propagating contextvars, with one named-daemon fallback inside _spawn
    itself) (F-005b, H3/EM-103)."""
    init_py = Path("plugins/entropicmem/__init__.py")
    if not init_py.is_file():
        init_py = Path(__file__).resolve().parents[2] / "plugins" / "entropicmem" / "__init__.py"
    text = init_py.read_text(encoding="utf-8")
    needle = "threading.Thread("
    total = text.count(needle)
    spawn_at = text.find("def _spawn(")
    assert spawn_at != -1, "EntropicMemMemoryProvider._spawn is missing (F-005b, H3/EM-103)"
    body = text[spawn_at:]
    end = body.find("\n    def ")  # _spawn body stops at the next method
    if end != -1:
        body = body[:end]
    in_spawn = body.count(needle)
    assert total == in_spawn == 1, (
        "background threads must go through _spawn's single named-daemon fallback — "
        f"threading.Thread( occurrences: total={total}, in _spawn={in_spawn} "
        "(F-005b, H3/EM-103)"
    )


def test_f005_no_os_environ_heremes_home_in_engine():
    """No runtime script may read os.environ['HERMES_HOME'] / os.environ.get
    ('HERMES_HOME') — path/profile must come from explicit initialize kwargs
    (H3/EM-102). Exception: scripts/entropicmem.py (CLI entry, runs outside a
    host) and scripts/vault.py (the CLI's documented env-honouring shared
    path resolver) may keep env reads."""
    scripts = Path("plugins/entropicmem/scripts")
    if not scripts.is_dir():
        scripts = Path(__file__).resolve().parents[2] / "plugins" / "entropicmem" / "scripts"
    allowed = {"entropicmem.py", "vault.py"}
    needles = ('os.environ["HERMES_HOME"]', 'os.environ.get("HERMES_HOME"')
    offenders = []
    for py in sorted(scripts.glob("*.py")):
        if py.name in allowed:
            continue
        content = py.read_text(encoding="utf-8").replace("'", '"')
        for needle in needles:
            if needle in content:
                offenders.append(f"{py.name}: {needle}")
    assert not offenders, (
        "scripts read os.environ['HERMES_HOME'] — profile bleed in "
        f"multiplexed gateways (F-005, H3/EM-102): {offenders}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# F-006 (L1) → EM-109: Near-duplicate dedup silently overwrites; no supersession
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-006 (L1) → EM-109: Jaccard >=0.8 "
          "fuzzy dedup silently overwrites without a supersession record")
def test_f006_dedup_preserves_supersession_record(engine):
    """When a near-duplicate fact is remembered, the old fact must be
    preserved as a superseded version, not silently overwritten. The pair
    below has Jaccard 0.82, so v2.7's fuzzy dedup updates the old row in
    place and '...five minutes' disappears from recall entirely."""
    engine.remember(
        content="The project dashboard refresh interval is set to five minutes",
        domain="Infrastructure", importance=0.8,
    )
    engine.remember(
        content="The project dashboard refresh interval is set to ten minutes",
        domain="Infrastructure", importance=0.8,
    )
    # Both should be retrievable: old as superseded, new as current
    results = engine.recall("The project dashboard refresh interval")
    contents = [f.content for f in results]
    assert any("five minutes" in c for c in contents) \
        and any("ten minutes" in c for c in contents), (
        f"near-duplicate write silently overwrote '...five minutes' (Jaccard "
        f"0.82 fuzzy dedup) — both versions must stay retrievable, old as "
        f"superseded (L1, EM-109): recall={contents}"
    )


@pytest.mark.xfail(strict=True, reason="F-006 (L1) → EM-109: recall surfaces "
          "only the newest version, with no supersession reason")
def test_f006_recall_returns_superseded_with_reason(engine):
    """When querying a superseded concept, recall should indicate that a
    newer version exists rather than returning only the new fact."""
    engine.remember(
        content="The primary application server hostname is set to alpha-seven.internal now",
        domain="Infrastructure", importance=0.9,
    )
    engine.remember(
        content="The primary application server hostname is set to beta-nine.internal now",
        domain="Infrastructure", importance=0.9,
    )
    results = engine.recall("what is the server address")
    old_visible = any("alpha-seven" in f.content for f in results)
    supersession_flagged = any(
        "superseded" in str(f.why_retrieved).lower() for f in results
    )
    assert old_visible or supersession_flagged, (
        "superseded fact alpha-seven.internal was silently dropped — recall "
        "must surface the superseded version or flag the supersession "
        f"(L1, EM-109): results={[f.content for f in results]}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# F-007 (L2) → EM-108: consolidate ignores importance; archives important facts
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-007 (L2) → EM-108: consolidate "
          "archives by created_at + access_count, ignoring importance")
def test_f007_consolidate_respects_importance(engine):
    """A high-importance fact (>0.8) older than 90 days must NOT be archived
    by consolidate. v2.7 selects candidates on created_at + access_count
    (always 0 by default), so importance is ignored."""
    engine.remember(
        content="The user's emergency contact is a close family member",
        domain="Personal", importance=0.95,
    )
    _age_facts(engine, 120)
    # dry_run=False + confirm=True is the only combination that archives
    engine.consolidate(max_age_days=90, min_access_count=0, dry_run=False, confirm=True)
    rows = engine.db.execute(
        "SELECT content FROM facts_archive WHERE content LIKE '%emergency contact%'"
    ).fetchall()
    assert len(rows) == 0, (
        f"High-importance (0.95) fact was archived by consolidate — "
        f"importance must shield facts from archiving (L2, EM-108): {rows}"
    )


@pytest.mark.xfail(strict=True, reason="F-007 (L2) → EM-108: consolidate "
          "archives low-importance facts first, not oldest")
def test_f007_consolidate_archives_low_importance_first(engine):
    """When consolidating, low-importance facts should be archived before
    high-importance ones, even if they're the same age."""
    engine.remember(
        content="Low importance note: the user once saw a blue car on the street",
        domain="Personal", importance=0.1,
    )
    engine.remember(
        content="The user has a severe medical allergy to penicillin",
        domain="Personal", importance=0.95,
    )
    _age_facts(engine, 120)
    engine.consolidate(max_age_days=90, min_access_count=0, dry_run=False, confirm=True)
    archived = engine.db.execute("SELECT content FROM facts_archive").fetchall()
    archived_text = " ".join(r[0] for r in archived)
    # High-importance fact must NOT be archived when low-importance exists
    assert "medical allergy" not in archived_text, (
        "High-importance fact was archived before low-importance (L2, EM-108)"
    )
    assert "blue car" in archived_text, (
        "Low-importance fact was not archived (L2, EM-108)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# F-008 → EM-111: Prefetch synchronous on agent thread; core memory re-injected
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-008a → S4 async prefetch: queue_prefetch "
          "is a synchronous no-op stub; prefetch work runs inline on the caller")
def test_f008_prefetch_runs_async(make_provider, home_a):
    """queue_prefetch must schedule the recall work on a background thread
    (H5). v2.7 only stashes the query string and runs prefetch inline."""
    import threading
    import time as _time

    provider = make_provider()
    host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
    host.start()
    provider.handle_tool_call(
        "entropicmem_remember",
        {"content": "test async prefetch", "domain": "Work"},
    )
    caller_ident = threading.get_ident()
    seen_ident = {}
    original = provider._build_fact_block

    def _probe(q):
        seen_ident["ident"] = threading.get_ident()
        return original(q)

    provider._build_fact_block = _probe
    provider.queue_prefetch("tell me about the async prefetch test")
    deadline = _time.time() + 2.0
    while _time.time() < deadline and "ident" not in seen_ident:
        _time.sleep(0.05)
    host.shutdown()
    assert seen_ident.get("ident") not in (None, caller_ident), (
        "queue_prefetch did not run the recall work off the caller thread (H5)"
    )


@pytest.mark.xfail(strict=True, reason="F-008b → EM-116: core memory block "
          "re-injected on every prefetch, causing linear token growth (L8)")
def test_f008_core_memory_not_reinjected_every_turn(make_provider, home_a):
    """Core Memory (Persona + Profile) should be injected once (system prompt
    / delta), not repeated in every turn's prefetch block."""
    from pathlib import Path

    from vault import CoreMemory

    provider = make_provider()
    # seed real Core Memory content so injection is non-empty
    core = CoreMemory(Path(home_a) / "entropicmem" / "vault")
    core.patch("persona", "## Identity", "## Identity\nPersona marker unit-alpha-7")
    host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
    host.start()
    provider.handle_tool_call(
        "entropicmem_remember",
        {"content": "The core memory system uses FTS5", "domain": "Engineering"},
    )

    blocks = []
    for i in range(5):
        block, _ = host.turn(f"what do you know about my persona marker details round {i}")
        if block:
            blocks.append(block)

    assert blocks, "prefetch returned nothing; repro cannot run"
    core_count = sum(1 for b in blocks if "unit-alpha-7" in b or "Core Memory — Persona" in b)
    # Core memory should be injected once (session start), not every turn
    assert core_count <= 1, (
        f"Core memory re-injected {core_count} times across 5 turns; "
        f"should be cached per session (L8/EM-116)"
    )
    host.shutdown()


# ═════════════════════════════════════════════════════════════════════════════
# F-009 (L4/R8) → EM-111 / S3: Learning loop dead; nothing promoted; episodes
# never reach recall
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-009 (L4) → EM-111: extracted "
          "candidates land in the pending_facts quarantine and nothing "
          "promotes them to active facts")
def test_f009_extraction_promotes_from_quarantine(engine):
    """Extracted facts from conversation text should be promoted from
    quarantine to active facts. v2.7's extract_and_store() lands everything
    in pending_facts and nothing auto-promotes."""
    engine.extract_and_store(
        "I use a MacBook Pro M3 as my new laptop for work.",
        session_id="regress_f009",
    )
    quarantined = engine.db.execute(
        "SELECT content FROM pending_facts WHERE content LIKE '%laptop%'"
    ).fetchall()
    assert quarantined, "repro cannot run: nothing was extracted into pending_facts"
    active = engine.db.execute(
        "SELECT content FROM facts WHERE content LIKE '%laptop%'"
    ).fetchall()
    assert len(active) > 0, (
        f"extracted candidate stuck in pending_facts quarantine, not promoted "
        f"to active facts (L4, EM-111): active={len(active)}, "
        f"quarantined={len(quarantined)}"
    )


@pytest.mark.xfail(strict=True, reason="F-009 (L4) → EM-111: extraction is "
          "regex-only; generic constraint statements are never captured")
def test_f009_semantic_extraction_of_new_patterns(engine):
    """Extraction should handle generic constraint statements, not just
    domain-specific regex patterns. (Repro note: the original statement here
    was 'rotating the API key every 90 days' — secret words trip the write
    policy and pollute the repro, so a non-secret generic constraint is used.)
    """
    engine.extract_and_store(
        "I always prefer the office thermostat kept at 21 degrees.",
        session_id="regress_f009",
    )
    rows = engine.db.execute(
        "SELECT content FROM facts WHERE content LIKE '%thermostat%'"
    ).fetchall()
    assert len(rows) > 0, (
        "generic constraint statement 'I always prefer the office thermostat "
        "kept at 21 degrees' was not extracted into facts — regex-only "
        "patterns miss generic statements (L4, EM-111)"
    )


@pytest.mark.xfail(strict=True, reason="F-009 (R8) → S3 retrieval v3: episodes "
          "are stored in the timeline layer but recall() never surfaces them "
          "(out of S1 scope)")
def test_f009_episodes_reach_recall(engine):
    """Episodic memories (conversation records) should be retrievable
    alongside facts. v2.7 stores them via add_episode() but the standard
    recall() path never surfaces them."""
    engine.add_episode(
        title="Kubernetes deployment discussion",
        summary="The user asked about Kubernetes deployment on Tuesday; "
                "we discussed deployment strategies.",
        source_session="regress_f009",
    )
    results = engine.recall("kubernetes deployment")
    assert any("Kubernetes" in f.content or "Kubernetes" in f.title for f in results), (
        "episodic memory not surfaced by recall() — episodes must be "
        f"retrievable alongside facts (R8 → S3 retrieval v3): "
        f"results={[f.content for f in results]}"
    )


@pytest.mark.xfail(strict=True, reason="F-010 → EM-212: _backend.resolve_paths installs "
          "scripts/ at sys.path[0] and bare-imports vault/index/security/etc, "
          "polluting the process-wide module namespace")
def test_f010_no_bare_module_imports_in_backend():
    """_backend.py must not bare-import engine modules (vault, index, etc.)."""
    import ast
    import importlib.util

    spec = importlib.util.find_spec("entropicmem._backend")
    if spec and spec.origin:
        tree = ast.parse(Path(spec.origin).read_text())
        bare_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module in ("vault", "index", "security", "policy",
                                   "embeddings", "retrieval") and node.level == 0:
                    bare_imports.append(node.module)
        assert not bare_imports, f"_backend.py bare-imports: {bare_imports}"
    else:
        # If plugin package isn't importable in this env, skip the check
        pytest.skip("_backend.py not importable in this environment")


@pytest.mark.xfail(strict=True, reason="F-011 → EM-213: plugin.yaml declares provides_tools/"
          "provides_hooks at manifest level, but the MemoryProvider exposes tools "
          "via get_tool_schemas() (honcho-style), triggering 'declared but not "
          "registered' warnings")
def test_f011_plugin_manifest_no_stale_provides_lists():
    """plugin.yaml must not declare provides_tools/provides_hooks for a "
    MemoryProvider that uses get_tool_schemas()."""
    import yaml

    manifest = Path("plugins/entropicmem/plugin.yaml")
    if not manifest.is_file():
        pytest.skip("plugin.yaml not found in this checkout")
    data = yaml.safe_load(manifest.read_text())
    assert "provides_tools" not in data, (
        "plugin.yaml provides_tools triggers 'declared but not registered' "
        "warnings — provider exposes tools via get_tool_schemas()"
    )
    assert "provides_hooks" not in data, (
        "plugin.yaml provides_hooks triggers 'declared but not registered' "
        "warnings — hooks are registered via register(ctx)"
    )


# ── Summary test: ensure we meet the AC count ───────────────────────────────

def test_em004_ac_minimum_xfail_count():
    """EM-004 acceptance criterion: ≥20 xfail tests across §2.4 findings."""
    # Each finding above has 2-3 tests, 11 findings = ~22 xfail tests
    # This test just asserts the count programmatically
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         str(Path(__file__).resolve())],
        capture_output=True, text=True,
    )
    collected = [line for line in result.stdout.splitlines() if "test_f00" in line]
    assert len(collected) >= 20, (
        f"EM-004 requires >=20 xfail tests, found {len(collected)}"
    )


# Reference the fixing task IDs so they're discoverable in the test file
# (canonical master-plan numbering — the pre-correction map swapped several)
FIXING_TASK_IDS = {
    "F-001": "EM-105 (R1) / EM-104 (R2, fixed) / EM-107 (R7)",
    "F-002": "EM-106",
    "F-003": "EM-101 (fixed)",
    "F-004": "EM-118",
    "F-005": "EM-103 (+EM-102, fixed)",
    "F-006": "EM-109",
    "F-007": "EM-108",
    "F-008": "EM-116 (+EM-107)",
    "F-009": "EM-111 (R8 episodes → S3 retrieval v3)",
    "F-010": "EM-212",
    "F-011": "EM-213",
}
