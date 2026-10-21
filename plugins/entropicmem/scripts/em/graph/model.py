"""The graph's model layer: nodes, edges, palettes and community detection.

EM-605 lifted this out of the ``graph_export.py`` monolith. Nothing here writes
a file, opens a socket or knows about HTML: given a `VaultIndex` and the filter
arguments it returns the payload the renderers serialise. That is what makes the
same model reusable for the JSON, DOT, Canvas and HTML renderers, and what the
graph server's refresh path shares.

Stdlib only.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from em.clock import parse_iso, to_iso
from em_internal.index import VaultIndex
from em_internal.policy import normalize_sensitivity, redact_for_prefetch

# ── per-domain color palette (brand-inspired, colorblind-safe) ─────────────

DOMAIN_PALETTE = {
    "Infrastructure": "#1DCF8E",
    "Acme Corp": "#5AE4AA",
    "Content-Growth": "#00AD74",
    "Finance": "#FFB800",
    "Workflows": "#7C4DFF",
    "People": "#FF6B6B",
    "Knowledge": "#4FC3F7",
    "Products-Research": "#FF9800",
    "Projects": "#9CCC65",
}

DEFAULT_COLOR = "#888888"

# ── node type → shape mapping ──────────────────────────────────────────────

TYPE_SHAPES = {
    "permanent": "circle",
    "literature": "square",
    "moc": "diamond",
    "index": "triangle",
    "log": "triangle",
}


def get_color(domain: str) -> str:
    return DOMAIN_PALETTE.get(domain, DEFAULT_COLOR)


def get_shape(note_type: str) -> str:
    return TYPE_SHAPES.get(note_type, "circle")


# ── entity kind → color, relation predicate → color (EM-605 slice 2.1) ────

ENTITY_PALETTE = {
    "person": "#FF6B6B",
    "org": "#4FC3F7",
    "organization": "#4FC3F7",
    "organisation": "#4FC3F7",
    "company": "#4FC3F7",
    "product": "#FF9800",
    "project": "#9CCC65",
    "place": "#FFB800",
    "event": "#7C4DFF",
    "thing": "#1DCF8E",
}

ENTITY_DEFAULT_COLOR = "#B0B0B8"

#: Free-form predicates get a stable colour from this palette: the digest of
#: the predicate picks one, so "works_at" is the same colour in every export,
#: on every machine, without a hard-coded vocabulary that drifts from the
#: extractor. Python's ``hash()`` is deliberately not used (it is salted).
RELATION_PALETTE = (
    "#8AB4F8",
    "#F28B82",
    "#81C995",
    "#FDD663",
    "#C58AF9",
    "#78D9EC",
    "#FF8BCB",
    "#A8D08D",
)


def get_entity_color(kind: str) -> str:
    return ENTITY_PALETTE.get(str(kind or "").strip().lower(), ENTITY_DEFAULT_COLOR)


def get_relation_color(predicate: str) -> str:
    key = str(predicate or "").strip().lower()
    if not key:
        return ENTITY_DEFAULT_COLOR
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return RELATION_PALETTE[digest[0] % len(RELATION_PALETTE)]


# ─ community palette + detection (structure layer, stdlib) ───────────────
# Okabe-Ito colorblind-safe core set plus accessible extras that read on the
# dark galaxy theme. Deterministic per community id (indexed, cycles when the
# number of communities exceeds the palette).

COMMUNITY_PALETTE = [
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # bluish green
    "#F0E442",  # yellow
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#CC79A7",  # reddish purple
    "#5AE4AA",  # accent green
    "#FF6B6B",  # soft red
    "#9CCC65",  # light green
    "#7C4DFF",  # violet
]


def get_community_color(community_id: int) -> str:
    return COMMUNITY_PALETTE[community_id % len(COMMUNITY_PALETTE)]


def detect_communities(edges, max_iter: int = 30) -> dict:
    """Label propagation over an undirected edge set. Stdlib-only.

    Deterministic by construction: nodes are processed in sorted order, ties
    between candidate labels resolve to the smallest label, and final ids are
    renumbered by (size desc, smallest member). Identical graph state always
    produces identical ids, so community colors cannot flicker between
    rebuilds.

    Args:
        edges: iterable of (source_id, target_id) pairs.
        max_iter: sweep cap; label propagation converges well before this on
            vault-scale graphs.

    Returns:
        {node_id: community_id} for nodes participating in at least one edge.
        Isolated nodes are absent (and export as community=null).
    """
    adjacency: dict = {}
    for source, target in edges:
        if source == target:
            continue
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    if not adjacency:
        return {}

    labels = {node: node for node in adjacency}
    for _ in range(max_iter):
        changed = False
        for node in sorted(adjacency):
            neighbors = adjacency[node]
            if not neighbors:
                continue
            counts: dict = {}
            for neighbor in neighbors:
                label = labels[neighbor]
                counts[label] = counts.get(label, 0) + 1
            best = min(counts, key=lambda label: (-counts[label], label))
            if labels[node] != best:
                labels[node] = best
                changed = True
        if not changed:
            break

    groups: dict = {}
    for node, label in labels.items():
        groups.setdefault(label, []).append(node)
    ordered = sorted(groups.values(), key=lambda members: (-len(members), min(members)))
    community_of: dict = {}
    for community_id, members in enumerate(ordered):
        for node in members:
            community_of[node] = community_id
    return community_of


def body_coverage(nodes: list) -> dict:
    """Return body coverage stats for a graph node list.

    Used by the graph server, refresh wrapper, and health check so empty
    modals can never go silent again. Entity nodes (``kind == "entity"``) have
    no body plane, so they are not in the denominator — otherwise adding an
    entity subgraph to a body export would trip the empty-modal gate.
    """
    notes = [n for n in (nodes or []) if n.get("kind") != "entity"]
    total = len(notes)
    with_body = 0
    for n in notes:
        if (n.get("full_body") or n.get("body_preview") or "").strip():
            with_body += 1
    empty = total - with_body
    pct = (100.0 * with_body / total) if total else 100.0
    return {
        "total": total,
        "with_body": with_body,
        "empty": empty,
        "coverage_pct": round(pct, 1),
        "ok": total == 0 or empty == 0,
    }


def assert_bodies_present(payload: dict, *, context: str = "graph export") -> dict:
    """Raise RuntimeError if bodies were requested but the export is body-less.

    The failure mode we hit twice: include_bodies claimed True (or the local
    viewer expects bodies) but every node lacks full_body/body_preview, so
    every modal shows "No content available". A few genuinely empty notes
    are fine; a near-total miss is not.
    """
    nodes = payload.get("nodes") or []
    stats = body_coverage(nodes)
    meta = payload.get("meta") or {}
    if meta.get("include_bodies") is False:
        return stats  # lean export is intentional
    total = stats["total"]
    if total == 0:
        return stats
    # Hard fail: zero bodies when nodes exist
    if stats["with_body"] == 0:
        raise RuntimeError(
            f"{context}: 0/{total} nodes have body content "
            f"(coverage {stats['coverage_pct']}%). "
            "Refusing a body-less graph export — this is the empty-modal bug."
        )
    # Soft fail: large export with most bodies missing (index/FTS broken)
    if total >= 10 and stats["coverage_pct"] < 90.0:
        raise RuntimeError(
            f"{context}: only {stats['with_body']}/{total} nodes have bodies "
            f"({stats['coverage_pct']}% < 90%). "
            "Index/FTS likely stale — rebuild before accepting the export."
        )
    return stats


# ── vault path safety ───────────────────────────────────────────────────────

def resolve_note_path(vault_root: Path, rel_path) -> Path:
    """Resolve a DB-supplied note path strictly inside the vault root.

    notes_meta.path rows feed vault reads here (body fallback) and in the
    graph server; a poisoned row must never turn those reads into arbitrary
    file access. Absolute paths and any dot-dot segment are rejected outright,
    and the resolved result must still land under vault_root (symlink escapes
    resolve() away).

    Args:
        vault_root: vault directory the note must live under.
        rel_path: DB-supplied relative path (str or Path).

    Returns:
        The resolved absolute path to the note inside vault_root.

    Raises:
        ValueError: when the path is empty, absolute, contains '..', or
            resolves outside vault_root.
    """
    raw = str(rel_path or "").strip()
    if not raw:
        raise ValueError("empty note path")
    candidate = Path(raw)
    if candidate.is_absolute() or candidate.drive or any(p == ".." for p in candidate.parts):
        raise ValueError(f"note path escapes vault root: {raw!r}")
    root = Path(vault_root).expanduser().resolve()
    full = (root / candidate).resolve()
    if not full.is_relative_to(root):
        raise ValueError(f"note path escapes vault root: {raw!r}")
    return full


# ── the entity subgraph (EM-605 slice 2.1) ──────────────────────────────────

@dataclass(frozen=True)
class GraphEntity:
    """One entity from memory.db, already scoped and selected."""

    entity_id: str
    name: str
    kind: str = "thing"
    aliases: tuple = ()


@dataclass(frozen=True)
class GraphRelation:
    """One relation between two entities in the same scope.

    ``object_id`` is the other entity; literal relations never reach the model
    (they have no node to point at) and are counted by the loader instead.
    ``valid_from`` / ``valid_to`` are nullable: either end can be open. The
    model turns them into ``time_span`` ranks over the payload's time axis.

    ``superseded`` is the loader's reading of the store (EM-605 slice 2.4): the
    claim behind this relation was replaced, so the edge is drawn dashed. It is
    decided from ``memories.status = 'superseded'`` — never from ``valid_to``
    (a closed claim merely ended) and never from ``superseded_by`` (history
    survives a restore) — and it is a model field so the viewer has nothing to
    infer.
    """

    subject_id: str
    predicate: str
    object_id: str
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    confidence: float = 0.7
    superseded: bool = False


@dataclass(frozen=True)
class EntityGraph:
    """The second store's contribution, loaded before the payload is built.

    ``available`` is False when memory.db is missing or is not a v3 store;
    ``reason`` says which, in a path-free phrase (an export carries this block,
    and a home directory is not graph data).

    ``scope`` records which filter produced this graph — ``owner`` (the
    default) or ``all``. ``hidden_entities`` and ``hidden_relations`` are the
    number of rows that filter removed; they are counts, never rows, so the
    block cannot leak what it excluded. ``dropped_relations`` stays separate:
    it counts shape and cap losses, not scope losses.
    """

    entities: tuple = ()
    relations: tuple = ()
    scope_profile: str = ""
    scope: str = "owner"
    available: bool = True
    reason: str = ""
    truncated: bool = False
    dropped_relations: int = 0
    literal_relations: int = 0
    hidden_entities: int = 0
    hidden_relations: int = 0


def _normalise_time_bound(value) -> Optional[str]:
    """A relation bound as a canonical UTC instant, or a sentinel.

    ``None`` (or empty) means the bound is open. An unparseable value returns
    ``""``: the edge stays visible in every window rather than crashing an
    export or silently acquiring a made-up date. The count, not the value, is
    reported.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return to_iso(parse_iso(text))
    except (TypeError, ValueError):
        return ""


