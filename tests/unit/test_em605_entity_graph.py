"""EM-605 slices 2.1–2.3 — entity nodes, typed relation edges and the time axis.

The graph's two stores do not share an id space. ``index.db`` keys notes by
their vault-relative path (``note_id_for_path``); ``memory.db`` keys entities by
``ent_…`` and memories by ``mem_…``, and ``memory_entities`` links *memories*,
not notes. Nothing joins a note to an entity, so the model must not pretend it
does: entity node ids are prefixed ``entity:`` and a note id can never collide
with one, which is what makes an invented note↔entity edge impossible.

What is pinned here:

* one loader reads ``memory.db`` read-only, scoped to one profile (no default —
  a caller must name the profile, so cross-profile data cannot arrive by
  omission), and never creates the file;
* entity nodes carry their kind's colour, relation edges their predicate's;
* the "stores disagree" fixture: an entity whose id looks like a note id stays
  a separate node, and a ``memory_entities`` row pointing at a note id produces
  nothing (the loader does not read that table at all);
* every relation that cannot become an edge — literal object, out-of-profile
  endpoint, or an endpoint trimmed by the entity cap — is counted in
  ``meta.entities`` and emits no edge; a **closed interval is an edge with both
  bounds**, not a loss (slice 2.3);
* the time axis is a server-built set of ranks: null becomes ±∞, equal
  boundaries collapse to one stop, an unparseable bound is counted and left
  visible, and the viewer's window is an inclusive rank range;
* the body gate counts notes only, so entity nodes cannot fail a body export.

Rules: invented data only (Acme / Globex, Alice / Bob Example, example.com).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
CLI = SCRIPTS / "entropicmem.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import graph_assets  # noqa: E402

from em.clock import to_iso, utc_now  # noqa: E402
from em.graph.export import export_html, export_json  # noqa: E402
from em.graph.model import (  # noqa: E402
    EntityGraph,
    GraphEntity,
    GraphRelation,
    build_graph_payload,
    get_entity_color,
    get_relation_color,
)
from em.graph.source import load_entity_graph  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.entities import EntityStore  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402
from em_internal.index import VaultIndex  # noqa: E402
from em_internal.vault import Vault  # noqa: E402

OWNER = Scope(profile="default")


# ── fixtures: one real index.db, one real memory.db ─────────────────────────


def _build_index(tmp_path: Path, titles=("Alpha", "Beta")):
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    vault = Vault(root)
    for title in titles:
        body = "Links: " + " ".join(f"[[{t}]]" for t in titles if t != title)
        vault.write_note("Knowledge", title, body + "\n\nExample body text.", domain="Knowledge")
    index = VaultIndex(tmp_path / "index.db")
    for rel in vault.list_notes():
        index.upsert_note(vault.read_note(rel))
    index._rebuild_edges(vault)
    return index


@pytest.fixture
def index(tmp_path):
    idx = _build_index(tmp_path)
    yield idx
    idx.close()


@pytest.fixture
def memory(tmp_path):
    store = Store(str(tmp_path / "memory.db"))
    with store.writer() as conn:
        migrate(conn)
    yield store
    store.close()


def _seed(
    memory,
    *,
    profile: str = "default",
    names=("Alice Example", "Acme Corp", "Widget"),
):
    """Alice works at Acme; Acme makes Widget. Returns the entity ids."""
    alice_name, acme_name, widget_name = names
    scope = Scope(profile=profile)
    with memory.writer() as conn:
        es = EntityStore(conn)
        alice = es.get_or_create_entity(alice_name, scope=scope, kind="person")
        acme = es.get_or_create_entity(acme_name, scope=scope, kind="org")
        widget = es.get_or_create_entity(widget_name, scope=scope, kind="product")
        works_at = es.add_relation(
            scope=scope, subject_id=alice, predicate="works_at", object_id=acme
        )
        makes = es.add_relation(
            scope=scope, subject_id=acme, predicate="makes", object_id=widget
        )
        es.add_alias(acme, acme_name.split()[0])
    return {
        "alice": alice,
        "acme": acme,
        "widget": widget,
        "works_at": works_at,
        "makes": makes,
    }


def _graph(memory, profile: str = "default", **kw):
    return load_entity_graph(
        Path(memory.path), scope_profile=profile, **kw
    )


def _payload(index, memory, **kw):
    return build_graph_payload(index, entity_graph=_graph(memory, **kw))


def _endpoints_resolve(payload) -> bool:
    ids = {n["id"] for n in payload["nodes"]}
    return all(e["source"] in ids and e["target"] in ids for e in payload["edges"])


def _edge(payload, predicate):
    return next(e for e in payload["edges"] if e.get("predicate") == predicate)


def _visible(span, lo, hi) -> bool:
    """The viewer's inclusive-window predicate, over rank indices."""
    return span[0] <= hi and span[1] >= lo


