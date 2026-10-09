"""``em.retrieval`` — the v3 retrieval layer (S3, cards EM-301…EM-310).

The pipeline §3.6 describes, as far as it is built:

    query ─▶ query.analyze ─▶ candidates.* ─▶ fusion.fuse ─▶ fusion.rank
          ─▶ gate.apply_gate ─▶ diversity.collapse ─▶ diversity.mmr
          ─▶ packer.pack ─▶ provider.render (EM-307; not called from pipeline.retrieve)

| Module | Card | What it holds |
|---|---|---|
| ``query`` | EM-301 | ``analyze()`` → ``AnalyzedQuery``: normalisation, IDF term selection, intent, entity detection, the common temporal shapes |
| ``stopwords`` | EM-301 | The 180-word list (the same set v2 uses) |
| ``temporal`` | EM-310 | ``TimeRange``, the window a query may carry |
| ``candidates`` | EM-302 | The generators (``bm25``, ``entity``, ``episodic``, ``recent``, ``pinned``), ``Candidate``, ``RetrievalContext``, and ``scope_sql`` — the §3.5 rule as SQL |
| ``fusion`` | EM-304 | Weighted RRF over the generators that ran, the feature rerank, the deterministic tie-break, the explanation, and the scoped feature loader |
| ``gate`` | EM-305 | The abstention gate: the four support conditions, then the score threshold |
| ``diversity`` | EM-305 | The supersession/duplicate collapse and MMR |
| ``packer`` | EM-307 | Greedy token pack (``ceil(len/4)``, full else summary else skip). The renderer is ``em.provider.render`` |

Recorded gaps, so nobody has to rediscover them:

* **``vector`` searches stored embeddings and does not embed (EM-303, partial).**
  It runs only when ``retrieve`` is given a query vector and a model, and only
  when ≥ 50% of the active memories in scope have a usable vector for that
  model. The default call passes neither, so the generator returns ``[]``,
  does no SQL, and the gate's cosine condition stays off. Still absent: the
  embedding backends, the embed job, the numpy cache, and MMR's embedding
  path (MMR is still token Jaccard).
* **Chat scoping.** §3.5's ``scope_mode=chat`` adds ``scope_chat`` to reads, and
  its owner rule also looks at ``visibility``. Both are now implemented —
  ``scope_sql`` and ``_in_scope`` share ``chat_in_scope`` and ``row_is_owner_only``
  — and ``chat``/``chat_type``/``author`` arrive with ``ScopeContext`` in EM-402.
* **"Current session" in ``recent``.** §3.6's ``recent`` reads "in current session
  / last 48 h"; the 48 h window is implemented, and the session half needs a
  session id that EM-302's ``RetrievalContext`` does not carry.
* **Config.** ``ranking.*`` (EM-304) and ``gate.*`` (EM-305) are dataclasses
  carrying §3.6's numbers as overridable defaults. EM-306 committed tuned
  scalars in ``em/config.py`` and **nothing here reads them** — they reach
  call sites via EM-401–403, and the typed loader is EM-407. ``query.analyze``'s
  ``extra_stopwords`` and §3.6's optional ``query_rewrite`` are in the same
  position.
* **The eval adapter does not render (EM-307).** ``packer.load_pack_items`` and
  ``em.provider.render.render_retrieval`` turn a gated ``Retrieval`` — rankings
  plus the predecessors the collapse kept — into §3.6's block. The adapter
  still emits ``- [full id]`` bullets. Short citations would stop
  ``parse_injected_ids`` matching, and the budget can drop an id the old
  bullet emitted, so that switch is a separate change. ``cite="full"`` is the
  seam.
* **``why_retrieved_tokens``.** ``fusion.legacy_tokens`` produces §3.6's flat
  v2-shaped reason list; putting it on the recall path is the provider's card, as
  is the ``include_history`` flag the EM-305 AC names (this layer supplies the
  predecessors it needs, and ``MemoryStore.history()`` walks the whole chain).

Stdlib-only, like everything under ``em`` (plan §3.2).
"""
