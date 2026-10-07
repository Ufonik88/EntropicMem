"""The v2 engine's internal modules, under a package namespace (EM-212).

These six modules used to sit at the top level of ``scripts/``, which
``_backend.resolve_paths`` puts on ``sys.path``. The Hermes host runs many
plugins in one process, so a bare ``import vault`` resolves through the shared
``sys.modules``: another plugin's ``vault`` (or ``index``, ``security``,
``policy``, ``embeddings``, ``retrieval``) would be returned instead of ours,
and ours would shadow theirs.

Being a package means the import system registers ``em_internal.vault`` and
friends, never the bare names. ``tests/test_backend_namespace.py`` pins the
acceptance criterion: load the engine in a clean interpreter the way the plugin
does, and none of the six unprefixed names may appear in ``sys.modules``.

The rest of ``scripts/`` is not moved here yet; the card's AC names these six.
"""
