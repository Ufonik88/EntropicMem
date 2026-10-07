"""Retrieval vocabulary: an ``fts5vocab`` view over ``memories_fts`` (§3.6).

EM-301 selects query terms by IDF, and IDF needs each term's document
frequency. ``fts5vocab(memories_fts, 'row')`` gives exactly that: one row per
indexed term with ``doc`` (the number of rows the term appears in) and ``cnt``.

**The plan calls this "migration 0003".** That number is already taken by
``0003_audit_append_only``, and a migration's version is its filename, so this
is **0004** — the plan's number is stale, not wrong-headed.

A virtual table stores no data of its own: it reads the FTS index, so nothing
is duplicated and nothing needs a trigger. It must be created after
``memories_fts`` exists (0002), which the version ordering guarantees.
"""

from __future__ import annotations

import sqlite3

VERSION = 4
# Space-free, like every other migration name: the fresh-subprocess test
# reads the applied list from stdout and splits on whitespace.
NAME = "retrieval_vocab_fts5vocab"


def up(conn: sqlite3.Connection) -> None:
    """Create the term-frequency view the analyzer reads."""
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS memories_vocab "
        "USING fts5vocab(memories_fts, 'row')"
    )