def _time_axis(relations) -> tuple:
    """Build the inclusive rank axis and per-edge spans (EM-605 slice 2.3).

    The stops are the sorted, normalised instants named by the surviving
    relation edges. A null ``valid_from`` ranks at ``-1`` and a null
    ``valid_to`` at ``len(stops)``, so the viewer's integer window predicate
    means the same thing as the timestamp predicate:

        ``valid_from <= t1 and (valid_to is null or valid_to >= t0)``

    Equal boundaries share one stop, which is what makes a point interval a
    point. An edge with both bounds open has no span and is timeless; an edge
    with one unparseable bound has no span either and is counted.
    """
    normalized = []
    stops = set()
    unparsed = 0
    for relation in relations:
        start = _normalise_time_bound(relation.valid_from)
        end = _normalise_time_bound(relation.valid_to)
        if start == "" or end == "":
            unparsed += 1
            normalized.append(None)
            continue
        normalized.append((start, end))
        if start is not None:
            stops.add(start)
        if end is not None:
            stops.add(end)

    stops = sorted(stops)
    rank = {instant: index for index, instant in enumerate(stops)}
    spans = []
    for item in normalized:
        if item is None:
            spans.append(None)
            continue
        start, end = item
        if start is None and end is None:
            spans.append(None)
            continue
        spans.append([
            -1 if start is None else rank[start],
            len(stops) if end is None else rank[end],
        ])

    block = {
        "available": bool(stops),
        "min": stops[0] if stops else "",
        "max": stops[-1] if stops else "",
        "stops": stops,
        "unparsed_relations": unparsed,
    }
    return spans, block


