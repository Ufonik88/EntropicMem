"""EM-003 acceptance-criteria tests.

1. Smoke: drive 20 turns of the CURRENT EntropicMem provider through FakeHost
   and record metrics (prefetch latency distribution, injection sizes,
   cumulative prompt tokens with host replay, spill/timeout counters).
2. Two-profile: two FakeHosts with different HERMES_HOMEs in one process must
   not see each other's memories (regression guard for the v2.7 bleed, fixed
   in EM-102: the engine resolved the profile from os.environ['HERMES_HOME'],
   the decoy the harness sets post-initialize).
"""

import time

import pytest
from fake_host import FakeHost

# Deterministic, generic corpus (public-repo rule: no personal data).
FACTS = [
    ("The user's favourite editor is Neovim with the LSP plugin.", "Knowledge"),
    ("The staging deploy target is host zeta-7 behind nginx.", "Infrastructure"),
    ("The quarterly budget review happens on the last Friday.", "Operations"),
    ("Project Falcon uses SQLite FTS5 for its search index.", "Engineering"),
    ("The preferred meeting slot is late morning UTC.", "Operations"),
]

TURNS = [
    "what editor do I code in",
    "how should I deploy to staging",
    "when is the budget review",
    "what database does project falcon search use",
    "any preference about meeting times",
    "tell me about the neovim setup",
    "what runs in front of zeta-7",
    "who owns the quarterly review cadence",
    "how does falcon index its documents",
    "what is my coding tool again",
    "summarize what you know about our infra",
    "is there anything about deployment targets",
    "what search technology do we track",
    "any note about calendars or schedules",
    "what would you change about the editor config",
    "walk me through the staging pipeline",
    "which meetings are blocked out",
    "what facts exist about project falcon",
    "anything relevant for a code review today",
    "wrap up: what should I remember from this session",
]

TRIVIAL = {"hi", "thanks!", "continue", "ok", "yes"}


def _seed_provider(provider):
    """remember() some facts through the provider's own tool surface."""
    for content, domain in FACTS:
        out = provider.handle_tool_call(
            "entropicmem_remember", {"content": content, "domain": domain, "importance": 0.8}
        )
        assert '"ok": true' in out, out


@pytest.fixture()
def smoke_metrics_path(tmp_path):
    return tmp_path / "harness-smoke-metrics.json"


def test_smoke_20_turns(make_provider, home_a, smoke_metrics_path):
    """AC-1: 20 turns through the current provider via FakeHost; metrics recorded."""
    import json

    provider = make_provider()
    host = FakeHost(provider, hermes_home=home_a, platform="cli",
                    init_kwargs={"user_id": "u-smoke", "agent_identity": "homeA"})
    host.start()
    _seed_provider(provider)

    injected_turns = 0
    for i, text in enumerate(TURNS):
        block, latency = host.turn(text)
        assert isinstance(block, str) and isinstance(latency, float)
        if block:
            injected_turns += 1
            assert block.startswith("<memory-context>")
        host.drain(timeout=10)  # keep FIFO close to real cadence between turns

    metrics = host.summary()
    assert metrics["turns"] == 20
    assert metrics["prefetch_timeouts"] == 0, "no prefetch may exceed the 8 s host join"
    assert metrics["errors"] == [], f"provider raised through host hooks: {metrics['errors']}"
    # injection actually happened on most knowledge turns
    assert injected_turns >= 10, f"only {injected_turns}/20 turns injected memory"
    # cumulative tokens grew because earlier blocks replay into every later prompt
    cum = metrics["cumulative_prompt_tokens"]
    assert cum[-1] > cum[4], "replayed-block token accounting did not grow"

    drain_state = host.shutdown()
    assert drain_state["status"] == "drained"

    payload = {"captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "metrics": metrics,
               "injected_turns": injected_turns}
    smoke_metrics_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert smoke_metrics_path.is_file()


def test_two_profiles_do_not_bleed(make_provider, home_a, home_b):
    """AC-2: distinct homes in ONE process must not share memories.

    Demonstrates the v2.7 profile bleed (fixed by EM-102): the engine resolved
    `profile_id` from os.environ['HERMES_HOME'] — which the harness poisons
    with a decoy after initialize — so facts written under profile A landed
    stamped as the decoy/wrong profile, and A's recall could surface B's rows.
    """
    provider_a = make_provider()
    provider_b = make_provider()
    host_a = FakeHost(provider_a, hermes_home=home_a, agent_identity="homeA")
    host_b = FakeHost(provider_b, hermes_home=home_b, agent_identity="homeB")
    host_a.start()
    host_b.start()

    out = provider_a.handle_tool_call(
        "entropicmem_remember",
        {"content": "Alpha-only secret: the build server passphrase prefix is "
                    "al" + "pha-" + "seven."},
    )
    assert '"ok": true' in out
    out = provider_b.handle_tool_call(
        "entropicmem_remember",
        {"content": "Beta-only secret: the build server passphrase prefix is "
                    "be" + "ta-" + "nine."},
    )
    assert '"ok": true' in out

    # Separate DBs: each home's memory.db has its own single fact.
    from memory_engine import MemoryEngine

    with MemoryEngine(home_a / "entropicmem" / "memory.db") as eng:
        rows_a = eng.db.execute("SELECT content, profile_id FROM facts").fetchall()
    with MemoryEngine(home_b / "entropicmem" / "memory.db") as eng:
        rows_b = eng.db.execute("SELECT content, profile_id FROM facts").fetchall()
    assert len(rows_a) == 1 and len(rows_b) == 1

    # The bleed: profile stamp must be the profile's own slug, not the decoy
    # home the env now points at. v2.7 reads os.environ AFTER initialize →
    # profile_id == "decoy-wrong-home" for BOTH profiles.
    assert rows_a[0][1] == "homeA", f"profile bleed: A's fact is stamped {rows_a[0][1]!r}"
    assert rows_b[0][1] == "homeB", f"profile bleed: B's fact is stamped {rows_b[0][1]!r}"

    # And recall stays in-profile: A asking about the passphrase must not surface B's.
    block_a, _ = host_a.turn("what is the build server passphrase prefix")
    assert "alpha-seven" in block_a
    assert "beta-nine" not in block_a

    host_a.shutdown()
    host_b.shutdown()

