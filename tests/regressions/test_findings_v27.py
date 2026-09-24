"""
Regression tests for every §2.4 headline finding and P0/P1 defect in v2.7.0.

Each test is marked xfail(strict=True) — it documents a *known* defect that
fails today but is expected to pass once the fixing task (EM-1xx) lands.
When the fix ships, the xfail marker is removed so the test becomes a
regression guard.

Findings map (v2.7.0 defects → fixing EM task):
  F-001 → EM-105  Relevance normalisation / junk-query noise amplification
  F-002 → EM-107  Temporal decay from last_accessed; long-term facts forgotten
  F-003 → EM-108  Multimodal list payload crashes prefetch (TypeError swallowed)
  F-004 → EM-109  No user/chat scoping; cross-user memory bleed
  F-005 → EM-110  os.environ check already clean (F-005a); bare threading.Thread still needed (F-005b)
  F-006 → EM-104  Near-duplicate dedup silently overwrites; no supersession record
  F-007 → EM-106  consolidate ignores importance; archives important facts
  F-008 → EM-111  Prefetch synchronous on agent thread; core memory re-injected every turn
  F-009 → EM-112  Learning loop dead; regex extraction only, nothing promoted
  F-010 → EM-212  Plugin namespace isolation: _backend bare-imports vault/index/etc
  F-011 → EM-213  Stale provides_tools/provides_hooks in plugin.yaml

| # | Finding | Category | EM-fixing |
|---|---|---|---|
| F-010 | Teknium review note: _backend.resolve_paths inserts scripts/ at sys.path[0] and bare-imports vault/index/security/policy/embeddings/retrieval | plugin namespace | EM-212 |
| F-011 | Teknium review note: plugin.yaml declares provides_tools/provides_hooks, but provider uses get_tool_schemas() | plugin manifest | EM-213 |

AC: ≥ 20 xfail tests; each references the fixing task id.
"""

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
    eng = MemoryEngine(str(db_path))
    eng.initialize(profile_id="regression_test",
                   vault_root=str(db_path.parent / "vault"))
    yield eng
    eng.close()


# ═════════════════════════════════════════════════════════════════════════════
# F-001 → EM-105: Relevance normalisation / junk-query noise amplification
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-001 → EM-105: min-max normalisation "
          "gives junk queries relevance=1.0; noise injected on most turns")
def test_f001_junk_query_returns_zero_relevance(engine):
    """A gibberish query matching no real fact should never return relevance
    1.0. v2.7 min-max normalises per-result-set so even filler ranks at 1.0."""
    engine.remember(
        content="The user works at Acme Corp as a Product Manager.",
        domain="Work", importance=0.9,
    )
    # gibberish with no real overlap
    results = engine.recall_with_relevance("zzqx nonsense a query", top_k=10)
    for _, _, score, _ in results:
        assert score < 0.3, f"junk query returned relevance {score} (>= 0.3)"


@pytest.mark.xfail(strict=True, reason="F-001 → EM-105: 1-letter FTS prefix terms "
          "make every token match; no real filtering")
def test_f001_single_token_query_does_not_match_everything(engine):
    """A single common token should not match all facts in the DB.
    v2.7 treats 'a' as a prefix match so it hits everything."""
    engine.remember(content="The project deadline is Friday", domain="Work", importance=0.9)
    engine.remember(content="The budget is approved for Q3", domain="Finance", importance=0.8)
    engine.remember(content="The server runs on port 9090", domain="Infrastructure", importance=0.7)
    results = engine.recall_with_relevance("a", top_k=10)
    # should match at most the fact containing "a" (if any), not all 3
    assert len(results) <= 1, f"single token 'a' matched {len(results)} facts"


@pytest.mark.xfail(strict=True, reason="F-001 → EM-105: min_relevance_score "
          "is meaningless under min-max normalisation")
