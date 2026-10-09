"""The §4.1 hook surface, as this repo sees it (EM-401).

One table, three readers:

* :mod:`em.provider.hooks` — the budgets a wrapped hook is held to;
* the host harness — which drives **every** row, so a hook the provider stops
  implementing fails a test rather than going unnoticed;
* the contract test — which asserts the pinned ``MemoryProvider`` base class is
  fully implemented, with anything absent explicitly deferred to the card that
  lifts it and a reason that says why.

Adding a hook to the provider without a row here fails that test. A row whose
status is ``deferred`` must name its card: "not yet" is not a reason, a card
number is. ``on_delegation`` and ``identity_signature`` are the two deferred
rows today, and both are *optional* on the base class, so the host never calls
them until they land.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .hooks import HOOK_BUDGETS

AGENT = "agent"
PREFETCH_THREAD = "prefetch thread (8 s join)"
MEM_SYNC = "mem-sync worker"
AGENT_OR_BG = "agent or bg worker"
CALLER = "caller (host drains 5 s)"
CLI = "CLI"
GATEWAY = "gateway (per inbound message)"

#: Statuses a row may carry.
IMPLEMENTED = "implemented"
DEFERRED = "deferred"


@dataclass(frozen=True)
class HookSpec:
    """One row of §4.1's hook table."""

    name: str
    thread: str
    #: §4.1's budget in milliseconds — the number ``fail_soft`` enforces.
    budget_ms: float
    status: str = IMPLEMENTED
    #: The card that lands a deferred hook, and why it is not here yet.
    deferred_to: str = ""
    defer_reason: str = ""
    #: ``provides_hooks`` in plugin.yaml must list it (the catalog review
    #: verifies the plugin against those lists — never rename or drop one
    #: outside a release that re-pins the entry).
    in_manifest: bool = False


def _spec(name: str, thread: str, *, in_manifest: bool = False, **kw) -> HookSpec:
    return HookSpec(
        name=name,
        thread=thread,
        budget_ms=HOOK_BUDGETS[name],
        in_manifest=in_manifest,
        **kw,
    )


HOOK_SURFACE: Tuple[HookSpec, ...] = (
    _spec("name", AGENT),
    _spec("is_available", AGENT),
    _spec("unavailable_reason", AGENT),
    _spec("initialize", AGENT),
    _spec("system_prompt_block", AGENT),
    _spec("on_turn_start", AGENT, in_manifest=True),
    _spec("prefetch", PREFETCH_THREAD),
    _spec("recall_status", AGENT),
    _spec("queue_prefetch", MEM_SYNC),
    _spec("sync_turn", MEM_SYNC),
    _spec("get_tool_schemas", AGENT),
    _spec("handle_tool_call", AGENT),
    _spec("on_memory_write", AGENT, in_manifest=True),
    _spec("on_session_switch", AGENT_OR_BG, in_manifest=True),
    _spec("on_pre_compress", AGENT, in_manifest=True),
    _spec("on_delegation", AGENT, status=DEFERRED, deferred_to="EM-405",
          defer_reason=(
              "EM-405's AC owns the delegation episode ('delegation creates an "
              "episode'); the signature lands with the behaviour, not before"
          )),
    _spec("on_session_end", AGENT_OR_BG, in_manifest=True),
    _spec("backup_paths", CLI),
    _spec("shutdown", CALLER),
    _spec("get_config_schema", CLI),
    HookSpec(  # §3.5 / EM-402: config-derived, cached by mtime, called per message
        name="identity_signature",
        thread=GATEWAY,
        budget_ms=HOOK_BUDGETS["identity_signature"],
        status=DEFERRED,
        deferred_to="EM-402",
        defer_reason=(
            "§3.5 owns the identity mapping and its mtime cache; EM-402 lands "
            "it with ScopeContext so the two cannot disagree"
        ),
    ),
    _spec("save_config", CLI),
)


def specs() -> Tuple[HookSpec, ...]:
    """Every row of the §4.1 surface."""
    return HOOK_SURFACE


def implemented() -> Tuple[str, ...]:
    """The hook names this provider must implement today."""
    return tuple(s.name for s in HOOK_SURFACE if s.status == IMPLEMENTED)


def deferred() -> Dict[str, HookSpec]:
    """``{hook name: spec}`` for hooks deliberately not yet implemented."""
    return {s.name: s for s in HOOK_SURFACE if s.status == DEFERRED}


def manifest_hooks() -> Tuple[str, ...]:
    """Hooks that must appear in plugin.yaml's ``provides_hooks``."""
    return tuple(s.name for s in HOOK_SURFACE if s.in_manifest)


def _provides(provider: object, name: str) -> bool:
    """Does *provider* expose *name* the way the host's contract expects?

    A property row (``name``) is provided when reading it yields a value; a
    method row when the attribute is callable.
    """
    if isinstance(getattr(type(provider), name, None), property):
        return getattr(provider, name, None) is not None
    return callable(getattr(provider, name, None))


def audit(provider: object) -> Tuple[str, ...]:
    """Problems with *provider* against the surface, as human-readable lines.

    Empty means the class implements every row marked ``implemented`` and omits
    every row marked ``deferred``. The contract test asserts this is empty; a
    runtime caller (a future ``doctor``) can use the same answer.
    """
    problems = []
    for spec in HOOK_SURFACE:
        has = _provides(provider, spec.name)
        if spec.status == IMPLEMENTED and not has:
            problems.append(f"{spec.name}: implemented per §4.1 but missing on the provider")
        if spec.status == DEFERRED and has:
            problems.append(
                f"{spec.name}: deferred to {spec.deferred_to} but implemented — "
                "flip the row in em.provider.provider"
            )
    return tuple(problems)
