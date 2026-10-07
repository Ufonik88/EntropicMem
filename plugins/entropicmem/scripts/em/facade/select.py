"""Choose the engine that matches a store's schema (EM-211, Chunk 9).

The provider used to construct the v2 ``MemoryEngine`` unconditionally. This
module picks instead, from the store's own ``PRAGMA user_version``: a v2 store
gets ``MemoryEngine``, a v3 store gets the facade.

**The check is read-only, and it runs before any engine is constructed.** That
ordering is the whole point. ``V3Engine.__init__`` calls ``migrate()``, so
constructing it over a v2 store would perform the v2-to-v3 cutover as a side
effect of merely opening the store — and the cutover is the owner's deliberate
act, not something that happens because the provider started up. Selection must
therefore be decided first, from a peek that cannot write.

The version rule matches what ``migrate()`` already assumes:

* ``user_version == 0`` — a v2 store (the v2 engine never sets the pragma; all
  three committed v2 fixtures are 0), or a store that does not exist yet, which
  the v2 engine will create. Either way: ``MemoryEngine``.
* ``1 <= user_version <= LATEST`` — a v3 store. The facade's ``migrate()`` is
  then a no-op, because the store is already current.
* ``user_version > LATEST`` — newer than this build. Refused, as ``migrate()``
  refuses it, rather than half-served by an engine that does not know the schema.
* a versioned store that has no ``memories`` table is not one of ours. Refused,
  so we never run our migrations against a database from somewhere else.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, Union

from ..store.migrations import LATEST

__all__ = ["StoreVersionError", "open_engine", "store_kind"]

V2 = "v2"
V3 = "v3"


class StoreVersionError(RuntimeError):
    """The store cannot be served by this build — too new, or not ours."""


def store_kind(db_path: Union[Path, str]) -> str:
    """Return :data:`V2` or :data:`V3` for the store at ``db_path``.

    A path that does not exist yet is :data:`V2`: the v2 engine creates it, which
    is what happened before this module existed, so a fresh install is unchanged.
    Raises :class:`StoreVersionError` for anything this build must not open.
    """
    path = Path(db_path)
    if not path.is_file():
        return V2

    version, tables = _peek(path)
    if version > LATEST:
        raise StoreVersionError(
            f"{path} has schema user_version={version}, newer than this build "
            f"(latest={LATEST}); refusing to open it"
        )
    if version == 0:
        return V2
    if "memories" not in tables:
        raise StoreVersionError(
            f"{path} reports user_version={version} but has no v3 `memories` table; "
            "it is not an EntropicMem v3 store"
        )
    return V3


def _peek(path: Path) -> tuple[int, set[str]]:
    """Read the version and table names without opening the file for writing."""
    # as_uri() rather than an f-string: a Windows path has backslashes, which are
    # not valid in a file: URI (invariant 10).
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    except sqlite3.DatabaseError as exc:
        raise StoreVersionError(f"{path} is not a readable SQLite database: {exc}") from exc
    finally:
        conn.close()
    return version, tables


def open_engine(
    db_path: Union[Path, str],
    *,
    profile_id: Optional[str] = None,
    hermes_home: Optional[Path] = None,
    pii_locales: Optional[list] = None,
    scope_user: str = "",
    scope_chat: str = "",
    is_owner: bool = False,
):
    """Open the engine the store's schema calls for.

    Takes both engines' arguments and routes them, so the caller does not have to
    know which engine it will get. ``hermes_home`` reaches the v2 engine only (the
    facade derives its paths from the store); the PII locale packs reach both, so
    a v3 store keeps the locale-aware redaction a v2 store had.

    ``profile_id=None`` means **"let the engine decide"**, which is not the same
    as ``"default"``: ``MemoryEngine.profile_id()`` resolves
    ``explicit > hermes_home basename > 'default'``, so passing ``"default"``
    would override the home-derived slug a v2 store has always been stamped with.
    The facade needs a concrete profile and coerces to ``"default"`` itself.

    Both imports are deferred. The v2 one especially: at 3.0
    ``memory_engine.py`` becomes a shim over this facade, so importing it at
    module level would be a cycle.
    """
    if store_kind(db_path) == V3:
        from .engine import V3Engine

        return V3Engine(
            db_path,
            profile_id=profile_id or "default",
            scope_user=scope_user,
            scope_chat=scope_chat,
            is_owner=is_owner,
            pii_locales=tuple(pii_locales or ()),
        )

    from memory_engine import MemoryEngine

    return MemoryEngine(
        db_path,
        profile_id=profile_id,
        hermes_home=hermes_home,
        pii_locales=pii_locales or [],
    )
