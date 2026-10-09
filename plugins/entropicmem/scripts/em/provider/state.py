"""Per-session hook state (EM-401).

The provider object outlives a session; the state a *session* owns does not.
EM-401 collects the four fields the §4.1 hooks read or write into one holder so
the fields a later card adds have a home, and so ``recall_status`` — which must
reflect only the LAST prefetch, never a stale prior count — has exactly one
place to be told that count.

Deliberately small. EM-402 adds the :class:`~em.provider.identity.ScopeContext`
(this file holds no identity, on purpose: scoping is a privacy decision and
belongs to its own card) and EM-405 adds the persisted turn index.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The agent contexts the host may report in ``initialize()`` kwargs. Only the
#: first is allowed to write durable state (§4.1's ``sync_turn`` / tools rows).
PRIMARY = "primary"

AGENT_CONTEXTS = ("primary", "subagent", "cron", "flush")


@dataclass
class ProviderState:
    """Session-scoped bookkeeping, mutated on the agent and hook threads."""

    session_id: str = ""
    #: 'primary' | 'subagent' | 'cron' | 'flush' — absent on legacy hosts.
    agent_context: str = PRIMARY
    #: What the most recent :meth:`prefetch` injected; ``recall_status`` reads it.
    last_recall_count: int = 0
    #: sha256 of the core block as issued by the last ``system_prompt_block``.
    core_baseline: str = ""

    def writes_allowed(self) -> bool:
        """True only for the primary agent context.

        ``subagent`` | ``cron`` | ``flush`` turns must not write durable
        memory: a subagent's writes would pollute the profile, and cron's
        writes belong to the job worker, not to a turn hook.
        """
        return self.agent_context == PRIMARY

    def note_recall(self, count: int) -> None:
        """Record what the prefetch that just finished injected."""
        self.last_recall_count = int(count)
