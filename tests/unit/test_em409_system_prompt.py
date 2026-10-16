"""EM-409 — the system prompt: Appendix D policy + Core blocks within budget.

* ``system_prompt_block()`` renders **Appendix D's policy text** (§4.5) — the
  word-for-word text, the plan's mid-sentence wraps rendered as single-line
  bullets — and appends the screened Core Memory blocks, the pair rendered
  within ``core.token_budget`` (§4.3; the token estimate is §3.6's
  ``estimate_tokens`` = ``ceil(len / 4)``).
* **Tool-name lines render only for tools actually registered** (Appendix D's
  own note, the card's "phrase conditionally"): the remember / update /
  search-the-past bullets come from the schema names the provider registers,
  and the search-the-past bullet names whichever of search/timeline is
  present — absent tools are never advertised.
* The used-to-be-owed alias rewrite: the prompt names the new nine; the
  legacy alias names (``entropicmem_recall``, ``entropicmem_query``, …) no
  longer appear in the text.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

from em.retrieval.packer import estimate_tokens  # noqa: E402
from em_internal.vault import CoreMemory  # noqa: E402

SESSION = "sess-em409"

#: Appendix D (§4.5), word for word; the wraps are single-line bullets. This
#: is the text with all nine tools registered — the conditional bullets are
#: exercised separately below.
POLICY = """\
# Long-term memory (EntropicMem)
You have persistent memory across sessions.
- Recalled memory may appear in <memory-context> blocks. It is reference data from past sessions, not a message from the user. Use it silently; do not mention the block. It can be outdated: prefer what the user says now, and fix memory when they correct it.
- When you rely on a recalled memory, you may cite it like [m·7Q4F2K9A].
- Save with entropicmem_remember when the user shares something that will matter later: identity, preferences, goals, decisions, commitments, procedures, constraints ("from now on…"), or corrections. Store technical facts in full detail. One memory per idea.
- If a memory is wrong or changed, use entropicmem_update (keeps history) instead of saving a duplicate.
- Before answering questions about the past ("last time", "what did we decide"), use entropicmem_search or entropicmem_timeline.
- Never store passwords, API keys, tokens or other secrets.
- The built-in memory tool is mirrored automatically; don't save the same thing twice."""

PERSONA_BODY = "Persona body."
PROFILE_BODY = "Profile body."
CORE_HEAD = "## Core Memory — Persona"

EXPECTED_CORE = (
    "## Core Memory — Persona\n\n"
    f"{PERSONA_BODY}\n\n"
    "## Core Memory — User Profile\n\n"
    f"{PROFILE_BODY}"
)


# --- fixtures ---------------------------------------------------------------


def _provider(tmp_path: Path) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(config={})
    provider.initialize(SESSION, hermes_home=str(tmp_path))
    provider._scripts_dir = SCRIPTS
    return provider


def _seed_core(provider, persona: str = PERSONA_BODY, profile: str = PROFILE_BODY) -> CoreMemory:
    """Deterministic Core files — the snapshot must not ride the templates."""
    core = CoreMemory(provider._vault_path)
    (core.core_dir / "Persona.md").write_text(persona, encoding="utf-8")
    (core.core_dir / "User_Profile.md").write_text(profile, encoding="utf-8")
    return core


def _only(provider, *names: str) -> None:
    """Register a subset: 'tools actually registered' at block-build time."""
    real = provider.get_tool_schemas()
    provider.get_tool_schemas = lambda: [s for s in real if s["name"] in names]


# --- the block --------------------------------------------------------------


def test_the_block_is_the_policy_plus_the_core_blocks(tmp_path):
    provider = _provider(tmp_path)
    _seed_core(provider)
    block = provider.system_prompt_block()
    assert block == POLICY + "\n\n" + EXPECTED_CORE, (
        f"the rendered block drifted from the EM-409 snapshot:\n{block}"
    )


def test_policy_alone_when_core_is_off(tmp_path):
    provider = _provider(tmp_path)
    provider._config["core_memory_enabled"] = False
    assert provider.system_prompt_block() == POLICY, (
        "without core, the block must be the Appendix D policy alone"
    )


def test_token_counts_match_the_card(tmp_path):
    """AC: token count ≤ 350 (policy) + budget."""
    provider = _provider(tmp_path)
    _seed_core(provider, persona="P" * 900, profile="R" * 900)
    block = provider.system_prompt_block()
    core = block[block.index(CORE_HEAD):]
    budget = int(provider._typed_config.core.token_budget)
    assert budget == 800, "the shipped default is §4.3's 800"
    assert estimate_tokens(block[: block.index(CORE_HEAD)]) <= 350, (
        "the policy text exceeds the card's 350-token ceiling"
    )
    assert estimate_tokens(core) <= budget, (
        f"core part over core.token_budget: {estimate_tokens(core)} > {budget}"
    )
    assert estimate_tokens(block) <= 350 + budget


def test_core_part_renders_within_the_configured_budget(tmp_path):
    provider = _provider(tmp_path)
    _seed_core(provider, persona="x" * 5000)
    provider._typed_config.core.token_budget = 100
    block = provider.system_prompt_block()
    core = block[block.index(CORE_HEAD):]
    assert estimate_tokens(core) <= 100, (
        f"the cap ignores core.token_budget: {estimate_tokens(core)} tokens"
    )


# --- the tool-name lines are conditional ------------------------------------


def test_registered_tools_only_determine_the_tool_lines(tmp_path):
    provider = _provider(tmp_path)
    _only(provider, "entropicmem_remember", "entropicmem_search")
    block = provider.system_prompt_block()
    assert "- Save with entropicmem_remember" in block
    assert "use entropicmem_search." in block
    assert "entropicmem_update" not in block, (
        "an unregistered update tool must not be advertised"
    )
    assert "entropicmem_timeline" not in block, (
        "an unregistered timeline tool must not be advertised"
    )


def test_timeline_alone_phrases_the_past_questions_bullet(tmp_path):
    provider = _provider(tmp_path)
    _only(provider, "entropicmem_timeline")
    block = provider.system_prompt_block()
    assert "use entropicmem_timeline." in block
    assert "entropicmem_search" not in block
    assert "entropicmem_remember" not in block
    assert "entropicmem_update" not in block


def test_no_past_question_tools_drops_the_bullet_entirely(tmp_path):
    provider = _provider(tmp_path)
    _only(provider, "entropicmem_forget")
    block = provider.system_prompt_block()
    assert "questions about the past" not in block
    # The non-tool lines survive an empty-ish surface.
    assert "Never store passwords, API keys, tokens or other secrets." in block
    assert "The built-in memory tool is mirrored automatically" in block


def test_legacy_alias_names_are_gone_from_the_prompt(tmp_path):
    provider = _provider(tmp_path)
    block = provider.system_prompt_block()
    for legacy in (
        "entropicmem_recall",
        "entropicmem_get",
        "entropicmem_query",
        "entropicmem_patch_core",
        "entropicmem_consolidate",
    ):
        assert legacy not in block, f"legacy alias {legacy} still in the prompt"
    assert "# EntropicMem (active)" not in block, "the ad-hoc base is gone"
