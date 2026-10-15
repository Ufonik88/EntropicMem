"""The ``retract_turns`` job (EM-405): run one rewound-turn retraction.

§4.1's rewound ``on_session_switch`` does not delete anything itself — the turn
thread only enqueues, so an ``/undo`` costs one short transaction on a 30 ms
budget. This module is the other half: the handler that the worker (the
operator's ``entropicmem worker run`` today; EM-410's in-process worker after
that) runs to soft-delete the undone turn's live rows.

The work itself is ``MemoryStore.retract_session`` — one transaction, each row
on the audited and reversible ``retracted_by_undo`` edge. The handler adds only
the queue's contract: a malformed payload is a *permanent* failure (retrying a
missing session id would never fix it), and a re-run converges because the
target set is re-queried every time.
"""

from __future__ import annotations

from ..jobs.worker import PermanentJobError
from .memories import MemoryStore

#: The job type the rewound ``on_session_switch`` enqueues.
RETRACT_JOB_TYPE = "retract_turns"

#: Recorded as the audit actor. The reason on the row itself is
#: ``retracted_by_undo`` (``em.store.types``); this names the mechanism.
RETRACT_ACTOR = "retract_turns"


def make_retract_handler():
    """Handler for ``retract_turns`` jobs: ``{"session_id": str, "from_turn": int}``."""

    def handle(job, ctx) -> None:
        session_id = str(job.payload.get("session_id") or "")
        from_turn = job.payload.get("from_turn")
        # bool is an int subclass and True would mean "turn 1"; refuse it.
        if (
            not session_id
            or not isinstance(from_turn, int)
            or isinstance(from_turn, bool)
            or from_turn <= 0
        ):
            raise PermanentJobError(
                "retract_turns needs a non-empty session_id and a positive integer from_turn"
            )

        with ctx.store.transaction() as conn:
            MemoryStore(conn).retract_session(session_id, from_turn, actor=RETRACT_ACTOR)

    return handle


__all__ = ["RETRACT_JOB_TYPE", "RETRACT_ACTOR", "make_retract_handler"]
