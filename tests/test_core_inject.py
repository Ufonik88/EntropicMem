"""EM-116 (L8): Core Memory out of per-turn prefetch.

- config `core_inject_mode`: "system_prompt" (default) | "prefetch" (legacy).
- system_prompt mode: system_prompt_block() appends the screened
  CoreMemory.injection_block() capped at 2800 chars and records its hash.
- prefetch adds a ONE-LINE delta only if core changed since session start.
- CoreMemory.patch writes atomically (tmp + os.replace) and keeps
  .history/ snapshots.
"""


import pytest
from fake_host import FakeHost

from vault import CoreMemory

MARKER = "unit-alpha-7"


@pytest.fixture
def seeded(make_provider, home_a):
    provider = make_provider()
    core = CoreMemory(home_a / "entropicmem" / "vault")
    core.patch("persona", "## Identity", f"## Identity\nPersona marker {MARKER}")
    host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
    host.start()
    provider.handle_tool_call(
        "entropicmem_remember",
        {"content": "The core memory system uses FTS5 for retrieval", "domain": "Engineering"},
    )
    yield provider, host, core
    host.shutdown()


def _prefetch(provider, i):
    return provider.prefetch(f"what do you know about the core memory system round {i}")


class TestNoPerTurnReinjection:
    def test_core_injected_at_most_once_across_turns(self, seeded):
        # f008b repro contract: <= 1 core injection across 5 turns
        provider, host, _ = seeded
        blocks = [b for b in (_prefetch(provider, i) for i in range(5)) if b]
        assert blocks, "prefetch returned nothing; repro cannot run"
        core_count = sum(
            1 for b in blocks if MARKER in b or "Core Memory — Persona" in b
        )
        assert core_count <= 1, (
            f"Core memory re-injected {core_count} times across {len(blocks)} turns"
        )

    def test_legacy_prefetch_mode_keeps_core_block(self, make_provider, home_a):
        provider = make_provider({"core_inject_mode": "prefetch"})
        core = CoreMemory(home_a / "entropicmem" / "vault")
        core.patch("persona", "## Identity", f"## Identity\nPersona marker {MARKER}")
        host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
        host.start()
        block = provider.prefetch("what do you know about my persona")
        host.shutdown()
        assert MARKER in block, f"legacy mode lost the core block: {block[:200]}"


class TestSystemPromptInjection:
    def test_system_prompt_block_contains_core(self, seeded):
        provider, _, _ = seeded
        block = provider.system_prompt_block()
        assert MARKER in block, f"core memory missing from system prompt block: {block}"

    def test_core_part_capped_at_2800(self, seeded):
        provider, _, core = seeded
        core.patch("persona", f"Persona marker {MARKER}", "Persona marker " + "x" * 5000)
        block = provider.system_prompt_block()
        core_part = block[block.index("## Core Memory"):]
        assert len(core_part) <= 2800, (
            f"core injection not capped: {len(core_part)} chars"
        )

    def test_records_block_hash(self, seeded):
        provider, _, _ = seeded
        provider.system_prompt_block()
        assert getattr(provider, "_core_baseline", None), (
            "system_prompt_block did not record the core block hash"
        )


class TestDeltaOnlyOnChange:
    def test_no_delta_when_unchanged(self, seeded):
        provider, _, _ = seeded
        provider.system_prompt_block()
        block = _prefetch(provider, 1)
        assert MARKER not in block and "Core Memory" not in block, (
            f"core leaked into prefetch: {block[:200]}"
        )

    def test_one_line_delta_after_change(self, seeded):
        provider, _, core = seeded
        provider.system_prompt_block()
        _prefetch(provider, 1)
        core.patch("persona", f"Persona marker {MARKER}", f"Persona marker {MARKER} updated-later")
        block = _prefetch(provider, 2)
        lines = [ln for ln in block.splitlines() if "updated-later" in ln or "Core Memory" in ln]
        assert lines, f"no delta after core change: {block[:200]}"
        assert len(lines) == 1, f"delta is not one line: {lines}"
        assert "Core Memory — Persona" not in block, (
            "delta must not re-inject the whole core block"
        )


class TestCorePatchSafety:
    def test_patch_keeps_history_snapshot(self, make_provider, home_a):
        make_provider()  # seeds the vault template (Core/Persona.md)
        core = CoreMemory(home_a / "entropicmem" / "vault")
        core.patch("persona", "## Identity", f"## Identity\nPersona marker {MARKER}")
        history = home_a / "entropicmem" / "vault" / "Core" / ".history"
        files = list(history.glob("Persona.md.*")) if history.is_dir() else []
        assert files, f"no .history snapshot written: {history}"
        snapshot = files[-1].read_text(encoding="utf-8")
        assert MARKER not in snapshot, "snapshot should hold the PRE-patch content"

    def test_patch_content_applied(self, make_provider, home_a):
        make_provider()  # seeds the vault template (Core/Persona.md)
        core = CoreMemory(home_a / "entropicmem" / "vault")
        ok = core.patch("persona", "## Identity", f"## Identity\nPersona marker {MARKER}")
        assert ok
        assert MARKER in core.persona
