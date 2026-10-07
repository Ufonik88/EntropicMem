"""``em.retrieval`` — the v3 retrieval layer (S3, cards EM-302…EM-305).

This package is being built card by card. What is here now:

* ``candidates.scope_sql`` — the §3.5 scope rule as SQL, the single helper every
  generator will filter through, with a truth table that is cross-checked against
  ``MemoryStore._in_scope`` (the authoritative implementation) rather than
  restated.

What is deliberately **not** here yet, and why: the ``RetrievalContext`` and
``Candidate`` shapes, and the generator functions themselves. The master plan
lives on the owner's machine (plan §1), and neither the repo nor the card summary
in ``REMAINING_PLAN.md`` §6.2 records what a ``Candidate`` carries. Designing it
from imagination would put EM-304 ("exactly §3.6 formulas", a deterministic
``score desc, updated_at desc, id asc`` tie-break) on sand, so the plan's size
guard says record the gap instead. See ``NEXT_CHUNK.md`` Part B for the precise
list of what is missing.

Stdlib-only, like everything under ``em`` (plan §3.2).
"""