def _set_interval(memory, relation_id, *, valid_from, valid_to):
    with memory.writer() as conn:
        conn.execute(
            "UPDATE relations SET valid_from=?, valid_to=? WHERE id=?",
            (valid_from, valid_to, relation_id),
        )


# ── the happy path: typed nodes and typed edges ─────────────────────────────


def test_entity_nodes_and_relation_edges_are_typed(index, memory):
    ids = _seed(memory)
    payload = _payload(index, memory)

    nodes = {n["id"]: n for n in payload["nodes"]}
    alice = nodes[f"entity:{ids['alice']}"]
    assert alice["title"] == "Alice Example"
    assert alice["kind"] == "entity"
    assert alice["entity_kind"] == "person"
    assert alice["color"] == get_entity_color("person")
    assert alice["domain"] == ""
    assert nodes[f"entity:{ids['acme']}"]["color"] == get_entity_color("org")

    edges = {(e["source"], e["target"]): e for e in payload["edges"]}
    works = edges[(f"entity:{ids['alice']}", f"entity:{ids['acme']}")]
    assert works["predicate"] == "works_at"
    assert works["kind"] == "relation"
    assert works["color"] == get_relation_color("works_at")
    # one predicate, one colour, in every export — across the whole vocabulary,
    # not one pair (a two-value pin can collide by chance in an 8-slot palette)
    for predicate in ("works_at", "makes", "born_in", "knows"):
        assert get_relation_color(predicate) == get_relation_color(
            f"  {predicate.upper()}  "
        )

    # note nodes are untouched: no prefix, and they declare their own class
    alpha = nodes["Knowledge/Alpha"]
    assert alpha["kind"] == "note"
    assert alpha["color"] != ""
    assert _endpoints_resolve(payload)


def test_aliases_ride_the_entity_node(index, memory):
    ids = _seed(memory)
    payload = _payload(index, memory)
    acme = next(n for n in payload["nodes"] if n["id"] == f"entity:{ids['acme']}")
    assert "Acme" in acme["aliases"]


def test_meta_reports_the_entity_block(index, memory):
    _seed(memory)
    payload = _payload(index, memory)
    block = payload["meta"]["entities"]
    assert block["available"] is True
    assert block["scope_profile"] == "default"
    assert block["entity_count"] == 3
    assert block["relation_edge_count"] == 2
    assert block["truncated"] is False
    assert payload["meta"]["node_count"] == len(payload["nodes"])
    assert payload["meta"]["edge_count"] == len(payload["edges"])


# ── the profile is required, not guessed ────────────────────────────────────


def test_the_loader_reads_one_profile_only(index, memory):
    _seed(memory)
    ids = _seed(
        memory,
        profile="guest",
        names=("Bob Example", "Globex Corp", "Gadget"),
    )

    payload = _payload(index, memory)
    rendered = repr(payload)
    assert ids["alice"] not in rendered
    assert "Bob Example" not in rendered
    assert "Globex Corp" not in rendered
    assert payload["meta"]["entities"]["scope_profile"] == "default"

    # and the same tree, loaded for the guest, is the guest's own subgraph
    guest = _graph(memory, profile="guest")
    assert {e.name for e in guest.entities} == {
        "Bob Example", "Globex Corp", "Gadget"
    }


# ── the stores disagree: ids from the two databases never cross ─────────────


def test_note_ids_and_entity_ids_never_join(index, memory):
    """A note id that *is* an entity id string stays two nodes, and a
    ``memory_entities`` row pointing at a note id manufactures no edge."""
    ids = _seed(memory)
    now = to_iso(utc_now())
    with memory.writer() as conn:
        # Deliberately an id shaped like a note id — the join someone would
        # reach for. It is a separate entity, not a note.
        conn.execute(
            "INSERT INTO entities (id, scope_profile, name, kind, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            ("Knowledge/Alpha", "default", "Alpha (entity)", "thing", now, now),
        )
        EntityStore(conn).add_relation(
            scope=OWNER,
            subject_id=ids["alice"],
            predicate="mentions",
            object_id="Knowledge/Alpha",
        )
        # A memory id that *is* the note id: the old wrong assumption. The
        # loader never reads memory_entities, so this must change nothing.
        mem = MemoryStore(conn).add(
            MemoryDraft(content="Alpha is the first note."),
            scope=OWNER,
            actor="tester",
        )
        conn.execute("UPDATE memories SET id=? WHERE id=?", ("Knowledge/Alpha", mem.id))
        conn.execute(
            "INSERT INTO memory_entities (memory_id, entity_id, role) VALUES (?,?,?)",
            ("Knowledge/Alpha", ids["alice"], "mention"),
        )

    payload = _payload(index, memory)
    ids_in_payload = {n["id"] for n in payload["nodes"]}
    assert "Knowledge/Alpha" in ids_in_payload
    assert "entity:Knowledge/Alpha" in ids_in_payload
    entity_ids = {
        n["id"] for n in payload["nodes"] if n["kind"] == "entity"
    }
    for e in payload["edges"]:
        # a note may link to another note (its wikilinks); it may never link
        # to the entity that happens to share its id
        assert not (
            e["source"] == "Knowledge/Alpha" and e["target"] in entity_ids
        )
        assert not (
            e["target"] == "Knowledge/Alpha" and e["source"] in entity_ids
        )
    assert (
        "entity:Knowledge/Alpha"
    ) in {e["target"] for e in payload["edges"]}
    assert _endpoints_resolve(payload)


