"""Hermes provider package (S4).

EM-307 lands the renderer here (``render.py``); EM-401 slice 1 lands the hook
skeleton: ``hooks.py`` (``fail_soft``, the §4.1 budgets and the per-hook
metrics), ``state.py`` (the per-session ``ProviderState``) and ``provider.py``
(the §4.1 surface table the harness drives and the contract test audits).
The ScopeContext (EM-402), the PrefetchService (EM-403) and the provider class
itself are still to come — the class stays in ``plugins/entropicmem/__init__.py``
until the move is its own reviewed chunk.

Stdlib-only, like the rest of ``em``: nothing here imports the Hermes host
or reads ``em/config.py``.
"""
