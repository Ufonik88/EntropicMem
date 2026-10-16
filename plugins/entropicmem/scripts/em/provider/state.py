"""Per-session hook state (EM-401).

The provider object outlives a session; the state a *session* owns does not.
EM-401 collects the four fields the §4.1 hooks read or write into one holder so
the fields a later card adds have a home, and so ``recall_status`` — which must
reflect only the LAST prefetch, never a stale prior count — has exactly one
place to be told that count.

EM-402 adds the :class:`~em.policy.scopes.ScopeContext` — the one §3.5 scope
the session runs under, narrowed per turn by ``with_author``. This file holds no
resolution *rules*: scoping is a privacy decision and lives in its own card
(``em.policy.scopes``); the identity probe that reports it to the host is
``em.provider.identity``. EM-405 adds the persisted turn index; EM-411 the
window ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..policy.scopes import ScopeContext

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
    #: §3.5's resolved scope for this session, narrowed per turn by
    #: ``with_author``. The default is "nothing resolved" — the v2
    #: single-owner, profile-wide context — so a provider that is driven before
    #: ``initialize`` behaves exactly as it did before EM-402.
    scope: ScopeContext = field(default_factory=ScopeContext)
    #: What the most recent :meth:`prefetch` injected; ``recall_status`` reads it.
    last_recall_count: int = 0
    #: sha256 of the core block as issued by the last ``system_prompt_block``.
    core_baseline: str = ""
    #: EM-405: the per-session turn counter. Incremented in ``on_turn_start``,
    #: persisted to the v3 store's ``meta`` as ``turn_index:<sid>`` so a restart
    #: continues the sequence, and stamped on the writes made during the turn
    #: (``source_turn``) — which is what makes the rewound-turn retraction
    #: (``source_turn >= turn``) find them.
    turn_index: int = 0
    #: The session ``turn_index`` belongs to; a mismatch means "reload".
    turn_index_session: str = ""
    #: EM-411: the window ledger. ``window_seq`` counts the user/assistant
    #: messages ``sync_turn`` has seen this session; the unsealed window is
    #: ``window_sealed + 1 .. window_seq``. Persisted to the v3 store's
    #: ``meta`` as ``window:<sid>`` so a restart continues the sequence —
    #: ranges never repeat, which is what the queue's one-key-one-row rule
    #: needs. ``window_turns`` counts the unsealed window's conversation
    #: turns (one per ``sync_turn`` with content), ``window_chars`` its text
    #: length — the two idle-floor dimensions; ``last_turn_ts`` is when
    #: ``on_turn_start`` last ran (idle detection; not persisted).
    window_seq: int = 0
    window_sealed: int = 0
    window_turns: int = 0
    window_chars: int = 0
    window_session: str = ""
    last_turn_ts: float = 0.0

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
