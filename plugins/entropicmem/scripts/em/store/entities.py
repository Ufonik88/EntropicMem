"""Entities, aliases and relations (v3 §3.6, card EM-208).

Two decisions here are deliberate and are the ones that keep the graph from
filling up with junk:

- **A capitalised phrase only becomes an entity once it has been seen in two
  different memories.** One mention is not an entity; it is a capitalised word.
  The counter lives in ``meta`` under ``entity_seen:<profile>:<norm>`` so the
  decision survives a restart and is shared by every writer.
- **The built-in seed dictionary is off by default.** ``entities.seed_builtin``
  defaults to false and belongs to the EM-407 typed config, so it is a
  parameter here. The seed is the generic list from ``triple_extract`` and
  nothing else; a personal or project-specific entity is never seeded.

Alias lookup is n-gram (1-4 tokens) with casefold and punctuation stripped, so
"Zorp", "Zorp Systems" and "Zorp Systems," all resolve to the same row.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any

from ..clock import new_id, to_iso, utc_now
from .types import Scope

# Entities are proposed from capitalised phrases only.
_CAP_PHRASE = re.compile(r"\b([A-Z][\w&.'-]*(?:\s+(?:of|the|and|de|van|von)\s+)?(?:\s+[A-Z][\w&.'-]*)*)\b")
_TOKEN = re.compile(r"[\w&]+", re.UNICODE)
MAX_NGRAM = 4

ENTITY_KINDS = ("person", "org", "place", "thing", "event", "product")

#: Characters stripped from the ends of a matched phrase.
_PUNCT = " .,'-'"

#: How many distinct memory ids a phrase's sighting list keeps. The only
#: question ever asked of it is "seen at least twice?", so two is enough, and a
#: cap keeps a ``meta`` row per candidate phrase bounded.
_SEEN_CAP = 2


def normalise(text: str) -> str:
    """Casefold and strip punctuation, leaving single-spaced tokens.

    This is the join key for alias lookup. Anything that would let two
    different spellings of the same name miss each other is removed here:
    case, punctuation, and runs of whitespace.
    """
    return " ".join(_TOKEN.findall(text.casefold()))


def ngrams(text: str, max_n: int = MAX_NGRAM) -> list[str]:
    """All 1..max_n token n-grams of a normalised string, longest first.

    Longest first matters: "Zorp Systems" must resolve to the org before the
    bare "Zorp" can claim the mention.
    """
    tokens = normalise(text).split()
    out: list[str] = []
    for size in range(min(max_n, len(tokens)), 0, -1):
        for start in range(len(tokens) - size + 1):
            out.append(" ".join(tokens[start : start + size]))
    return out


#: Split points between sentences. A capitalised phrase may never span one:
#: without this, "Cape Town. I" matched as a single phrase across the boundary.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[ \t]*\n[ \t]*|(?<=[.!?])[ \t]+")


def _scan_phrases(content: str, *, strip_opener: bool) -> list[str]:
    """Capitalised phrases in ``content``, in order, de-duplicated.

    Split on sentence boundaries first, so a phrase can never span two
    sentences ("Cape Town. I" is not one phrase). ``strip_opener`` selects
    between the two callers' rules for a phrase that opens a sentence; see
    ``candidate_phrases`` and ``known_phrases``.
    """
    from stopwords import STOPWORDS

    out: list[str] = []
    seen: set[str] = set()

    for sentence in _SENTENCE_SPLIT.split(content or ""):
        for match in _CAP_PHRASE.finditer(sentence):
            phrase = match.group(0).strip(_PUNCT)
            if strip_opener and not sentence[: match.start()].strip():
                # Everything before the match is punctuation/whitespace: the
                # phrase opens the sentence, so its first token is a word that
                # merely happens to be capitalised.
                _, _, rest = phrase.partition(" ")
                phrase = rest.strip(_PUNCT)
            if len(phrase) < 2 or not any(ch.isupper() for ch in phrase):
                continue
            tokens = normalise(phrase).split()
            if not tokens or all(t in STOPWORDS for t in tokens):
                continue
            key = normalise(phrase)
            if key and key not in seen:
                seen.add(key)
                out.append(phrase)
    return out


def candidate_phrases(content: str) -> list[str]:
    """Capitalised phrases worth *proposing* as entities.

    A capitalised word at the start of a sentence is punctuation, not evidence
    of an entity, which is what this function has always claimed to do:

    * a single-token phrase that opens a sentence is dropped ("Met");
    * the first token of a multi-token phrase that opens a sentence is stripped
      ("Met Alice Example" -> "Alice Example");
    * a phrase whose first token is preceded only by punctuation and whitespace
      counts as opening, so "(Met Alice Example)" is treated like the bare
      sentence;
    * mid-sentence phrases are kept exactly as matched, and may never span a
      sentence boundary.

    Two memories starting "Deployed to ..." used to promote an entity called
    "Deployed". Stopword-only fragments are dropped too, so a phrase left empty
    by the strip is dropped rather than proposed.

    The strip is the *proposal* rule only. Resolving an already-registered
    entity uses ``known_phrases``, which keeps the leading token: a name that
    opens a sentence is still that name.
    """
    return _scan_phrases(content, strip_opener=True)


def known_phrases(content: str) -> list[str]:
    """Capitalised phrases to resolve against known entities, unstripped.

    Same scan as ``candidate_phrases`` without the sentence-opening rule, so a
    registered entity still claims a mention at the start of a sentence. Only
    the proposal path may discard a leading capitalised word.
    """
    return _scan_phrases(content, strip_opener=False)


class EntityStore:
    """Entities, aliases, memory links and relations.

    Caller owns the connection and transaction, as with the other stores.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- entities ---------------------------------------------------------

    def get_or_create_entity(self, name: str, *, scope: Scope, kind: str = "thing") -> str:
        """Return the entity id for ``name`` in this scope, creating if needed."""
        now = to_iso(utc_now())
        row = self._conn.execute(
            "SELECT id FROM entities WHERE scope_profile=? AND name=?", (scope.profile, name)
        ).fetchone()
        if row is not None:
            return row["id"]
        entity_id = new_id("ent")
        try:
            self._conn.execute(
                "INSERT INTO entities (id, scope_profile, name, kind, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?)",
                (entity_id, scope.profile, name, kind, now, now),
            )
        except sqlite3.IntegrityError:
            # Another writer inserted the same name between the SELECT and here.
            row = self._conn.execute(
                "SELECT id FROM entities WHERE scope_profile=? AND name=?", (scope.profile, name)
            ).fetchone()
            if row is None:
                raise
            return row["id"]
        self.add_alias(entity_id, name)
        return entity_id

    def add_alias(self, entity_id: str, alias: str) -> None:
        """Record a spelling of this entity. The canonical name is added too."""
        for spelling in {alias, normalise(alias)}:
            if not spelling:
                continue
            self._conn.execute(
                "INSERT OR IGNORE INTO entity_aliases (alias_norm, entity_id) VALUES (?,?)",
                (spelling, entity_id),
            )

    def find_entity(self, alias: str) -> str | None:
        """Resolve any spelling to an entity id, or None.

        Exact alias match only. The caller decides which n-grams to try; keeping
        the lookup a single indexed probe is what holds the p95 budget.
        """
        key = normalise(alias)
        if not key:
            return None
        row = self._conn.execute(
            "SELECT entity_id FROM entity_aliases WHERE alias_norm=? LIMIT 1", (key,)
        ).fetchone()
        return row["entity_id"] if row else None

    def list_entities(self, *, scope: Scope, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM entities WHERE scope_profile=? ORDER BY name LIMIT ?",
            (scope.profile, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- linking ----------------------------------------------------------

    def link(self, memory_id: str, content: str, *, scope: Scope) -> list[str]:
        """Link a memory to known entities and propose new ones.

        Returns the entity ids now linked. A proposed entity is only *created*
        on its second sighting in a different memory, which is what stops a
        single capitalised word from permanently entering the graph.
        """
        linked: list[str] = []
        seen: set[str] = set()
        proposals = candidate_phrases(content)

        for phrase in known_phrases(content):
            for gram in ngrams(phrase):
                entity_id = self.find_entity(gram)
                if entity_id is not None:
                    if entity_id not in seen:
                        self._link(memory_id, entity_id)
                        seen.add(entity_id)
                        linked.append(entity_id)
                    break  # longest gram wins; do not also link a substring

        for phrase in proposals:
            key = normalise(phrase)
            if not key or self.find_entity(key) is not None:
                continue
            if self._bump_seen(scope, key, memory_id) >= 2:
                entity_id = self.get_or_create_entity(phrase, scope=scope)
                # The phrase is an entity now: alias lookup resolves it, so the
                # sighting counter is dead weight. Delete the row.
                self._conn.execute(
                    "DELETE FROM meta WHERE key=?", (f"entity_seen:{scope.profile}:{key}",)
                )
                self._link(memory_id, entity_id)
                seen.add(entity_id)
                linked.append(entity_id)
        return linked

    def _link(self, memory_id: str, entity_id: str, role: str = "mention") -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO memory_entities (memory_id, entity_id, role) VALUES (?,?,?)",
            (memory_id, entity_id, role),
        )

    def _bump_seen(self, scope: Scope, key: str, memory_id: str) -> int:
        """Count distinct memories a proposed phrase has appeared in.

        Stored in ``meta`` so the threshold decision is durable and shared. The
        value is the list of distinct memory ids seen, not a raw count, so one
        memory mentioning the same phrase five times still only counts once.
        The list is capped at the most recent 2: the only question ever asked of
        it is "has this been seen at least twice", and nothing is lost by
        dropping older ids.
        """
        meta_key = f"entity_seen:{scope.profile}:{key}"
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (meta_key,)).fetchone()
        memories: list[str] = json.loads(row["value"]) if row and row["value"] else []
        if memory_id not in memories:
            memories.append(memory_id)
        memories = memories[-_SEEN_CAP:]
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (meta_key, json.dumps(memories)),
        )
        return len(memories)

    def forget_sightings(self, memory_id: str, *, profile: str) -> int:
        """Drop a purged memory from every phrase's sighting list.

        A hard delete must forget the phrases it mentioned, not just its row: a
        sighting row holds the normalised capitalised phrase in its key, so a
        purged memory's names would otherwise survive in ``meta`` forever. A row
        left with no ids is deleted rather than kept as an empty list.

        Scoped to one profile so another profile's counter is untouched.
        """
        prefix = f"entity_seen:{profile}:"
        rows = self._conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ESCAPE '\\'", (prefix.replace("_", "\\_") + "%",)
        ).fetchall()
        removed = 0
        for row in rows:
            try:
                memories: list[str] = json.loads(row["value"]) if row["value"] else []
            except ValueError:  # a hand-edited row must not break a purge
                continue
            if memory_id not in memories:
                continue
            memories = [m for m in memories if m != memory_id]
            removed += 1
            if memories:
                self._conn.execute("UPDATE meta SET value=? WHERE key=?", (json.dumps(memories), row["key"]))
            else:
                self._conn.execute("DELETE FROM meta WHERE key=?", (row["key"],))
        return removed

    # --- relations --------------------------------------------------------

    def add_relation(
        self,
        *,
        scope: Scope,
        subject_id: str,
        predicate: str,
        object_id: str | None = None,
        object_literal: str | None = None,
        memory_id: str | None = None,
        confidence: float = 0.7,
        source: str = "extraction",
    ) -> str:
        """Record one relation. Exactly one of object_id/object_literal is set."""
        if not object_id and not object_literal:
            raise ValueError("a relation needs an object_id or an object_literal")
        relation_id = new_id("rel")
        self._conn.execute(
            "INSERT INTO relations (id, scope_profile, subject_id, predicate, object_id,"
            " object_literal, memory_id, confidence, valid_from, created_at, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                relation_id,
                scope.profile,
                subject_id,
                predicate,
                object_id,
                object_literal,
                memory_id,
                confidence,
                to_iso(utc_now()),
                to_iso(utc_now()),
                source,
            ),
        )
        return relation_id

    def close_relations(self, memory_id: str, valid_to: str) -> int:
        """Close every open relation attached to a memory (used by supersede)."""
        cur = self._conn.execute(
            "UPDATE relations SET valid_to=? WHERE memory_id=? AND valid_to IS NULL", (valid_to, memory_id)
        )
        return max(0, cur.rowcount or 0)

    def relations_for(self, entity_id: str, *, include_closed: bool = False) -> list[dict[str, Any]]:
        sql = (
            "SELECT * FROM relations WHERE (subject_id=? OR object_id=?)"
            + ("" if include_closed else " AND valid_to IS NULL")
            + " ORDER BY created_at DESC"
        )
        return [dict(r) for r in self._conn.execute(sql, (entity_id, entity_id))]

    # --- entity card ------------------------------------------------------

    def entity_card(self, entity_id: str, scope: Scope) -> dict[str, Any] | None:
        """Everything worth showing about one entity.

        Relations include recently closed ones, because "used to work on X" is
        often the most useful thing on a card.
        """
        row = self._conn.execute(
            "SELECT * FROM entities WHERE id=? AND scope_profile=?", (entity_id, scope.profile)
        ).fetchone()
        if row is None:
            return None

        aliases = [
            r["alias_norm"]
            for r in self._conn.execute(
                "SELECT alias_norm FROM entity_aliases WHERE entity_id=? ORDER BY alias_norm",
                (entity_id,),
            )
        ]
        memories = [
            dict(m)
            for m in self._conn.execute(
                "SELECT m.* FROM memory_entities me JOIN memories m ON m.id = me.memory_id"
                " WHERE me.entity_id=? AND m.status != 'deleted'"
                " ORDER BY m.updated_at DESC LIMIT 20",
                (entity_id,),
            )
        ]
        closed = self._conn.execute(
            "SELECT * FROM relations WHERE (subject_id=? OR object_id=?) AND valid_to IS NOT NULL"
            " ORDER BY valid_to DESC LIMIT 10",
            (entity_id, entity_id),
        ).fetchall()
        episodes = [
            dict(e)
            for e in self._conn.execute(
                "SELECT DISTINCT e.* FROM episodes e JOIN episodes_fts f ON f.rowid = e.rid"
                " WHERE episodes_fts MATCH ? ORDER BY rank LIMIT 5",
                (f'"{row["name"]}"',),
            )
        ]
        return {
            "id": entity_id,
            "name": row["name"],
            "kind": row["kind"],
            "description": row["description"],
            "aliases": aliases,
            "memories": memories,
            "relations": self.relations_for(entity_id),
            "closed_relations": [dict(r) for r in closed],
            "episodes": episodes,
        }

    # --- seed -------------------------------------------------------------

    def seed_builtin_entities(self, *, scope: Scope, enable: bool = False) -> int:
        """Seed the generic dictionary from ``triple_extract``.

        Off unless ``enable`` (the plan's ``entities.seed_builtin`` default is
        false, and the typed config is EM-407). Only the generic built-in list
        is used; nothing user-specific is ever seeded.

        ``_EXTRA_ALIASES`` maps a spelling to its display form, and which half
        of that mapping is the "name" depends on how the dictionary is built.
        Both the keys and the values are seeded, each canonicalised, and every
        spelling is registered as an alias of whichever display form survives.
        Relying on iteration order here meant the seeded names differed between
        environments.
        """
        if not enable:
            return 0
        from triple_extract import _EXTRA_ALIASES, canonical_entity

        names: set[str] = set()
        for alias in list(_EXTRA_ALIASES) + list(_EXTRA_ALIASES.values()):
            display = canonical_entity(alias)
            if not display:
                continue
            names.add(display)

        for name in sorted(names):
            entity_id = self.get_or_create_entity(name, scope=scope, kind="product")
            for alias in list(_EXTRA_ALIASES) + list(_EXTRA_ALIASES.values()):
                if canonical_entity(alias) == name:
                    self.add_alias(entity_id, alias)
        return len(names)


class EntityLinker:
    """The plan's ``EntityLinker.link(memory)`` entry point.

    The scope is bound at construction because it is fixed for a run of linking;
    passing it per call would be noise, and the plan's signature does not have
    it.
    """

    def __init__(self, conn: sqlite3.Connection, scope: Scope) -> None:
        self._conn = conn
        self._scope = scope
        self._store = EntityStore(conn)

    def link(self, memory: dict[str, Any]) -> list[str]:
        return self._store.link(memory["id"], memory.get("content", ""), scope=self._scope)


def time_link(linker: EntityLinker, memory: dict[str, Any]) -> tuple[list[str], float]:
    """Link a memory and report elapsed milliseconds. Used by the p95 benchmark."""
    started = time.perf_counter()
    linked = linker.link(memory)
    return linked, (time.perf_counter() - started) * 1000.0
