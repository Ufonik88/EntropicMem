"""§3.5's scoping & visibility policy (EM-402).

Pure resolution rules — no host imports, no DB reads, no ``HERMES_HOME``. The
provider feeds this package the host's ``initialize()`` kwargs and its config,
and gets back the one :class:`~em.policy.scopes.ScopeContext` a session (and,
through ``with_author``, each turn) runs under. The storage-side predicate lives
in :mod:`em.store.types` (``Scope``, ``row_is_owner_only``,
``may_read_owner_only``, ``chat_in_scope``); this package is what *produces* the
scope those functions are handed.
"""

from .scopes import (  # noqa: F401
    DEFAULT_OWNER_USER_ID,
    SCOPE_MODES,
    ScopeContext,
    resolve_scope_mode,
)