# ── relations that cannot be edges are counted, never invented ──────────────


def test_a_literal_relation_emits_no_edge_and_a_closed_one_carries_its_bounds(
    index, memory
):
    """2.1 dropped closed intervals; 2.3 draws them with their interval."""
    ids = _seed(memory)
    closed_at = to_iso(utc_now())
    with memory.writer() as conn:
        es = EntityStore(conn)
        es.add_relation(
            scope=OWNER, subject_id=ids["alice"], predicate="born_in",
            object_literal="1990",
        )
        closed = es.add_relation(
            scope=OWNER, subject_id=ids["alice"], predicate="used_to_make",
            object_id=ids["widget"],
        )
        conn.execute(
            "UPDATE relations SET valid_to=? WHERE id=?", (closed_at, closed)
        )

    payload = _payload(index, memory)
    predicates = {e.get("predicate") for e in payload["edges"]}
    assert "born_in" not in predicates
    assert "used_to_make" in predicates
    used = _edge(payload, "used_to_make")
    assert used["valid_from"] is not None
    assert used["valid_to"] == closed_at
    assert used["time_span"] is not None
    assert closed_at in payload["meta"]["entities"]["time"]["stops"]
    block = payload["meta"]["entities"]
    assert block["literal_relations"] == 1
    assert block["time"]["unparsed_relations"] == 0
    assert _endpoints_resolve(payload)


def test_relations_trimmed_by_the_cap_are_counted_and_emit_nothing(index, memory):
    ids = _seed(memory)
    payload = _payload(index, memory, max_entities=2)

    block = payload["meta"]["entities"]
    assert block["truncated"] is True
    assert block["entity_count"] == 2
    assert block["dropped_relations"] == 1
    kept = {n["entity_id"] for n in payload["nodes"] if n["kind"] == "entity"}
    assert ids["widget"] not in kept
    assert _endpoints_resolve(payload)


def test_the_cap_keeps_the_highest_degree_then_the_name(index, memory):
    with memory.writer() as conn:
        es = EntityStore(conn)
        hub = es.get_or_create_entity("Hub", scope=OWNER, kind="thing")
        for leaf in ("Alpha leaf", "Beta leaf", "Gamma leaf"):
            other = es.get_or_create_entity(leaf, scope=OWNER, kind="thing")
            es.add_relation(
                scope=OWNER, subject_id=hub, predicate="links", object_id=other
            )

    payload = _payload(index, memory, max_entities=2)
    kept = {n["title"] for n in payload["nodes"] if n["kind"] == "entity"}
    assert kept == {"Hub", "Alpha leaf"}
    assert payload["meta"]["entities"]["truncated"] is True


def test_an_endpoint_from_another_profile_is_not_an_edge(index, memory):
    """Relations are scoped rows; an object entity in another profile cannot
    appear as an edge endpoint even if the id is named."""
    ids = _seed(memory)
    other = _seed(memory, profile="guest")
    with memory.writer() as conn:
        EntityStore(conn).add_relation(
            scope=OWNER,
            subject_id=ids["alice"],
            predicate="borrowed_from",
            object_id=other["widget"],
        )

    payload = _payload(index, memory)
    assert "borrowed_from" not in {e.get("predicate") for e in payload["edges"]}
    assert payload["meta"]["entities"]["dropped_relations"] == 1
    assert _endpoints_resolve(payload)


# ── missing or foreign databases are explicit, not exceptions ───────────────


def test_an_empty_profile_is_refused(tmp_path):
    """No default scope: "every profile" must be a refusal, not an omission."""
    db = tmp_path / "memory.db"
    with pytest.raises(ValueError):
        load_entity_graph(db, scope_profile="")
    with pytest.raises(ValueError):
        load_entity_graph(db, scope_profile="   ")


