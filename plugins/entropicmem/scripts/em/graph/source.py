"""Read-only loader for the graph's second store: ``memory.db`` (EM-605 2.1).

Notes live in ``index.db`` and are keyed by their vault-relative path. Entities
and relations live in ``memory.db``, keyed by ``ent_…`` and ``rel_…`` ids. The
two stores share no id space and nothing maps a note to an entity:
``memory_entities`` links *memories* (``mem_…``), not notes. This loader
therefore loads a self-contained entity subgraph; the model prefixes its node
ids with ``entity:`` and never infers a note↔entity edge. A relation whose
endpoint is not one of the selected entities is counted, not drawn.

The database is opened ``mode=ro``: a read can never create or migrate the
file, and a missing/foreign database is an empty graph with a path-free
``reason`` rather than an exception. ``scope_profile`` is required — a caller
must name the profile it wants, so "every profile" cannot arrive by omission.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

from em.graph.model import EntityGraph, GraphEntity, GraphRelation

#: The profile a local owner session writes under. Mirrors
#: ``MemoryEngine(profile_id="default")`` and the provider's
#: ``self._profile_id or "default"``. It is a default for callers, never for
#: the loader: passing it explicitly is what keeps the scope a decision.
DEFAULT_PROFILE = "default"


def load_entity_graph(
    memory_db: Union[str, Path],
    *,
    scope_profile: str,
    max_entities: int = 200,
) -> EntityGraph:
    """Load one profile's entities and open relations for the graph.

    Only entities participating in at least one relation are candidates: an
    entity node with no edge is an isolated dot, so it is not drawn. Candidates
    are ranked by relation degree, then name, then id, and the top
    ``max_entities`` are kept; ``truncated`` says whether the cap bit.

    Args:
        memory_db: path to ``memory.db``. Read-only; never created.
        scope_profile: the one profile to read. Required, non-empty.
        max_entities: entity cap. Relations to entities beyond it are counted
            in ``dropped_relations`` and emit no edge.

    Returns:
        An :class:`EntityGraph`. ``available`` is False (with ``reason``) when
        the file is missing, unreadable, or not a v3 store (no ``entities`` /
        ``relations`` tables).

    Raises:
        ValueError: when ``scope_profile`` is empty.
    """
    profile = str(scope_profile or "").strip()
    if not profile:
        raise ValueError("scope_profile is required: refusing to load every profile")
    limit = max(0, int(max_entities))

    path = Path(memory_db).expanduser()
    if not path.is_file():
        return EntityGraph(
            scope_profile=profile, available=False, reason="memory.db not found"
        )

    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return EntityGraph(
            scope_profile=profile, available=False, reason="memory.db unreadable"
        )
    try:
        conn.row_factory = sqlite3.Row
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        except sqlite3.DatabaseError:
            return EntityGraph(
                scope_profile=profile, available=False, reason="memory.db unreadable"
            )
        if not {"entities", "relations"} <= tables:
            return EntityGraph(
                scope_profile=profile, available=False, reason="not a v3 memory.db"
            )

        entities = [
            dict(row)
            for row in conn.execute(
                "SELECT id, name, kind FROM entities WHERE scope_profile=?"
                " ORDER BY name, id",
                (profile,),
            )
        ]
        relations = [
            dict(row)
            for row in conn.execute(
                "SELECT id, subject_id, predicate, object_id, valid_from, valid_to,"
                " confidence FROM relations WHERE scope_profile=? AND valid_to IS NULL"
                " ORDER BY subject_id, predicate, object_id, id",
                (profile,),
            )
        ]
        aliases: dict = {}
        for row in conn.execute(
            "SELECT entity_id, alias_norm FROM entity_aliases ORDER BY alias_norm"
        ):
            aliases.setdefault(row["entity_id"], []).append(row["alias_norm"])
    finally:
        conn.close()

    # Degree is counted over relations whose two endpoints are both entities of
    # this profile. A relation with a literal object has no node to point at; a
    # relation whose endpoint is absent or in another profile cannot be drawn.
    entity_ids = {e["id"] for e in entities}
    degree = {entity_id: 0 for entity_id in entity_ids}
    eligible = []
    dropped = 0
    literals = 0
    for r in relations:
        if not r["object_id"]:
            literals += 1
            continue
        if r["subject_id"] in entity_ids and r["object_id"] in entity_ids:
            eligible.append(r)
            degree[r["subject_id"]] += 1
            degree[r["object_id"]] += 1
        else:
            dropped += 1

    ranked = sorted(
        (e for e in entities if degree[e["id"]] > 0),
        key=lambda e: (-degree[e["id"]], e["name"], e["id"]),
    )
    truncated = len(ranked) > limit
    selected = ranked[:limit]
    selected_ids = {e["id"] for e in selected}
    kept = [
        r
        for r in eligible
        if r["subject_id"] in selected_ids and r["object_id"] in selected_ids
    ]
    dropped += len(eligible) - len(kept)

    return EntityGraph(
        entities=tuple(
            GraphEntity(
                entity_id=e["id"],
                name=e["name"],
                kind=e["kind"] or "thing",
                aliases=tuple(aliases.get(e["id"], ())),
            )
            for e in selected
        ),
        relations=tuple(
            GraphRelation(
                subject_id=r["subject_id"],
                predicate=r["predicate"],
                object_id=r["object_id"],
                valid_from=r["valid_from"],
                valid_to=r["valid_to"],
                confidence=(
                    float(r["confidence"])
                    if r["confidence"] is not None
                    else 0.7
                ),
            )
            for r in kept
        ),
        scope_profile=profile,
        available=True,
        truncated=truncated,
        dropped_relations=dropped,
        literal_relations=literals,
    )
