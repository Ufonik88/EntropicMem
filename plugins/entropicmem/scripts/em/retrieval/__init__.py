"""``em.retrieval`` — the v3 retrieval layer (S3, cards EM-301…EM-310).

Built card by card. Here now:

* ``candidates`` — EM-302's candidate generators (§3.6): ``bm25``, ``entity``,
  ``episodic``, ``recent``, ``pinned``, plus ``scope_sql`` (the §3.5 rule as
  SQL) and the ``Candidate``/``RetrievalContext`` shapes.
* ``query`` — the ``AnalyzedQuery`` shape those generators consume. EM-301 adds
  the analyzer that *produces* one.
* ``temporal`` — the ``TimeRange`` shape a query may carry. EM-310 adds the
  parser that produces one.

Recorded gaps, so nobody has to rediscover them:

* **``vector``** is §3.6's sixth generator and is not implemented. §3.6 gates it
  on an embedding backend and forbids re-reading vector blobs per query, so it
  lands with the backend and the numpy cache in EM-303 (``GENERATOR_LIMITS``
  already carries its ``k``).
* **Chat scoping.** §3.5's ``scope_mode=chat`` adds ``scope_chat`` to reads, and
  its owner rule also looks at ``visibility``. ``MemoryStore._in_scope`` — the
  authoritative implementation, pinned in Chunk 7.2 — covers profile, user and
  the owner-only tier only, and ``scope_sql`` matches it exactly on purpose.
  The ``chat``/``visibility`` halves arrive with ``ScopeContext`` in EM-402.
* **"Current session" in ``recent``.** §3.6's ``recent`` reads "in current
  session / last 48 h"; the 48 h window is implemented, and the session half
  needs a session id that EM-302's ``RetrievalContext`` does not carry.

Stdlib-only, like everything under ``em`` (plan §3.2).
"""