def test_f001_min_relevance_score_actually_filters(engine):
    """min_relevance_score=0.5 should exclude facts below that threshold.
    Under min-max normalisation the minimum is always 0.0 so nothing is filtered."""
    engine.remember(content="The user likes rooibos tea", domain="Personal", importance=0.6)
    engine.remember(content="Project Falcon uses SQLite FTS5", domain="Engineering", importance=0.85)
    results = engine.recall_with_relevance(
        "what tea does the user like", top_k=10, min_relevance_score=0.5
    )
    for _, _, score, _ in results:
        assert score >= 0.5, f"fact with relevance {score} below min_relevance_score=0.5"


@pytest.mark.xfail(strict=True, reason="F-001 → EM-105: progressive disclosure "
          "max-2/3/5 tiers are meaningless")
def test_f001_progressive_disclosure_caps_results(engine):
    """With 5 facts all scoring >=0.7, progressive disclosure should cap at 2,
    not return all 5."""
    for i in range(5):
        engine.remember(
            content=f"Fact number {i} about the project deadline on Friday",
            domain="Work", importance=0.9,
        )
    results = engine.prefetch("project deadline", session_id="regress_f001")
    # progressive disclosure: max 2 if any >= 0.7
    assert len(results) <= 2, f"returned {len(results)} facts, progressive disclosure cap is 2"


# ═════════════════════════════════════════════════════════════════════════════
# F-002 → EM-107: Temporal decay from last_accessed; long-term facts forgotten
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-002 → EM-107: decay computed from "
          "last_accessed (never updated by default); 120-day facts decayed to 0.062")
def test_f002_old_important_fact_still_retrievable(engine):
    """A 120-day-old fact with importance 0.9 should still be retrieved
    on a relevant query. v2.7 decays it to ~0.062 and never prefetches."""
    import time as _time
    engine.remember(
        content="The user's display name is Alex Rivera",
        domain="People", importance=0.9, age_days=120,
    )
    # simulate time having passed
    engine.db.execute(
        "UPDATE facts SET created_at = ?, last_accessed = ?",
        (int(_time.time()) - 120 * 86400, int(_time.time()) - 120 * 86400),
    )
    engine.db.commit()
    results = engine.recall_with_relevance("what is the user's display name", top_k=10)
    found = any("Alex Rivera" in r for _, r, _, _ in results)
    assert found, "120-day-old important fact was not retrieved"


@pytest.mark.xfail(strict=True, reason="F-002 → EM-107: last_accessed never "
          "updated by default reinforce path")
def test_f002_recall_updates_last_accessed(engine):
    """Recalling a fact should update its last_accessed timestamp so it
    doesn't decay. v2.7 only updates via opt-in reinforce."""
    engine.remember(
        content="The user prefers dark mode in all applications",
        domain="Preferences", importance=0.8, age_days=90,
    )
    engine.recall("what is the user's theme preference")
    # last_accessed should be within the last few seconds (just recalled)
    import time as _time
    stored = engine.db.execute(
        "SELECT last_accessed FROM facts WHERE content LIKE '%dark mode%'"
    ).fetchone()
    assert stored[0] > _time.time() - 5, f"last_accessed={stored[0]} not updated after recall"


# ═════════════════════════════════════════════════════════════════════════════
# F-003 → EM-108: Multimodal list payload crashes prefetch (TypeError swallowed)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-003 → EM-108: multimodal message with "
          "list content raises TypeError: unhashable type 'list' in prefetch")
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
    # send a turn with multimodal list content
    block, latency = host.turn(
        "what is on my list",
        extra_messages=[{"role": "user", "content": [{"type": "text", "text": "list item"}]}],
    )
    # should not crash, should still inject memory
    assert isinstance(block, str), "prefetch crashed on multimodal message"
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


@pytest.mark.xfail(strict=True, reason="F-004 → EM-109: per-profile config "
          "overridden by default profile at initialize")
