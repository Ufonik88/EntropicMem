"""An index on ``embeddings(model)`` — EM-303's vector cache looks rows up by it.

The cache fingerprints ``(count, max rowid)`` for ``owner_type='memory' AND
model=?`` on every search, and loads the in-scope matrix once per snapshot.
Without an index both are full scans of the table; with ``(owner_type, model)``
they are index lookups, which is what keeps the per-query overhead off the
50k-vector p95 path (the card's AC: < 25 ms).

No data moves; this is a pure index addition, so it is safe on any store.
"""

from __future__ import annotations

import sqlite3

VERSION = 5
NAME = "embeddings_model_index"


def up(conn: sqlite3.Connection) -> None:
    """Index the columns the cache and the vector loader filter on."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_embeddings_owner_model"
        " ON embeddings(owner_type, model)"
    )