def test_a_missing_memory_db_is_empty_not_created(tmp_path, index):
    db = tmp_path / "absent.db"
    graph = load_entity_graph(db, scope_profile="default")
    assert graph.available is False
    assert graph.reason == "memory.db not found"
    assert graph.entities == ()
    assert not db.exists(), "the read-only loader created the file"

    payload = build_graph_payload(index, entity_graph=graph)
    assert payload["meta"]["entities"]["available"] is False
    assert payload["meta"]["entities"]["entity_count"] == 0


def test_a_database_without_the_tables_is_unavailable(tmp_path, index):
    db = tmp_path / "v2.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT)")
    conn.commit()
    conn.close()

    graph = load_entity_graph(db, scope_profile="default")
    assert graph.available is False
    assert graph.entities == ()


# ── the rest of the payload is unchanged ────────────────────────────────────


def test_the_model_never_draws_an_edge_to_a_missing_node(index):
    """The loader guarantees closed endpoints; the model must not rely on it.
    A hand-built graph with a dangling relation produces neither a dangling
    edge nor an isolated entity dot, and the relation is counted."""
    graph = EntityGraph(
        entities=(GraphEntity("ent_a", "Alpha"),),
        relations=(GraphRelation("ent_a", "mentions", "ent_missing"),),
        scope_profile="default",
    )
    payload = build_graph_payload(index, entity_graph=graph)
    assert [e for e in payload["edges"] if e["kind"] == "relation"] == []
    assert payload["meta"]["entities"]["entity_count"] == 0
    assert payload["meta"]["entities"]["dropped_relations"] == 1
    assert _endpoints_resolve(payload)


def test_an_absent_entity_graph_leaves_notes_and_edges_alone(index):
    plain = build_graph_payload(index)
    empty = build_graph_payload(index, entity_graph=None)
    assert [n["id"] for n in plain["nodes"]] == [n["id"] for n in empty["nodes"]]
    assert plain["edges"] == empty["edges"]
    assert len(plain["nodes"]) == 2


def test_the_body_gate_counts_notes_not_entities(index, memory):
    _seed(memory)
    payload = build_graph_payload(
        index, include_bodies=True, entity_graph=_graph(memory)
    )
    coverage = payload["meta"]["body_coverage"]
    assert coverage["total"] == 2, "entity nodes have no body plane"
    assert coverage["ok"] is True


def test_html_export_embeds_entity_data(index, memory, tmp_path):
    ids = _seed(memory)
    out = tmp_path / "graph.html"
    export_html(index, out, entity_graph=_graph(memory))
    html = out.read_text(encoding="utf-8")
    assert f"entity:{ids['alice']}" in html
    assert "works_at" in html
    assert "__ENTROPICMEM_" not in html


def test_the_viewer_draws_an_edge_with_its_typed_colour():
    js = graph_assets.asset("graph.js")
    assert "function edgeColor(d) { return d.color ||" in js, (
        "typed relation colours are in the payload but the viewer ignores them"
    )


# ── the owner-only scope filter (slice 2.2) ─────────────────────────────────

GUEST = Scope(profile="default", user="guest-user")