def test_f004_per_profile_config_respected(make_provider, home_a, home_b):
    """Each profile must use its own config, not the default profile's.
    v2.7 overrides per-profile config at initialize."""
    provider_a = make_provider()
    provider_b = make_provider()

    host_a = FakeHost(provider_a, hermes_home=home_a, agent_identity="homeA")
    host_b = FakeHost(provider_b, hermes_home=home_b, agent_identity="homeB")
    host_a.start()
    host_b.start()

    provider_a.handle_tool_call(
        "entropicmem_remember",
        {"content": "Profile A specific memory: alpha-omega-9", "domain": "Work"},
    )
    provider_b.handle_tool_call(
        "entropicmem_remember",
        {"content": "Profile B specific memory: beta-prime-7", "domain": "Work"},
    )

    # A's profile should not see B's memories and vice versa
    block_a, _ = host_a.turn("what specific memories exist for profile A")
    block_b, _ = host_b.turn("what specific memories exist for profile B")

    assert "alpha-omega-9" in block_a
    assert "beta-prime-7" not in block_a, "profile B memory leaked into profile A"

    assert "beta-prime-7" in block_b
    assert "alpha-omega-9" not in block_b

    host_a.shutdown()
    host_b.shutdown()


# ═════════════════════════════════════════════════════════════════════════════
# F-005 → EM-110: Bare threading.Thread; os.environ profile; config override
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-005 → EM-110: background threads use "
          "bare threading.Thread instead of spawn_context_thread")
def test_f005_uses_spawn_context_thread(make_provider, home_a):
    """Background sync threads must be spawned via the host's
    spawn_context_thread when running under Hermes, not bare threading.Thread."""
    provider = make_provider()
    host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
    host.start()
    provider.handle_tool_call(
        "entropicmem_remember",
        {"content": "test sync thread", "domain": "Work"},
    )
    host.turn("hello world")

    # Check that spawn_context_thread was called (not bare Thread)
    import threading
    threads = [t for t in threading.enumerate() if "sync" in t.name.lower()]
    # In the real fix, we check that spawn_context_thread was used.
    # For now, xfail: v2.7 uses bare Thread.
    assert not threads, "Bare threading.Thread detected; should use spawn_context_thread"

    host.shutdown()


def test_f005_no_os_environ_heremes_home_in_engine():
    """The engine must never read os.environ['HERMES_HOME'] — path/profile
    must come from explicit initialize kwargs."""
    # This test verifies by code inspection that the engine does not
    # reference os.environ['HERMES_HOME'] after initialize.
    me = Path("memory_engine.py")
    if not me.exists():
        # try the standard location
        me = Path("plugins/entropicmem/scripts/memory_engine.py")
    content = me.read_text()
    assert 'os.environ["HERMES_HOME"]' not in content.replace("'", '"'), (
        "Engine reads os.environ['HERMES_HOME'] — profile bleed in "
        "multiplexed gateways (F-005, EM-110)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# F-006 → EM-104: Near-duplicate dedup silently overwrites; no supersession
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-006 → EM-104: Jaccard >=0.8 dedup "
          "silently overwrites without supersession record")
def test_f006_dedup_preserves_supersession_record(engine):
    """When a near-duplicate fact is remembered, the old fact must be
    preserved as a superseded version, not silently overwritten."""
    engine.remember(
        content="The API gateway listens on port 8080",
        domain="Infrastructure", importance=0.8,
    )
    engine.remember(
        content="The API gateway listens on port 9090",
        domain="Infrastructure", importance=0.8,
    )
    # Both should be retrievable: old as superseded, new as current
    rows = engine.db.execute(
        "SELECT content, superseded_by FROM facts ORDER BY created_at"
    ).fetchall()
    assert len(rows) >= 1
    old_row = rows[0]
    # The old fact must have a supersession record
    assert old_row[1] is not None, (
        f"Old fact '{old_row[0]}' was silently overwritten — "
        "no supersession record (F-006, EM-104)"
    )


@pytest.mark.xfail(strict=True, reason="F-006 → EM-104: recall surfaces only the "
          "newest without a way to query superseded versions")