def _entity_graph_parts(entity_graph: EntityGraph, note_ids: set) -> tuple:
    """Turn one EntityGraph into nodes, edges and its meta block.

    Invariants, all tested:

    * an entity node id is ``entity:<id>``, so it can never equal a note id —
      the two stores have unrelated id spaces and no join is invented;
    * an edge exists only when both endpoint nodes are present in the export;
      every other relation is counted in ``dropped_relations``, never drawn;
    * an entity with no surviving edge is not drawn (an isolated dot is noise);
    * the scope's losses are counted in ``hidden_entities`` /
      ``hidden_relations``, and the block carries no hidden name, id, alias,
      predicate or endpoint — only the counts and the scope that produced them;
    * time losses are not scope losses: the payload carries every surviving
      edge with an inclusive ``time_span`` rank, and the viewer counts what the
      selected window hides (``timeHidden``), never adding it to
      ``hidden_relations``. Entities are timeless and stay;
    * a superseded claim is still drawn (dashed, never hidden): the edge carries
      the loader's ``superseded`` flag and ``superseded_relations`` counts the
      drawn ones, on its own axis — not ``hidden_relations`` (scope) and not
      ``time`` (interval).
    """
    by_id = {e.entity_id: e for e in entity_graph.entities}
    kept = []
    dropped = entity_graph.dropped_relations
    touched = set()
    for r in entity_graph.relations:
        if r.subject_id in by_id and r.object_id in by_id:
            kept.append(r)
            touched.add(r.subject_id)
            touched.add(r.object_id)
        else:
            dropped += 1

    degree = {}
    for r in kept:
        degree[r.subject_id] = degree.get(r.subject_id, 0) + 1
        degree[r.object_id] = degree.get(r.object_id, 0) + 1

    nodes = []
    for e in entity_graph.entities:
        if e.entity_id not in touched:
            continue
        node_id = f"entity:{e.entity_id}"
        if node_id in note_ids:  # cannot happen with the prefix; fail closed
            dropped += degree.get(e.entity_id, 0)
            continue
        nodes.append({
            "id": node_id,
            "kind": "entity",
            "entity_id": e.entity_id,
            "entity_kind": e.kind,
            "title": e.name,
            "type": "entity",
            "domain": "",
            "importance": 0.5,
            "tags": [],
            "aliases": list(e.aliases),
            "color": get_entity_color(e.kind),
            "shape": "circle",
            "community": None,
            "community_color": DEFAULT_COLOR,
            "degree": degree.get(e.entity_id, 0),
        })

    node_ids = {n["id"] for n in nodes}
    spans, time_block = _time_axis(kept)
    edges = []
    superseded_relations = 0
    for r, span in zip(kept, spans):
        source = f"entity:{r.subject_id}"
        target = f"entity:{r.object_id}"
        if source not in node_ids or target not in node_ids:
            dropped += 1
            continue
        if r.superseded:
            superseded_relations += 1
        edges.append({
            "source": source,
            "target": target,
            "weight": 1.0,
            "kind": "relation",
            "predicate": r.predicate,
            "color": get_relation_color(r.predicate),
            "valid_from": r.valid_from,
            "valid_to": r.valid_to,
            "time_span": span,
            "confidence": r.confidence,
            "superseded": r.superseded,
        })

    block = {
        "available": entity_graph.available,
        "reason": entity_graph.reason,
        "scope_profile": entity_graph.scope_profile,
        "scope": entity_graph.scope,
        "entity_count": len(nodes),
        "relation_edge_count": len(edges),
        "superseded_relations": superseded_relations,
        "hidden_entities": entity_graph.hidden_entities,
        "hidden_relations": entity_graph.hidden_relations,
        "truncated": entity_graph.truncated,
        "dropped_relations": dropped,
        "literal_relations": entity_graph.literal_relations,
        "time": time_block,
    }
    return nodes, edges, block