@pytest.fixture
def scoped(memory):
    """Owner and guest data in one profile, plus an entity both mention.

    The owner's three entities are linked to profile-wide memories. The
    guest's three are linked only to user-scoped memories. ``Shared Person``
    is linked to both, so it survives on the owner's mention. The guest also
    contributes a relation between two owner entities (hidden by its source
    memory) and one with no source memory whose endpoint is guest-only
    (hidden by the endpoint).
    """
    ids = {}
    guest_memories = []
    with memory.writer() as conn:
        es = EntityStore(conn)
        ms = MemoryStore(conn)

        def entity(name, kind):
            entity_id = es.get_or_create_entity(name, scope=OWNER, kind=kind)
            ids[name] = entity_id
            return entity_id

        alice = entity("Alice Owner", "person")
        acme = entity("Acme Owner Corp", "org")
        widget = entity("Widget Owner", "product")
        shared = entity("Shared Person", "person")
        zelda = entity("Zelda Guest", "person")
        zorblax = entity("Zorblax Guest Corp", "org")
        gizmo = entity("Gizmo Guest", "product")

        es.add_alias(acme, "acmeowneralias")
        es.add_alias(zelda, "zeldaguestalias")
        es.add_alias(zorblax, "zorblaxalias")
        es.add_alias(gizmo, "gizmoguestalias")

        def memory_row(content, scope, linked):
            result = ms.add(
                MemoryDraft(content=content), scope=scope, actor="tester"
            )
            assert result.ok, result
            for entity_id in linked:
                es.link_memory(result.id, entity_id)
            return result.id

        owner_mem = memory_row(
            "Alice Owner works at Acme Owner Corp.", OWNER, (alice, acme)
        )
        owner_mem2 = memory_row(
            "Acme Owner Corp makes Widget Owner.", OWNER, (acme, widget)
        )
        shared_owner_mem = memory_row(
            "Shared Person knows Alice Owner.", OWNER, (shared, alice)
        )
        guest_mem = memory_row(
            "Zelda Guest smuggles to Zorblax Guest Corp.",
            GUEST,
            (zelda, zorblax),
        )
        guest_mem2 = memory_row(
            "Zorblax Guest Corp fabricates Gizmo Guest.",
            GUEST,
            (zorblax, gizmo),
        )
        shared_guest_mem = memory_row(
            "Shared Person works with Zelda Guest.", GUEST, (shared, zelda)
        )
        guest_memories = [guest_mem, guest_mem2, shared_guest_mem]

        def relation(scope, subject, predicate, obj, *, memory_id=None):
            es.add_relation(
                scope=scope,
                subject_id=ids[subject],
                predicate=predicate,
                object_id=ids[obj],
                memory_id=memory_id,
            )

        relation(OWNER, "Alice Owner", "works_at", "Acme Owner Corp", memory_id=owner_mem)
        relation(OWNER, "Acme Owner Corp", "makes", "Widget Owner", memory_id=owner_mem2)
        relation(OWNER, "Shared Person", "knows", "Alice Owner", memory_id=shared_owner_mem)
        # No source memory: the endpoints decide. Both are owner-visible.
        relation(OWNER, "Alice Owner", "mentors", "Widget Owner")

        relation(GUEST, "Zelda Guest", "smuggles_to", "Zorblax Guest Corp", memory_id=guest_mem)
        relation(GUEST, "Zorblax Guest Corp", "fabricates", "Gizmo Guest", memory_id=guest_mem2)
        relation(GUEST, "Shared Person", "works_with", "Zelda Guest", memory_id=shared_guest_mem)
        # Guest-originated relation between two owner entities: the memory wins.
        relation(GUEST, "Alice Owner", "advises", "Acme Owner Corp", memory_id=guest_mem)
        # No source memory, but a guest-only endpoint: the endpoint wins.
        relation(GUEST, "Shared Person", "consorts_with", "Gizmo Guest")

    return memory, ids, guest_memories


#: Every distinctive string belonging to the guest side. The leak tests scan
#: the whole document for each one — ids, labels, aliases, predicates and
#: endpoints included. ``guest-user`` and the memory ids must not survive in
#: meta either.
GUEST_TOKENS = (
    "Zelda Guest",
    "zelda guest",
    "zeldaguestalias",
    "Zorblax Guest Corp",
    "zorblax guest corp",
    "zorblaxalias",
    "Gizmo Guest",
    "gizmo guest",
    "gizmoguestalias",
    "smuggles_to",
    "fabricates",
    "works_with",
    "advises",
    "consorts_with",
    "guest-user",
)


def _guest_tokens(ids, guest_memories):
    return GUEST_TOKENS + tuple(
        ids[name]
        for name in ("Zelda Guest", "Zorblax Guest Corp", "Gizmo Guest")
    ) + tuple(guest_memories)


def _offenders(text, tokens):
    return [token for token in tokens if token in text]


def test_owner_scope_hides_guest_only_entities_and_counts_them(index, scoped):
    memory, ids, _ = scoped
    graph = _graph(memory)

    assert graph.scope == "owner"
    assert {e.name for e in graph.entities} == {
        "Alice Owner",
        "Acme Owner Corp",
        "Widget Owner",
        "Shared Person",
    }
    assert graph.hidden_entities == 3
    assert graph.hidden_relations == 5
    assert graph.dropped_relations == 0
    assert not _offenders(repr(graph), _guest_tokens(ids, ()))


def test_owner_scope_keeps_a_shared_entity_and_only_its_owner_edge(index, scoped):
    memory, ids, _ = scoped
    payload = _payload(index, memory)
    nodes = {n["id"]: n for n in payload["nodes"]}
    shared = nodes[f"entity:{ids['Shared Person']}"]
    assert shared["title"] == "Shared Person"

    predicates = {e.get("predicate") for e in payload["edges"]}
    assert "knows" in predicates          # owner memory, both endpoints visible
    assert "mentors" in predicates        # no memory, owner endpoints
    assert "works_with" not in predicates # guest memory, even though Shared is visible
    assert _endpoints_resolve(payload)


def test_scope_all_is_the_explicit_opt_in(index, scoped):
    memory, ids, _ = scoped
    graph = _graph(memory, scope="all")

    assert graph.scope == "all"
    assert graph.hidden_entities == 0
    assert graph.hidden_relations == 0
    assert {e.name for e in graph.entities} == {
        "Alice Owner",
        "Acme Owner Corp",
        "Widget Owner",
        "Shared Person",
        "Zelda Guest",
        "Zorblax Guest Corp",
        "Gizmo Guest",
    }
    assert len(graph.relations) == 9


