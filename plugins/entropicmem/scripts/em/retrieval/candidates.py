"""Candidate generators — EM-302. Contains the scope helper so far.

The generators themselves are not written yet: their ``Candidate`` return shape
is not recorded anywhere in this repo (see the package docstring and
``NEXT_CHUNK.md`` Part B). What *is* fully specified is ``scope_sql``, the single
helper every generator must filter through, so it is here — and it is the part
worth getting right first, because it is where the §3.5 owner-only rule has to be
expressed in SQL without drifting from the predicate that defines it.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from ..store.types import OWNER_ONLY_TIERS, Scope, may_read_owner_only

__all__ = ["scope_sql"]


def scope_sql(scope: Scope, *, table: str = "m") -> Tuple[str, List[Any]]:
    """The §3.5 read rule as a SQL fragment plus its parameters.

    Returns ``(clause, params)`` for ``WHERE <clause>`` against a table aliased
    ``table``. The clause is exactly ``MemoryStore._in_scope``:

    * same profile, and
    * the row is the caller's own or profile-wide, and
    * an owner-only tier (``sensitive``/``secret``) is excluded unless the caller
      is the owner context.

    The owner decision comes from :func:`em.store.types.may_read_owner_only`, the
    same function ``_in_scope`` calls, so the SQL form and the row-by-row form
    cannot disagree about who the owner is — and
    ``tests/unit/test_em_retrieval_scope_sql.py`` cross-checks them against real
    rows rather than trusting that.

    ``table`` defaults to ``m`` because every retrieval query joins ``memories``
    as ``m``; pass ``table=""`` for a bare query.
    """
    prefix = f"{table}." if table else ""
    clause = (
        f"{prefix}scope_profile = ?"
        f" AND ({prefix}scope_user = ? OR {prefix}scope_user = '')"
    )
    params: List[Any] = [scope.profile, scope.user]

    if not may_read_owner_only(scope):
        # Exclude the owner-only tiers. The tier names come from the same tuple
        # `_in_scope` consults, so adding one there cannot forget the SQL side.
        placeholders = ", ".join("?" for _ in OWNER_ONLY_TIERS)
        # No `IS NULL` escape is needed: `sensitivity` is NOT NULL in the schema
        # (pinned by a test), and if that ever changes, `NOT IN` excludes the
        # NULLs — the safe direction, since a row of unknown tier must not reach
        # a non-owner.
        clause += f" AND {prefix}sensitivity NOT IN ({placeholders})"
        params.extend(OWNER_ONLY_TIERS)

    return clause, params