# ── the payload ─────────────────────────────────────────────────────────────

def build_graph_payload(
    index: VaultIndex,
    domain: Optional[str] = None,
    min_importance: float = 0.0,
    max_nodes: int = 500,
    include_bodies: bool = False,
    *,
    context: Optional[str] = None,
    entity_graph: Optional[EntityGraph] = None,
    redact_sensitive: bool = False,
) -> dict:
    """Build the nodes + edges + meta payload the renderers serialise.

    Note bodies (body_preview/full_body) are only embedded when
    include_bodies=True, so a shared/exported graph.json never leaks vault
    content by default.

    ``redact_sensitive`` (EM-606) applies the policy's own tier rule to those
    bodies: a note whose domain tier is ``sensitive`` or ``secret``
    (``em_internal.policy.normalize_sensitivity``) is embedded as the redacted
    summary ``redact_for_prefetch`` produces, never as the full body. The graph
    server passes True — its payload lands in a browser over HTTP — while the
    CLI keeps the default, because an export written to the owner's own disk is
    the owner's artifact and ``--include-bodies`` is already its opt-in.

    ``entity_graph`` (EM-605 slice 2.1) adds the second store's entities and
    relations. It is None by default, in which case the payload is exactly the
    note graph it always was. When supplied — even empty or unavailable — the
    payload's ``meta.entities`` block records what was loaded and what could not
    become an edge. The two stores share no ids, so entity nodes are prefixed
    and no note↔entity edge is ever inferred.

    Args:
        index: the vault index the graph is read from.
        domain: optional domain filter.
        min_importance: drop nodes below this importance.
        max_nodes: node cap; when hit, nodes are re-ranked by (degree,
            importance) so the kept set looks connected rather than an
            importance-sorted dot field.
        include_bodies: embed bodies (off by default; security).
        context: names the caller in the body-gate error message (the export
            path, historically, so the message still points at the file).

    Returns:
        The payload dict, including `meta` with counts and a `body_coverage`
        block. Raises RuntimeError via `assert_bodies_present` when bodies were
        requested but the export came back empty.
    """
    # Full in-scope edge set. Single fetch (previously fetched twice with the
    # same args): drives degree, community detection, and the cap re-rank.
    all_edges = index.get_graph_edges(domain=domain, min_weight=1)
    degree_of: dict = {}
    for e in all_edges:
        degree_of[e.source_id] = degree_of.get(e.source_id, 0) + 1
        degree_of[e.target_id] = degree_of.get(e.target_id, 0) + 1
    community_of = detect_communities((e.source_id, e.target_id) for e in all_edges)

    nodes = index.get_graph_nodes(
        domain=domain,
        min_importance=min_importance,
        max_nodes=max_nodes,
        include_bodies=include_bodies,
    )

    # Build node list with visual properties
    node_list = []
    for n in nodes:
        tags = n.get("tags", "")
        if isinstance(tags, str) and tags:
            tags = [t.strip() for t in tags.split(",")]
        elif not isinstance(tags, list):
            tags = []

        community_id = community_of.get(n["note_id"])
        node_list.append({
            "id": n["note_id"],
            "kind": "note",
            "title": n.get("title", n["note_id"]),
            "type": n.get("note_type", "permanent"),
            "domain": n.get("domain", ""),
            "importance": n.get("importance", 0.3),
            "tags": tags,
            "color": get_color(n.get("domain", "")),
            "shape": get_shape(n.get("note_type", "permanent")),
            "community": community_id,
            "community_color": (
                get_community_color(community_id)
                if community_id is not None else DEFAULT_COLOR
            ),
            "degree": degree_of.get(n["note_id"], 0),
        })
        # Bodies only embedded when explicitly requested (security default: off)
        if include_bodies:
            node_list[-1]["body_preview"] = n.get("body_preview", "")
            node_list[-1]["full_body"] = n.get("full_body", n.get("body_preview", ""))
            # path helps the modal frontmatter; only with bodies (same trust plane)
            if n.get("path"):
                node_list[-1]["path"] = n["path"]
            if redact_sensitive:
                tier = normalize_sensitivity(None, n.get("domain", ""))
                if tier in ("sensitive", "secret"):
                    for key in ("body_preview", "full_body"):
                        if node_list[-1].get(key):
                            node_list[-1][key] = redact_for_prefetch(
                                node_list[-1][key], tier
                            )

    # Build edge list (only edges where both nodes exist in the export set)
    node_ids = {n["id"] for n in node_list}

    # If we hit the max_nodes cap, re-rank to prefer triple-heavy / high-degree
    # nodes so the visible graph looks like a connected web, not an isolated
    # importance-sorted dot field. Edges whose endpoints are both kept stay;
    # nodes that got truncated drop their incident edges.
    if max_nodes and len(node_list) >= max_nodes:
        node_list.sort(key=lambda n: (n.get("degree", 0), n.get("importance", 0.3)), reverse=True)
        node_list = node_list[:max_nodes]
        node_ids = {n["id"] for n in node_list}
    edge_list = []
    for e in all_edges:
        if e.source_id in node_ids and e.target_id in node_ids:
            edge_list.append({
                "source": e.source_id,
                "target": e.target_id,
                "weight": e.weight,
                "kind": e.kind,
            })

    # Note-only statistics are measured before the entity subgraph is added:
    # "domains" and "max_importance" describe notes, and they are what the
    # note filters read. node_count/edge_count stay totals.
    note_count = len(node_list)
    note_domains = list(set(n.get("domain", "") for n in node_list))
    note_max_importance = max(
        (n.get("importance", 0) for n in node_list), default=0
    )

    entity_block = None
    if entity_graph is not None:
        entity_nodes, entity_edges, entity_block = _entity_graph_parts(
            entity_graph, set(node_ids)
        )
        node_list.extend(entity_nodes)
        edge_list.extend(entity_edges)

    payload = {
        "nodes": node_list,
        "edges": edge_list,
        "meta": {
            "generated": "",
            "node_count": len(node_list),
            "note_count": note_count,
            "edge_count": len(edge_list),
            "include_bodies": include_bodies,
            "domains": note_domains,
            "community_count": len(set(community_of.values())),
            "max_importance": note_max_importance,
            "filters": {
                "domain": domain,
                "min_importance": min_importance,
                "max_nodes": max_nodes,
            },
        },
    }
    if entity_block is not None:
        payload["meta"]["entities"] = entity_block

    payload["meta"]["generated"] = datetime.now(timezone.utc).isoformat()
    payload["meta"]["body_coverage"] = body_coverage(node_list)

    # Hard gate: never write a "bodies included" export that is actually empty.
    # This is the permanent fix for empty graph modals (hit twice before).
    if include_bodies:
        assert_bodies_present(payload, context=context or "build_graph_payload")

    return payload