def test_an_unknown_scope_is_refused(tmp_path):
    with pytest.raises(ValueError):
        load_entity_graph(
            tmp_path / "memory.db", scope_profile="default", scope="everything"
        )


def test_a_relation_with_cross_profile_provenance_is_hidden(index, memory):
    """A relation whose source memory is real but in another profile cannot be
    resolved as owner data, so it fails closed."""
    ids = _seed(memory)
    with memory.writer() as conn:
        other = MemoryStore(conn).add(
            MemoryDraft(content="A fact in another profile."),
            scope=Scope(profile="guest"),
            actor="tester",
        )
        EntityStore(conn).add_relation(
            scope=OWNER,
            subject_id=ids["alice"],
            predicate="orphaned",
            object_id=ids["acme"],
            memory_id=other.id,
        )

    graph = _graph(memory)
    assert "orphaned" not in {r.predicate for r in graph.relations}
    assert graph.hidden_relations == 1


def test_the_cap_is_applied_after_the_scope_filter(index, scoped):
    memory, ids, _ = scoped
    payload = _payload(index, memory, max_entities=2)
    block = payload["meta"]["entities"]

    assert block["truncated"] is True
    assert block["hidden_entities"] == 3
    kept = {n["title"] for n in payload["nodes"] if n["kind"] == "entity"}
    assert kept == {"Alice Owner", "Acme Owner Corp"}
    # Four eligible owner relations were considered; one survived the two-node
    # cap. The guest relations never entered the eligible set.
    assert block["dropped_relations"] == 3
    assert _endpoints_resolve(payload)


def test_json_export_leaks_no_non_owner_token(index, scoped, tmp_path):
    memory, ids, guest_memories = scoped
    out = tmp_path / "json" / "graph.json"
    export_json(index, out, entity_graph=_graph(memory))
    text = out.read_bytes().decode("utf-8")

    tokens = _guest_tokens(ids, guest_memories)
    assert not _offenders(text, tokens)
    # Positive controls: the owner side is present, so the scan is not passing
    # because the export is empty.
    for token in ("Alice Owner", "acmeowneralias", "works_at", "mentors"):
        assert token in text
    assert f"entity:{ids['Alice Owner']}" in text

    block = json.loads(text)["meta"]["entities"]
    assert block["scope"] == "owner"
    assert block["hidden_entities"] == 3
    assert block["hidden_relations"] == 5
    assert not _offenders(repr(block), tokens)


def test_html_export_leaks_no_non_owner_token(index, scoped, tmp_path):
    memory, ids, guest_memories = scoped
    tokens = _guest_tokens(ids, guest_memories)

    # Control: none of the fixture's tokens already lives in the viewer assets.
    # If one did, a byte scan could not tell the fixture from the shell.
    baseline_dir = tmp_path / "baseline"
    export_html(index, baseline_dir / "graph.html")
    baseline = (baseline_dir / "graph.html").read_bytes().decode("utf-8")
    assert not _offenders(baseline, tokens), "a fixture token is in the viewer shell"

    out_dir = tmp_path / "leaky"
    export_html(index, out_dir / "graph.html", entity_graph=_graph(memory))
    for name in ("graph.html", "graph.json"):
        text = (out_dir / name).read_bytes().decode("utf-8")
        assert not _offenders(text, tokens), f"{name} leaked non-owner data"
        for token in ("Alice Owner", "acmeowneralias", "works_at"):
            assert token in text


def test_the_scope_is_reported_and_the_viewer_filters_nothing():
    js = graph_assets.asset("graph.js")
    assert "DATA.meta.entities" in js
    assert "owner only" in js and "all scopes" in js
    # No client-side scope predicate: the data is already filtered.
    assert "scope === \"owner\"" not in js


def test_meta_reports_the_scope_without_naming_the_hidden(index, scoped):
    memory, _, _ = scoped
    block = _payload(index, memory)["meta"]["entities"]
    assert block["scope"] == "owner"
    assert block["scope_profile"] == "default"
    assert block["hidden_entities"] == 3
    assert block["hidden_relations"] == 5
    assert set(block) == {
        "available",
        "reason",
        "scope_profile",
        "scope",
        "entity_count",
        "relation_edge_count",
        "hidden_entities",
        "hidden_relations",
        "truncated",
        "dropped_relations",
        "literal_relations",
        "time",
    }


# ── the CLI flag is the only way in, and it stays opt-in ────────────────────


def _cli_env(tmp_path: Path, memory) -> dict:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ENTROPICMEM_")
    }
    env.update({
        "ENTROPICMEM_VAULT_PATH": str(tmp_path / "vault"),
        "ENTROPICMEM_INDEX_DB": str(tmp_path / "index.db"),
        "ENTROPICMEM_MEMORY_DB": str(memory.path),
    })
    return env