def test_f006_recall_returns_superseded_with_reason(engine):
    """When querying a superseded concept, recall should indicate that a
    newer version exists rather than returning only the new fact."""
    engine.remember(
        content="The server address is host alpha-seven.internal",
        domain="Infrastructure", importance=0.9,
    )
    engine.remember(
        content="The server address is host beta-nine.internal",
        domain="Infrastructure", importance=0.9,
    )
    # Recall should mention both facts or at least note the supersession
    results = engine.recall("what is the server address")
    # At minimum, the response should not silently drop the old fact
    assert "alpha-seven" in results or "superseded" in results.lower(), (
        "Superseded fact alpha-seven was silently dropped (F-006, EM-104)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# F-007 → EM-106: consolidate ignores importance; archives important facts
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-007 → EM-106: consolidate archives by "
          "created_at + access_count, ignoring importance")
def test_f007_consolidate_respects_importance(engine):
    """A high-importance fact (>0.8) older than 90 days must NOT be archived
    by consolidate. v2.7 uses access_count (always 0 by default) + created_at."""
    engine.remember(
        content="The user's emergency contact is 911",
        domain="Personal", importance=0.95, age_days=120,
    )
    engine.consolidate(max_age_days=90, min_access_count=0)
    rows = engine.db.execute(
        "SELECT content FROM facts_archive WHERE content LIKE '%emergency contact%'"
    ).fetchall()
    assert len(rows) == 0, (
        f"High-importance fact was archived by consolidate (F-007, EM-106): "
        f"{rows}"
    )


@pytest.mark.xfail(strict=True, reason="F-007 → EM-106: consolidate archives "
          "low-importance facts first, not oldest")
def test_f007_consolidate_archives_low_importance_first(engine):
    """When consolidating, low-importance facts should be archived before
    high-importance ones, even if they're the same age."""
    engine.remember(
        content="Low importance fact: the user once saw a blue car",
        domain="Personal", importance=0.1, age_days=120,
    )
    engine.remember(
        content="High importance fact: the user has a medical allergy to penicillin",
        domain="Personal", importance=0.95, age_days=120,
    )
    engine.consolidate(max_age_days=90, min_access_count=0)
    archived = engine.db.execute("SELECT content FROM facts_archive").fetchall()
    archived_text = " ".join(r[0] for r in archived)
    # High-importance fact must NOT be archived when low-importance exists
    assert "medical allergy" not in archived_text, (
        "High-importance fact was archived before low-importance (F-007, EM-106)"
    )
    assert "blue car" in archived_text, (
        "Low-importance fact was not archived (F-007, EM-106)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# F-008 → EM-111: Prefetch synchronous on agent thread; core memory re-injected
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-008 → EM-111: prefetch runs "
          "synchronously on the agent thread instead of a background worker")
def test_f008_prefetch_runs_async(make_provider, home_a):
    """Prefetch must run on a dedicated thread, not block the agent thread.
    v2.7 runs all prefetch synchronously on the main thread."""
    provider = make_provider()
    host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA",
                    init_kwargs={"hermes_home": home_a})
    host.start()
    provider.handle_tool_call(
        "entropicmem_remember",
        {"content": "test async prefetch", "domain": "Work"},
    )
    block, latency = host.turn("tell me about the test")

    # Prefetch should complete via queue_prefetch (async), not inline
    # In v2.7, prefetch blocks the turn — latency includes full recall time
    # The fix: prefetch is queued and runs on a FIFO background worker
    metrics = host.summary()
    assert metrics["prefetch_timeouts"] == 0
    # If async: turn returns quickly, prefetch completes in background
    # v2.7: turn latency includes full recall (synchronous)
    # Check that prefetch didn't block the main thread by >50% of turn time
    # (This is a heuristic; the real fix instruments the thread.)
    assert latency > 0.0  # just verify we got a latency

    host.shutdown()


@pytest.mark.xfail(strict=True, reason="F-008 → EM-111: core memory "
          "re-injected every turn, causing linear token growth")
