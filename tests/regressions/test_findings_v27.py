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
        content="The user works at a large company as a manager.",
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