def test_cli_exports_entities_only_when_asked(index, memory, tmp_path):
    _seed(memory)
    out = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable, str(CLI), "graph", "export",
            "--format", "json", "--entities", "--output-dir", str(out),
        ],
        env=_cli_env(tmp_path, memory),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "Entities: 3 nodes, 2 relations" in result.stdout
    assert "scope 'owner'" in result.stdout
    payload = json.loads((out / "graph.json").read_text(encoding="utf-8"))
    assert {n["kind"] for n in payload["nodes"]} == {"note", "entity"}
    assert payload["meta"]["entities"]["available"] is True


def test_cli_defaults_to_owner_scope(index, scoped, tmp_path):
    memory, _, _ = scoped
    out = tmp_path / "owner"
    result = subprocess.run(
        [
            sys.executable, str(CLI), "graph", "export",
            "--format", "json", "--entities", "--output-dir", str(out),
        ],
        env=_cli_env(tmp_path, memory),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "Entities: 4 nodes, 4 relations" in result.stdout
    assert "scope 'owner'" in result.stdout
    text = (out / "graph.json").read_text(encoding="utf-8")
    assert "Alice Owner" in text
    assert "Zelda Guest" not in text
    assert "zeldaguestalias" not in text


def test_cli_scope_all_is_an_explicit_opt_in(index, scoped, tmp_path):
    memory, _, _ = scoped
    out = tmp_path / "all"
    result = subprocess.run(
        [
            sys.executable, str(CLI), "graph", "export",
            "--format", "json", "--entities", "--scope", "all",
            "--output-dir", str(out),
        ],
        env=_cli_env(tmp_path, memory),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "Entities: 7 nodes, 9 relations" in result.stdout
    assert "scope 'all'" in result.stdout
    text = (out / "graph.json").read_text(encoding="utf-8")
    assert "Zelda Guest" in text
    assert "zeldaguestalias" in text


def test_cli_refuses_entities_for_dot(index, memory, tmp_path):
    result = subprocess.run(
        [
            sys.executable, str(CLI), "graph", "export",
            "--format", "dot", "--entities", "--output-dir", str(tmp_path / "out"),
        ],
        env=_cli_env(tmp_path, memory),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 2
    assert "only supported for --format html or json" in result.stderr


# ── the time slider (slice 2.3) ─────────────────────────────────────────────

T2019 = "2019-12-31T23:00:00.000Z"
T2020 = "2020-01-01T00:00:00.000Z"
T2021 = "2021-06-01T12:00:00.000Z"


def test_a_closed_interval_is_an_edge_and_extends_the_time_axis(index, memory):
    """2.1 counted closed intervals and drew nothing; 2.3 draws the interval."""
    ids = _seed(memory)
    _set_interval(memory, ids["works_at"], valid_from=T2020, valid_to=T2021)

    payload = _payload(index, memory)
    edge = _edge(payload, "works_at")
    assert edge["valid_from"] == T2020
    assert edge["valid_to"] == T2021
    assert edge["time_span"] is not None
    assert edge["time_span"][0] == 0
    assert edge["time_span"][1] == 1

    time = payload["meta"]["entities"]["time"]
    assert time["available"] is True
    assert time["min"] == T2020
    assert T2021 in time["stops"]
    assert time["stops"] == sorted(time["stops"])
    assert time["unparsed_relations"] == 0
    assert _endpoints_resolve(payload)


def test_open_ended_intervals_get_infinite_ranks_on_the_missing_side(index, memory):
    ids = _seed(memory)
    _set_interval(memory, ids["works_at"], valid_from=T2020, valid_to=None)
    _set_interval(memory, ids["makes"], valid_from=None, valid_to=T2019)

    payload = _payload(index, memory)
    time = payload["meta"]["entities"]["time"]
    assert time["stops"] == [T2019, T2020]

    works = _edge(payload, "works_at")["time_span"]
    makes = _edge(payload, "makes")["time_span"]
    assert works == [1, 2], "a null valid_to is +infinity, one past the last stop"
    assert makes == [-1, 0], "a null valid_from is -infinity"
    assert _visible(works, 1, 1) is True
    assert _visible(makes, 0, 0) is True


def test_equal_boundaries_are_a_point_interval(index, memory):
    ids = _seed(memory)
    _set_interval(memory, ids["works_at"], valid_from=T2021, valid_to=T2021)
    _set_interval(memory, ids["makes"], valid_from=T2020, valid_to=None)

    payload = _payload(index, memory)
    time = payload["meta"]["entities"]["time"]
    span = _edge(payload, "works_at")["time_span"]
    assert span[0] == span[1]
    assert time["stops"][span[0]] == T2021

    assert _visible(span, 0, 0) is False
    assert _visible(span, 1, 1) is True
    assert _visible(span, 2, 2) is False


def test_an_interval_outside_the_window_is_hidden_but_not_scope_hidden(index, memory):
    ids = _seed(memory)
    _set_interval(memory, ids["works_at"], valid_from=T2020, valid_to=T2020)
    _set_interval(memory, ids["makes"], valid_from=T2021, valid_to=T2021)

    payload = _payload(index, memory)
    works = _edge(payload, "works_at")["time_span"]
    makes = _edge(payload, "makes")["time_span"]
    assert _visible(works, 1, 1) is False
    assert _visible(makes, 1, 1) is True

    block = payload["meta"]["entities"]
    assert block["hidden_relations"] == 0, "time is a separate axis from scope"
    assert block["time"]["unparsed_relations"] == 0


def test_an_unparsed_bound_is_counted_and_left_visible(index, memory):
    ids = _seed(memory)
    _set_interval(memory, ids["works_at"], valid_from="not-a-timestamp", valid_to=None)

    payload = _payload(index, memory)
    edge = _edge(payload, "works_at")
    assert edge["time_span"] is None, "an unfilterable edge is never hidden by time"
    time = payload["meta"]["entities"]["time"]
    assert time["available"] is True, "the other relation still supplies an axis"
    assert time["unparsed_relations"] == 1
    assert _visible([-1, len(time["stops"])], 0, len(time["stops"]) - 1)


def test_no_bound_means_no_axis_and_no_filtering(index, memory):
    ids = _seed(memory)
    _set_interval(memory, ids["works_at"], valid_from=None, valid_to=None)
    _set_interval(memory, ids["makes"], valid_from=None, valid_to=None)

    payload = _payload(index, memory)
    time = payload["meta"]["entities"]["time"]
    assert time["available"] is False
    assert time["stops"] == []
    assert time["min"] == ""
    assert time["max"] == ""
    assert time["unparsed_relations"] == 0
    for predicate in ("works_at", "makes"):
        assert _edge(payload, predicate)["time_span"] is None


def test_the_viewer_ships_a_time_window_control():
    template = graph_assets.template()
    for marker in (
        'id="time-control"',
        'id="time-from"',
        'id="time-to"',
        'id="time-from-label"',
        'id="time-to-label"',
    ):
        assert marker in template, f"time slider markup missing: {marker}"

    js = graph_assets.asset("graph.js")
    assert "function buildTimeSlider()" in js
    assert "DATA.meta.entities" in js
    assert "time.stops" in js
    assert 'getElementById("time-from").addEventListener("input"' in js
    assert 'getElementById("time-to").addEventListener("input"' in js

    build = re.search(r"function buildTimeSlider\(\) \{(.*?)\n\}", js, re.S)
    assert build, "buildTimeSlider body not found"
    body = build.group(1)
    assert "const last = time.stops.length - 1" in body
    assert "timeFrom = 0" in body
    assert "timeTo = last" in body
    assert 'from.value = "0"' in body
    assert "to.value = String(last)" in body
    assert "timeReady = true" in body
    assert "box.hidden = true" in body

    sync = re.search(r"function syncTimeWindow\(changed\) \{(.*?)\n\}", js, re.S)
    assert sync, "syncTimeWindow body not found"
    assert "if (timeFrom > timeTo)" in sync.group(1)
    assert 'changed === "from"' in sync.group(1)


def test_the_viewer_filters_only_relation_edges_by_the_serialized_span():
    js = graph_assets.asset("graph.js")

    predicate = re.search(r"function timeVisible\(e\) \{(.*?)\n\}", js, re.S)
    assert predicate, "timeVisible helper not found"
    body = predicate.group(1)
    assert 'e.kind !== "relation"' in body
    assert "!e.time_span" in body
    assert "e.time_span[0] <= timeTo" in body
    assert "e.time_span[1] >= timeFrom" in body

    edge_filter = re.search(
        r"const edges = DATA\.edges\.filter\(e => \{(.*?)\n  \}\);", js, re.S
    )
    assert edge_filter, "edge filter body not found"
    assert "timeVisible(e)" in edge_filter.group(1)


def test_time_hidden_is_counted_outside_the_scope_axis():
    js = graph_assets.asset("graph.js")
    stats = re.search(r"function updateStats\(\) \{(.*?)\n\}", js, re.S)
    assert stats, "updateStats body not found"
    body = stats.group(1)
    assert "timeHidden" in body
    assert "outside time window" in body
    assert "hidden_relations" not in body, "scope losses are not time losses"

    reset = re.search(r"function resetFilters\(\) \{(.*?)\n\}", js, re.S)
    assert reset, "resetFilters body not found"
    body = reset.group(1)
    assert 'getElementById("time-from").value = "0"' in body
    assert 'getElementById("time-to").value = String(last)' in body
    assert "timeFrom = 0" in body
    assert "timeTo = last" in body