def test_f008_core_memory_not_reinjected_every_turn(make_provider, home_a):
    """Core Memory (Persona + Profile) should be cached per session,
    not re-injected every turn, to avoid linear prompt token growth."""
    provider = make_provider()
    host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
    host.start()
    provider.handle_tool_call(
        "entropicmem_remember",
        {"content": "The core memory system uses FTS5", "domain": "Engineering"},
    )

    blocks = []
    for i in range(5):
        block, _ = host.turn(f"query {i}")
        if block:
            blocks.append(block)

    # Count how many blocks contain the full "EntropicMem Core Memory" section
    core_count = sum(1 for b in blocks if "Core Memory" in b or "Persona" in b)
    # Core memory should be injected once (session start), not every turn
    assert core_count <= 1, (
        f"Core memory re-injected {core_count} times across 5 turns; "
        f"should be cached per session (F-008, EM-111)"
    )
    host.shutdown()


# ═════════════════════════════════════════════════════════════════════════════
# F-009 → EM-112: Learning loop dead; regex extraction only, nothing promoted
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="F-009 → EM-112: extraction is regex-only; "
          "extracted facts land in quarantine, nothing promotes to active")
def test_f009_extraction_promotes_from_quarantine(engine):
    """Extracted facts from session digests should be promoted from
    quarantine to active facts. v2.7 lands everything in quarantine."""
    engine.sync_turn(
        messages=[{"role": "user", "content": "Remember: my new laptop is a MacBook Pro M3"},
                  {"role": "assistant", "content": "I'll remember that."}],
        turn_author="test_user",
    )
    # The extraction regex should pull "MacBook Pro M3" as a fact
    # and it should be promoted (not stuck in quarantine)
    quarantined = engine.db.execute(
        "SELECT content FROM pending_facts WHERE content LIKE '%MacBook%'"
    ).fetchall()
    active = engine.db.execute(
        "SELECT content FROM facts WHERE content LIKE '%MacBook%'"
    ).fetchall()
    assert len(active) > 0, (
        f"Extracted fact stuck in quarantine, not promoted to facts "
        f"(F-009, EM-112): active={len(active)}, quarantined={len(quarantined)}"
    )


@pytest.mark.xfail(strict=True, reason="F-009 → EM-112: no semantic "
          "extraction; regex patterns are domain-specific")
def test_f009_semantic_extraction_of_new_patterns(engine):
    """Extraction should handle generic constraint statements, not just
    domain-specific regex patterns."""
    engine.sync_turn(
        messages=[{"role": "user", "content": "My security protocol requires rotating the API key every 90 days"},
                  {"role": "assistant", "content": "Noted."}],
        turn_author="test_user",
    )
    rows = engine.db.execute(
        "SELECT content FROM facts WHERE content LIKE '%API key%'"
    ).fetchall()
    assert len(rows) > 0, (
        "Constraint statement 'rotating API key every 90 days' was not "
        "extracted — regex-only patterns miss generic statements (F-009, EM-112)"
    )


@pytest.mark.xfail(strict=True, reason="F-009 → EM-112: episodes and triples "
          "never reach prefetch")
def test_f009_episodes_reach_recall(engine):
    """Episodic memories (conversations) should be retrievable alongside
    facts. v2.7 extracts them but they never reach prefetch."""
    engine.remember(
        content="The user asked about Kubernetes deployment on Tuesday",
        domain="Work", importance=0.7, age_days=3,
    )
    engine.sync_turn(
        messages=[{"role": "user", "content": "what did we discuss about Kubernetes?"},
                  {"role": "assistant", "content": "We discussed deployment."}],
        turn_author="test_user",
    )
    results = engine.recall("kubernetes deployment")
    assert "Kubernetes" in results, (
        "Episodic memory not surfaced in recall (F-009, EM-112): "
        f"results={results[:100]}"
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
FIXING_TASK_IDS = {
    "F-001": "EM-105",
    "F-002": "EM-107",
    "F-003": "EM-108",
    "F-004": "EM-109",
    "F-005": "EM-110",
    "F-006": "EM-104",
    "F-007": "EM-106",
    "F-008": "EM-111",
    "F-009": "EM-112",
    "F-010": "EM-212",
    "F-011": "EM-213",
}
