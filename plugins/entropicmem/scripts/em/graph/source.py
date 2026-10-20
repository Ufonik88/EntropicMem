"""Read-only loader for the graph's second store: ``memory.db`` (EM-605 2.1).

Notes live in ``index.db`` and are keyed by their vault-relative path. Entities
and relations live in ``memory.db``, keyed by ``ent_…`` and ``rel_…`` ids. The
two stores share no id space and nothing maps a note to an entity:
``memory_entities`` links *memories* (``mem_…``), not notes. This loader
therefore loads a self-contained entity subgraph; the model prefixes its node
ids with ``entity:`` and never infers a note↔entity edge. A relation whose
endpoint is not one of the selected entities is counted, not drawn.

Relations are loaded **whether open or closed** (EM-605 slice 2.3): a closed
relation was true for a bounded period and belongs on the timeline. Both
``valid_from`` and ``valid_to`` are nullable; the graph model turns the pair
into an inclusive rank span over a sorted axis of the surviving edges, and the
viewer applies the selected window to those ranks. The loader itself does not
filter by time: it loads the whole scoped subgraph, so moving the slider never
needs another database read.

The database is opened ``mode=ro``: a read can never create or migrate the
file, and a missing/foreign database is an empty graph with a path-free
``reason`` rather than an exception. ``scope_profile`` is required — a caller
must name the profile it wants, so "every profile" cannot arrive by omission.

The second required decision is the **scope** (EM-605 slice 2.2). Entities and
relations carry no user column; their user attribution comes from the memories
behind them (``memory_entities`` and ``relations.memory_id``). The default,
``scope="owner"``, keeps only data the v3 owner context can call its own: an
entity needs at least one link to a profile-wide memory (``scope_user=''``), or
no memory link at all (an entity row is itself profile-wide, and an unattributed
manual entity is owner data); a relation needs an empty ``memory_id`` with two
visible endpoints, or a ``memory_id`` that resolves to a profile-wide memory in
the same profile. ``scope="all"`` is the explicit opt-in that turns attribution
off. Hidden rows are counted, never named, so ``meta.entities`` cannot leak the
data it filtered.
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

#: The two scope modes. ``owner`` keeps profile-wide data (the v3 owner
#: context); ``all`` is the explicit opt-in that also includes rows attributed
#: to a user scope. There is no third mode: a caller that needs a specific
#: user's view must add one deliberately, not get it by a typo.
SCOPE_OWNER = "owner"
SCOPE_ALL = "all"
SCOPES = (SCOPE_OWNER, SCOPE_ALL)


def load_entity_graph(
    memory_db: Union[str, Path],
    *,
    scope_profile: str,
    scope: str = SCOPE_OWNER,
    max_entities: int = 200,
) -> EntityGraph:
    """Load one profile's entities and relations for the graph.

    Only entities participating in at least one relation are candidates: an
    entity node with no edge is an isolated dot, so it is not drawn. Candidates
    are ranked by relation degree, then name, then id, and the top
    ``max_entities`` are kept; ``truncated`` says whether the cap bit.

    ``scope="owner"`` (the default) filters through memory attribution before
    ranking: a hidden entity neither consumes the cap nor lends degree to a
    visible one. ``scope="all"`` skips the filter. Hidden rows are counted in
    ``hidden_entities`` / ``hidden_relations``; shape and cap losses stay in
    ``dropped_relations``.

    Args:
        memory_db: path to ``memory.db``. Read-only; never created.
        scope_profile: the one profile to read. Required, non-empty.
        scope: ``owner`` (profile-wide rows only) or ``all`` (every user).
        max_entities: entity cap. Relations to entities beyond it are counted
            in ``dropped_relations`` and emit no edge.

    Returns:
        An :class:`EntityGraph`. ``available`` is False (with ``reason``) when
        the file is missing, unreadable, or not a v3 store (no ``entities`` /
        ``relations`` / ``memory_entities`` / ``memories`` tables).

    Raises:
        ValueError: when ``scope_profile`` is empty or ``scope`` is unknown.
    """
    profile = str(scope_profile or "").strip()
    if not profile:
        raise ValueError("scope_profile is required: refusing to load every profile")
    scope_mode = str(scope or "").strip().lower()
    if scope_mode not in SCOPES:
        raise ValueError(
            f"scope must be one of {SCOPES!r}: refusing to guess {scope!r}"
        )
    limit = max(0, int(max_entities))

    path = Path(memory_db).expanduser()
    if not path.is_file():
        return EntityGraph(
            scope_profile=profile,
            scope=scope_mode,
            available=False,
            reason="memory.db not found",
        )

    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return EntityGraph(
            scope_profile=profile,
            scope=scope_mode,
            available=False,
            reason="memory.db unreadable",
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
                scope_profile=profile,
                scope=scope_mode,
                available=False,
                reason="memory.db unreadable",
            )
        if not {"entities", "relations", "memory_entities", "memories"} <= tables:
            return EntityGraph(
                scope_profile=profile,
                scope=scope_mode,
                available=False,
                reason="not a v3 memory.db",
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
                "SELECT r.id, r.subject_id, r.predicate, r.object_id, r.memory_id,"
                " r.valid_from, r.valid_to, r.confidence,"
                " m.scope_profile AS memory_profile, m.scope_user AS memory_user"
                " FROM relations r LEFT JOIN memories m ON m.id = r.memory_id"
                " WHERE r.scope_profile=?"
                " ORDER BY r.subject_id, r.predicate, r.object_id, r.id",
                (profile,),
            )
        ]
        # Entity attribution: the links from memories. A dangling memory link
        # counts as a link (fail closed) but never as an owner link. Rows from
        # another profile cannot make this profile's entity owner data.
        attribution: dict = {}
        if scope_mode == SCOPE_OWNER:
            for row in conn.execute(
                "SELECT me.entity_id, COUNT(*) AS links,"
                " SUM(CASE WHEN m.scope_profile=? AND m.scope_user=''"
                " THEN 1 ELSE 0 END) AS owner_links"
                " FROM memory_entities me"
                " JOIN entities e ON e.id=me.entity_id AND e.scope_profile=?"
                " LEFT JOIN memories m ON m.id=me.memory_id"
                " GROUP BY me.entity_id",
                (profile, profile),
            ):
                attribution[row["entity_id"]] = (
                    int(row["owner_links"] or 0),
                    int(row["links"] or 0),
                )
        aliases: dict = {}
        for row in conn.execute(
            "SELECT a.entity_id, a.alias_norm FROM entity_aliases a"
            " JOIN entities e ON e.id=a.entity_id AND e.scope_profile=?"
            " ORDER BY a.alias_norm",
            (profile,),
        ):
            aliases.setdefault(row["entity_id"], []).append(row["alias_norm"])
    finally:
        conn.close()

    # Scope attribution (EM-605 2.2). An entity row has no user column, so its
    # owner is the memory behind it. No link at all is profile data; links that
    # all point at user-scoped memories hide it. A relation is attributed by
    # its source memory; with none, its two endpoints decide.
    hidden_ids: set = set()
    if scope_mode == SCOPE_OWNER:
        visible_entities = []
        for e in entities:
            owner_links, links = attribution.get(e["id"], (0, 0))
            if links == 0 or owner_links > 0:
                visible_entities.append(e)
            else:
                hidden_ids.add(e["id"])
    else:
        visible_entities = list(entities)
    hidden_entities = len(hidden_ids)
    visible_ids = {e["id"] for e in visible_entities}

    # Degree is counted over relations whose two endpoints are both visible
    # entities of this profile. A relation with a literal object has no node to
    # point at; a relation whose endpoint is absent or in another profile
    # cannot be drawn. A hidden endpoint, or a memory attributed to another
    # user, is a scope loss and is counted separately.
    degree = {entity_id: 0 for entity_id in visible_ids}
    eligible = []
    dropped = 0
    literals = 0
    hidden_relations = 0
    for r in relations:
        if scope_mode == SCOPE_OWNER and r["memory_id"]:
            # Fail closed on a missing or cross-profile memory: provenance that
            # cannot be resolved is not owner data.
            if r["memory_profile"] != profile or r["memory_user"] != "":
                hidden_relations += 1
                continue
        if not r["object_id"]:
            literals += 1
            continue
        if r["subject_id"] in visible_ids and r["object_id"] in visible_ids:
            eligible.append(r)
            degree[r["subject_id"]] += 1
            degree[r["object_id"]] += 1
        elif r["subject_id"] in hidden_ids or r["object_id"] in hidden_ids:
            hidden_relations += 1
        else:
            dropped += 1

    ranked = sorted(
        (e for e in visible_entities if degree[e["id"]] > 0),
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
        scope=scope_mode,
        available=True,
        truncated=truncated,
        dropped_relations=dropped,
        literal_relations=literals,
        hidden_entities=hidden_entities,
        hidden_relations=hidden_relations,
    )
