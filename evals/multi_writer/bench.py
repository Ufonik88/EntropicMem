"""Multi-writer contradiction benchmark: two agents, one store, one ground truth.

The question a single-writer retrieval suite cannot answer: when two agents write
about the same key and one of them is behind, which value does the store serve?

**Everything is measured on the shipped path.** Every number comes from
``MemoryStore.add`` / ``MemoryStore.supersede`` and
``em.retrieval.pipeline.retrieve`` against a temporary v3 store. No LLM judges
anything: values are synthetic codenames, so "the current value was served" is a
substring test. The corpus is generated from ``--seed`` and ``--keys``, so a run
reproduces exactly.

**Four scenario shapes, three write protocols.** The variable is the write
protocol — not the database, the retrieval weights or the corpus:

``append``
    Every write is a plain ``remember``. The "shared store, newest wins"
    baseline: nothing is superseded, so every historical value stays ``active``
    and ranking decides.

``supersede``
    A correcting writer supersedes the row it is correcting (what
    ``entropicmem_update`` does by default). A writer that re-asserts a dead
    value is not cooperating and is written the way an agent would write it: a
    plain ``remember``.

``supersede_guard``
    ``supersede`` plus a caller-side echo check that uses only the shipped read
    surface: before a plain write, look for an identical text that already
    exists as a *superseded* row and skip the write. This is a policy an agent
    can adopt today; it is not a store feature.

The shapes exist because each one isolates a different mechanism, and collapsing
them would let one number stand for three different claims:

``succession``
    v1 → v2 → v3, all terse, one writer. The control: plain recency already
    handles the easy case, and a benchmark that only measured this would say
    nothing.

``pinned_stale``
    v1 is written as a pinned, high-importance fact (a constraint), then
    corrected. In an append-only store the pinned row keeps a 1.0 recency term
    and the pinned generator's weight, so the corrected value has to beat a
    deliberately favoured stale row. This is the mechanism ``supersede`` exists
    for: a superseded row is not a candidate at all.

``rogue_echo``
    A correction, then a *second* writer re-asserts the dead value with the
    corroborating detail a real note carries, so it is the better lexical
    match. No store can tell that from a legitimate re-assertion — this is the
    residual, and it is reported as such rather than averaged away.

``concurrent_conflict``
    Two writers claim different values at nearly the same time. There is no
    ground truth to score against, so these keys are reported separately: what
    matters is that the store ends up holding two live values, visibly.

Stdlib only, no network, no dependence on the wall clock in scoring.
"""

from __future__ import annotations

import random
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from em.clock import to_iso
from em.retrieval.candidates import OWNER_TYPE_MEMORY
from em.retrieval.pipeline import retrieve
from em.store.db import Store
from em.store.memories import MemoryStore
from em.store.migrations import migrate
from em.store.types import MemoryDraft, Scope

PROFILE = "multi-writer-eval"

#: The virtual clock's origin. Fixed so the same seed produces the same stamps.
BASE = datetime(2026, 3, 1, tzinfo=timezone.utc)

#: How long after the last write the queries are asked.
ASK_AFTER_DAYS = 30

_KEYS = (
    "deploy branch",
    "release channel",
    "staging host",
    "vendor contact",
    "on-call rota",
    "backup window",
    "api version",
    "signing key",
    "status page",
    "billing plan",
    "region pin",
    "retention window",
)
_NOUNS = (
    "aurora", "basalt", "cinder", "dahlia", "ember", "fjord",
    "garnet", "harbor", "indigo", "juniper", "kestrel", "lantern",
)

PROTOCOLS = ("append", "supersede", "supersede_guard")
SHAPES = ("succession", "pinned_stale", "rogue_echo", "concurrent_conflict")


@dataclass(frozen=True)
class Write:
    key: str
    value: str
    writer: str
    kind: str            # correct | echo | conflict | restate
    day: float
    pinned: bool = False
    importance: float = 0.6


@dataclass(frozen=True)
class KeyScenario:
    key: str
    shape: str
    values: Tuple[str, ...]     # authoritative succession, oldest first
    conflict: str               # the other writer's competing value ("" if none)
    writes: Tuple[Write, ...]
    #: For a concurrent-conflict key only: the value written *second*. Which one
    #: the ranking serves is the measurement — the store has no way to know.
    conflict_second: str = ""

    @property
    def current(self) -> str:
        return self.values[-1]

    @property
    def stale(self) -> Tuple[str, ...]:
        return tuple(dict.fromkeys((*self.values[:-1], *( (self.conflict,) if self.conflict else ()))))

    @property
    def has_ground_truth(self) -> bool:
        return self.shape != "concurrent_conflict"


