"""The shared job registry builder (EM-410).

One place decides which handlers a fresh worker carries, so the CLI's
``entropicmem worker run`` and the provider's in-process worker cannot drift.
Stdlib-only (plan §3.2): the handler factories come from this repository, not
from the host.

The formation types (``extract_session`` / ``extract_window``) are
deliberately absent: ``em.jobs.BUILT_FORMATION_HANDLERS`` ships empty until
EM-502 registers the handler that serves them, and a worker must not claim
work nothing can run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from .worker import HandlerRegistry

#: The job types this build carries a handler for.
KNOWN_JOB_TYPES = ("backup", "link", "embed", "embed_backfill", "retract_turns")


def build_registry(
    db_path: "str | Path", *, types: Optional[Iterable[str]] = None
) -> HandlerRegistry:
    """A ``HandlerRegistry`` for *db_path*, restricted to *types* when given.

    Selecting ``embed`` or ``embed_backfill`` builds one ``EmbeddingService``
    for the pair. Construction is configuration-reading only — the backend
    warms lazily inside the handler, so a request thread never pays for it
    (§4.1: the model load belongs to the worker thread).
    """
    selected = list(types) if types is not None else list(KNOWN_JOB_TYPES)
    registry = HandlerRegistry()
    if "backup" in selected:
        from ..store.backup import BackupManager, make_backup_handler

        registry.register("backup", make_backup_handler(BackupManager(db_path)))
    if "link" in selected:
        from ..formation.entity_linker import make_link_handler

        registry.register("link", make_link_handler())
    if "retract_turns" in selected:
        from ..store.retract import make_retract_handler

        registry.register("retract_turns", make_retract_handler())
    if "embed" in selected or "embed_backfill" in selected:
        from ..embeddings.jobs import make_embed_backfill_handler, make_embed_handler
        from ..embeddings.service import EmbeddingService

        service = EmbeddingService(str(db_path))
        if "embed" in selected:
            registry.register("embed", make_embed_handler(service))
        if "embed_backfill" in selected:
            registry.register("embed_backfill", make_embed_backfill_handler(service))
    return registry


__all__ = ["KNOWN_JOB_TYPES", "build_registry"]