@dataclass
class Scenario:
    seed: int
    keys: Tuple[KeyScenario, ...]

    def scored(self) -> List[KeyScenario]:
        return [ks for ks in self.keys if ks.has_ground_truth]


@dataclass
class KeyResult:
    key: str
    shape: str
    protocol: str
    current_rank: Optional[int] = None
    stale_ranks: Tuple[int, ...] = ()
    served: str = "abstained"          # current | stale | other | abstained
    served_second: bool = False        # conflict keys: did the later write win?
    active_stale: int = 0
    live_values: int = 0
    history_ok: bool = True


@dataclass
class ProtocolResult:
    protocol: str
    keys: List[KeyResult] = field(default_factory=list)

    def scored(self) -> List[KeyResult]:
        return [k for k in self.keys if k.shape != "concurrent_conflict"]

    def conflicts(self) -> List[KeyResult]:
        return [k for k in self.keys if k.shape == "concurrent_conflict"]

    # ── the numbers, over keys with a ground truth ───────────────────────
    @property
    def current_at_1(self) -> float:
        return _mean(r.current_rank == 0 for r in self.scored())

    @property
    def current_at_5(self) -> float:
        return _mean(r.current_rank is not None and r.current_rank < 5 for r in self.scored())

    @property
    def stale_leak_at_5(self) -> float:
        return _mean(any(rank < 5 for rank in r.stale_ranks) for r in self.scored())

    @property
    def stale_above_current(self) -> float:
        return _mean(_stale_above(r) for r in self.scored())

    @property
    def served_current(self) -> float:
        return _mean(r.served == "current" for r in self.scored())

    @property
    def served_stale(self) -> float:
        return _mean(r.served == "stale" for r in self.scored())

    @property
    def abstained(self) -> float:
        return _mean(r.served == "abstained" for r in self.scored())

    @property
    def active_stale_count(self) -> float:
        return _mean_count(r.active_stale for r in self.scored())

    @property
    def history_recoverable(self) -> float:
        return _mean(r.history_ok for r in self.scored())

    @property
    def conflict_live_values(self) -> float:
        return _mean_count(r.live_values for r in self.conflicts())

    @property
    def conflict_served_second(self) -> float:
        return _mean(r.served_second for r in self.conflicts())

    def by_shape(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for shape in SHAPES:
            rows = [r for r in self.keys if r.shape == shape]
            if not rows:
                continue
            grounded = shape != "concurrent_conflict"
            out[shape] = {
                "n": len(rows),
                "ground_truth": grounded,
                "current_at_1": _mean(r.current_rank == 0 for r in rows) if grounded else None,
                "stale_above_current": _mean(_stale_above(r) for r in rows) if grounded else None,
                "served_stale": _mean(
                    (r.served_second if shape == "concurrent_conflict" else r.served == "stale")
                    for r in rows
                ),
                "live_values": _mean_count(r.live_values for r in rows),
            }
        return out

    def as_dict(self) -> Dict[str, Any]:
        return {
            "protocol": self.protocol,
            "scored_keys": len(self.scored()),
            "conflict_keys": len(self.conflicts()),
            "current_at_1": round(self.current_at_1, 4),
            "current_at_5": round(self.current_at_5, 4),
            "stale_leak_at_5": round(self.stale_leak_at_5, 4),
            "stale_above_current": round(self.stale_above_current, 4),
            "served_current": round(self.served_current, 4),
            "served_stale": round(self.served_stale, 4),
            "abstained": round(self.abstained, 4),
            "active_stale_count": round(self.active_stale_count, 4),
            "conflict_live_values": round(self.conflict_live_values, 4),
            "conflict_served_second": round(self.conflict_served_second, 4),
            "history_recoverable": round(self.history_recoverable, 4),
            "by_shape": {k: {m: round(v, 4) if isinstance(v, float) else v for m, v in d.items()}
                         for k, d in self.by_shape().items()},
        }


# ── the corpus ────────────────────────────────────────────────────────────


def build_scenario(*, seed: int, keys: int) -> Scenario:
    """A deterministic corpus, shapes dealt round-robin over the keys."""
    rng = random.Random(seed)
    chosen = list(_KEYS[: max(1, min(keys, len(_KEYS)))])
    rng.shuffle(chosen)
    out: List[KeyScenario] = []
    for index, key in enumerate(chosen):
        shape = SHAPES[index % len(SHAPES)]
        picks = rng.sample(_NOUNS, 4)
        tag = f"{index + 1:02d}"
        v = tuple(f"{verb}-{pick}-{tag}" for verb, pick in zip(("alpha", "bravo", "delta"), picks[:3]))
        conflict = f"charlie-{picks[3]}-{tag}"
        second = ""

        if shape == "succession":
            writes = (
                Write(key, v[0], "atlas", "correct", 0.0),
                Write(key, v[1], "atlas", "correct", 2.0),
                Write(key, v[2], "atlas", "correct", 4.0),
            )
            values, clash = v, ""
        elif shape == "pinned_stale":
            writes = (
                Write(key, v[0], "atlas", "correct", 0.0, pinned=True, importance=0.95),
                Write(key, v[1], "atlas", "correct", 2.0),
            )
            values, clash = v[:2], ""
        elif shape == "rogue_echo":
            writes = (
                Write(key, v[0], "atlas", "correct", 0.0),
                Write(key, v[1], "atlas", "correct", 2.0),
                Write(key, v[0], "birch", "echo", 3.0),
            )
            values, clash = v[:2], ""
        else:  # concurrent_conflict
            # Alternate who writes first. If the served value tracks the order,
            # the answer is insertion order; if it splits, it is arbitrary.
            if index % 2 == 0:
                writes = (
                    Write(key, v[0], "atlas", "correct", 0.0),
                    Write(key, conflict, "birch", "conflict", 0.5),
                )
                second = conflict
            else:
                writes = (
                    Write(key, conflict, "birch", "conflict", 0.0),
                    Write(key, v[0], "atlas", "correct", 0.5),
                )
                second = v[0]
            values, clash = v[:1], conflict

        out.append(
            KeyScenario(
                key=key, shape=shape, values=values, conflict=clash, writes=writes,
                conflict_second=second if shape == "concurrent_conflict" else "",
            )
        )
    return Scenario(seed=seed, keys=tuple(out))


def content_for(write: Write) -> str:
    """The text a writer would store.

    The echo carries the corroborating detail a real note accumulates, so it is
    the better lexical match against the terse correction. That is the failure
    mode this benchmark exists to expose, not a contrivance the other way.
    """
    if write.kind == "echo":
        # The topic named more than once: this is what makes the dead value the
        # better lexical match than the terse correction, which is the whole
        # failure mode. A note that merely added unrelated detail would lose on
        # length normalisation and prove nothing.
        return (
            f"{write.key}: {write.value} — the {write.key} was confirmed in the last "
            f"review; the {write.key} change ticket and runbook are attached."
        )
    if write.kind == "conflict":
        return f"{write.key}: {write.value} (reported by the other agent)."
    return f"{write.key}: {write.value}."


# ── the three write protocols ─────────────────────────────────────────────


def _stamp(write: Write) -> datetime:
    return BASE + timedelta(days=write.day)


def _draft(write: Write) -> MemoryDraft:
    return MemoryDraft(
        content=content_for(write),
        kind="constraint" if write.pinned else "fact",
        domain="Knowledge",
        source="agent",
        author_id=write.writer,
        importance=write.importance,
        pinned=write.pinned,
        status="active",
        valid_from=to_iso(_stamp(write)),
        tags=("multi-writer", write.kind),
    )


def _backdate(conn: sqlite3.Connection, memory_id: str, stamp: datetime) -> None:
    conn.execute(
        "UPDATE memories SET created_at=?, updated_at=? WHERE id=?",
        (to_iso(stamp), to_iso(stamp), memory_id),
    )


def _superseded_contents(conn: sqlite3.Connection, scope: Scope) -> List[str]:
    rows = conn.execute(
        "SELECT content FROM memories WHERE status='superseded' AND scope_profile=?",
        (scope.profile,),
    )
    return [row["content"] for row in rows]


def _value_is_dead(conn: sqlite3.Connection, scope: Scope, value: str) -> bool:
    """Is this value already superseded, regardless of the text carrying it?

    An exact-text check cannot answer this: a re-assertion typically quotes the
    dead value inside *new* prose ("confirmed in the last review, with the
    runbook…"), which is the whole reason it wins a lexical match. The shipped
    read surface for this question is history — ``entropicmem_search`` with
    ``include_history=True`` returns the predecessor rows — so the check is by
    value, over the superseded rows and their version snapshots.
    """
    needle = f"%{value}%"
    if conn.execute(
        "SELECT 1 FROM memories WHERE status='superseded' AND scope_profile=? AND content LIKE ? LIMIT 1",
        (scope.profile, needle),
    ).fetchone():
        return True
    # Version snapshots only count for a *retired* row: every live memory also
    # owns a version row carrying its current text, which would make the check
    # answer yes for the value that is live right now.
    return conn.execute(
        "SELECT 1 FROM memory_versions v JOIN memories m ON m.id = v.memory_id"
        " WHERE m.status IN ('superseded','deleted') AND v.content LIKE ? LIMIT 1",
        (needle,),
    ).fetchone() is not None


def apply_writes(store: Store, scenario: Scenario, protocol: str) -> None:
    """Write the whole corpus through one protocol, in timeline order."""
    if protocol not in PROTOCOLS:
        raise ValueError(f"unknown protocol {protocol!r}")
    scope = Scope(profile=PROFILE)
    current: Dict[str, str] = {}
    with store.transaction() as conn:
        memories = MemoryStore(conn)
        for ks in scenario.keys:
            for write in sorted(ks.writes, key=lambda w: w.day):
                stamp = _stamp(write)
                if write.kind == "correct":
                    target = current.get(ks.key) if protocol != "append" else None
                    if target:
                        result = memories.supersede(
                            target, _draft(write), scope=scope,
                            actor=write.writer, reason="corrected",
                        )
                    else:
                        result = memories.add(_draft(write), scope=scope, actor=write.writer)
                    if result.ok:
                        current[ks.key] = result.id
                        _backdate(conn, result.id, stamp)
                    continue

                if protocol == "supersede_guard":
                    # The caller-side check, using only the shipped read
                    # surface: a value that is already superseded is dead, so a
                    # write re-asserting it is not written, whatever prose it
                    # arrives in.
                    if _value_is_dead(conn, scope, write.value):
                        continue

                result = memories.add(_draft(write), scope=scope, actor=write.writer)
                if result.ok and result.decision == "created":
                    _backdate(conn, result.id, stamp)


# ── scoring ───────────────────────────────────────────────────────────────


def _ranked_rows(
    conn: sqlite3.Connection, scope: Scope, query: str, *, gate: bool, now: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    # ``now`` is pinned to the scenario clock: the wall clock would age every row
    # past the standard half-life floor and flatten the recency term, which is
    # one of the two mechanisms under test.
    outcome = retrieve(conn, scope=scope, query=query, with_gate=gate, now=now)
    memories = MemoryStore(conn)
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for ranking in outcome.rankings:
        if getattr(ranking, "owner_type", "") != OWNER_TYPE_MEMORY:
            continue
        if ranking.owner_id in seen:
            continue
        row = memories.get(ranking.owner_id, scope=scope)
        if row is None or row["status"] == "deleted":
            continue
        seen.add(ranking.owner_id)
        rows.append(row)
    return rows


def _first_index(rows: Sequence[Dict[str, Any]], value: str) -> Optional[int]:
    for index, row in enumerate(rows):
        if value in row["content"]:
            return index
    return None


def _stale_above(result: KeyResult) -> bool:
    if not result.stale_ranks:
        return False
    if result.current_rank is None:
        return True
    return min(result.stale_ranks) < result.current_rank


def score_key(conn: sqlite3.Connection, ks: KeyScenario, *, protocol: str) -> KeyResult:
    scope = Scope(profile=PROFILE)
    query = f"what is the {ks.key}?"
    now = BASE + timedelta(days=ASK_AFTER_DAYS)
    ranked = _ranked_rows(conn, scope, query, gate=False, now=now)
    served_rows = _ranked_rows(conn, scope, query, gate=True, now=now)

    result = KeyResult(key=ks.key, shape=ks.shape, protocol=protocol)
    result.current_rank = _first_index(ranked, ks.current)
    result.stale_ranks = tuple(
        index for index, row in enumerate(ranked)
        if any(value in row["content"] for value in ks.stale)
    )

    result.served_second = bool(
        ks.conflict_second and served_rows and ks.conflict_second in served_rows[0]["content"]
    )
    if not served_rows:
        result.served = "abstained"
    elif ks.current in served_rows[0]["content"]:
        result.served = "current"
    elif any(value in served_rows[0]["content"] for value in ks.stale):
        result.served = "stale"
    else:
        result.served = "other"

    active_texts = [
        row["content"] for row in conn.execute(
            "SELECT content FROM memories WHERE status='active' AND scope_profile=?",
            (scope.profile,),
        )
    ]
    result.active_stale = sum(
        1 for value in ks.stale if any(value in text for text in active_texts)
    )
    candidates = (ks.current, *ks.stale)
    result.live_values = sum(1 for value in candidates if any(value in text for text in active_texts))

    superseded = _superseded_contents(conn, scope)
    versions = conn.execute(
        "SELECT content FROM memory_versions WHERE content LIKE ?", (f"%{ks.values[0]}%",)
    ).fetchall()
    result.history_ok = (
        any(ks.values[0] in text for text in superseded)
        or any(ks.values[0] in row["content"] for row in versions)
        or any(ks.values[0] in text for text in active_texts)
    )
    return result


def run_protocol(scenario: Scenario, protocol: str) -> ProtocolResult:
    """Fresh store, same corpus, one protocol; then score every key."""
    with tempfile.TemporaryDirectory(prefix="em-mw-eval-") as tmp:
        store = Store(str(Path(tmp) / "memory.db"))
        try:
            with store.writer() as conn:
                migrate(conn)
            apply_writes(store, scenario, protocol)
            conn = store.reader()
            result = ProtocolResult(protocol=protocol)
            for ks in scenario.keys:
                result.keys.append(score_key(conn, ks, protocol=protocol))
            return result
        finally:
            store.close()


def run(*, seed: int = 60828, keys: int = 12) -> Dict[str, Any]:
    scenario = build_scenario(seed=seed, keys=keys)
    results = [run_protocol(scenario, protocol) for protocol in PROTOCOLS]
    return {
        "seed": seed,
        "keys": len(scenario.keys),
        "shapes": list(shapes_present(scenario)),
        "ask_after_days": ASK_AFTER_DAYS,
        "protocols": [result.as_dict() for result in results],
    }


def shapes_present(scenario: Scenario) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(ks.shape for ks in scenario.keys))


def _mean(values: Iterable[bool]) -> float:
    items = list(values)
    return (sum(1 for item in items if item) / len(items)) if items else 0.0


def _mean_count(values: Iterable[int]) -> float:
    items = list(values)
    return (sum(items) / len(items)) if items else 0.0


def render_markdown(payload: Dict[str, Any]) -> str:
    """The table a reader can check at a glance. Ratios, not percentages."""
    columns = (
        ("current@1", "current_at_1"),
        ("current@5", "current_at_5"),
        ("stale leak@5", "stale_leak_at_5"),
        ("stale > current", "stale_above_current"),
        ("served: current", "served_current"),
        ("served: stale", "served_stale"),
        ("abstained", "abstained"),
        ("active stale (n)", "active_stale_count"),
        ("conflict live (n)", "conflict_live_values"),
        ("history kept", "history_recoverable"),
    )
    head = "| protocol | " + " | ".join(label for label, _ in columns) + " |"
    rule = "|---" * (len(columns) + 1) + "|"
    lines = [head, rule]
    for row in payload["protocols"]:
        cells = " | ".join(f"{row[key]:.2f}" for _, key in columns)
        lines.append(f"| `{row['protocol']}` | {cells} |")

    lines += [
        "",
        "| shape | protocol | current@1 | stale > current | served: other writer | live values |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["protocols"]:
        for shape, values in row["by_shape"].items():
            current = f"{values['current_at_1']:.2f}" if values["ground_truth"] else "—"
            above = f"{values['stale_above_current']:.2f}" if values["ground_truth"] else "—"
            lines.append(
                f"| {shape} | `{row['protocol']}` | {current} | {above} | "
                f"{values['served_stale']:.2f} | {values['live_values']:.2f} |"
            )
    return "\n".join(lines)
