"""The v3 **shadow read** (P0) — exercise S3 on real turns without committing the store.

The cutover is deferred until the provider reads through S3, but a v3 read path only
exists once the store *is* v3 (engine selection is by ``PRAGMA user_version``). The
shadow is the way out of that circle: **the turn is served by v2 exactly as today**,
and S3 runs afterwards, off the turn path, over a **v3 copy**, writing a divergence
line. Nothing about the live store, its schema, or the served answer changes.

What this module guarantees, and how each is checked rather than asserted:

* **The flag is off by default.** ``ENTROPICMEM_SHADOW_V3`` unset means this module
  does nothing at all.
* **The served response is untouched when the flag is on.** The provider's
  ``_spawn_shadow`` runs *after* the response is built, and it is submitted to a
  background thread; a test blocks that thread on an event and asserts the response
  still returns, which is a proof rather than an inspection.
* **The live store is never written** (repo rule 3). The refresh reads it with a
  read-only connection and writes only the copy.

**Two biases this design cannot remove, so every line states them:**

* ``copy_age_s`` — the copy **lags**. A stale copy makes v3 look *less* diverged than
  it is, so **divergence here is a lower bound**, and it will read as "v3 is fine"
  when the truth is "the copy is old". The age is on every line, and ``stale`` marks
  the lines that exceed the bound.
* v3 scores today are **lexical, entity and episodic only** — no vector generator and
  no cosine support condition until EM-303. Divergence numbers are therefore **not**
  an apples-to-apples quality comparison against v2, and the line says so.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: Points at the **v3 copy** the shadow reads. Unset (the default) disables the shadow.
SHADOW_ENV = "ENTROPICMEM_SHADOW_V3"
#: Where divergence lines go. Defaults beside the copy.
LOG_ENV = "ENTROPICMEM_SHADOW_LOG"

#: A copy older than this is refreshed before use, and the line that used a stale one
#: is marked. 15 minutes is a bound, not a target: each refresh re-runs the migration.
MAX_COPY_AGE_S = 900.0

_DEFAULT_DIR = "entropicmem-shadow"

#: What a divergence report must carry, because neither bias can be designed away.
CAVEAT = (
    "v3 scores are lexical/entity/episodic only (no vectors or cosine until EM-303), "
    "and divergence is a LOWER BOUND because the copy lags"
)

#: The promotion observable, **fixed before any data is collected** so the threshold
#: cannot be chosen to fit the sample.
#:
#: **Amended by owner ruling on 2026-10-08 — before a single real turn was read**, which
#: is the only circumstance in which amending a frozen observable is not fitting it to the
#: data. The ruling, in its own terms: the old ``max_divergence_rate`` was **symmetric**,
#: so "v3 dropped a hit v2 had" (a recall regression) counted exactly like "v3 invented a
#: hit" (a fabrication). A measured 240-turn sample was **150 misses and 0 additions**, so
#: the gate failed on the metric the observable itself calls decisive, for a reason that is
#: not a safety failure — the wrong promotion criterion, and one that would block a better
#: engine. So: fabrication stays a hard ceiling; the miss side gets its own, pre-registered
#: ceiling, **armed 2026-10-08 from EM-306's holdout**.
PROMOTION: Dict[str, Any] = {
    "min_turns": 200,
    "max_copy_age_s": MAX_COPY_AGE_S,
    # Hard and non-negotiable: v3 must never inject a memory v2 did not. A
    # correctness/safety property, not a tuning knob.
    "max_v3_only": 0,
    # Ids v3 dropped / ids v2 injected. **ARMED 2026-10-08** at the pre-registered
    # reference — 1 - recall@5 of the v2 adapter on EM-306's holdout split; see
    # MISS_CEILING_RULE and evals/results/tune-hard-4eb8097.json. ``None`` remains the
    # shape of an un-armed ceiling, and the report still reads it loudly.
    "max_v2_miss_rate": 0.107143,
    "max_p95_shadow_ms": 150.0,    # §4.2's warm prefetch budget, off-turn
}

#: How ``max_v2_miss_rate`` was armed. **Pre-registered 2026-10-08, before any real turn
#: was read**, so the number could not be chosen after seeing the sample — which is the
#: whole reason the observable is frozen in code.
#:
#: The owner's ruling allowed either an absolute miss rate with a stated rationale, or
#: "the miss rate must not exceed v2's own miss rate against a held-out reference". The
#: relative form is the one registered here: no defensible absolute number existed before
#: real turns, and this one is computable from artifacts that already existed — and it
#: cannot be fitted to the shadow sample, because it is measured on a different dataset.
#:
#: **Corrected and then armed, 2026-10-08, still before any real turn was read:** the
#: first draft said "measured over the same corpus the shadow sample is drawn from",
#: which is a category error — the bound is measured on the eval holdout, the shadow's
#: rate on real turns. The rule names the two quantities and says the relationship is a
#: policy choice; the value came from EM-306's holdout the day that holdout existed.
MISS_CEILING_RULE = (
    f"max_v2_miss_rate is ARMED at {PROMOTION['max_v2_miss_rate']} — 1 - recall@5 of "
    "the v2 adapter on EM-306's holdout split (evals/results/tune-hard-4eb8097.json). "
    "It was pre-registered 2026-10-08 before any real turn was read, and armed the same "
    "day the holdout existed. This is a policy choice, not an identity: the miss rate it "
    "gates is v3-vs-v2 (ids v3 dropped that v2 injected, over ids v2 injected, on real "
    "turns), while the bound is v2-vs-truth (what v2 itself missed against the held-out "
    "reference); applying the second to the first says only 'v3 may drop no more of v2's "
    "hits than v2 itself misses against truth'. Do not re-arm it from a synthetic "
    "sample: that is evidence about the metric, not about turns."
)

_ID_RE = re.compile(r"^- \[([^\]]+)\]", re.MULTILINE)


def injected_ids(block: str) -> List[str]:
    """Ids of the bullets in a rendered block — the same shape `evals.runner` reads."""
    return _ID_RE.findall(block or "")


def shadow_path() -> Optional[Path]:
    """The v3 copy to read, or ``None`` when the shadow is off (the default)."""
    raw = os.environ.get(SHADOW_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def log_path() -> Path:
    raw = os.environ.get(LOG_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    base = shadow_path()
    parent = base.parent if base is not None else Path(tempfile.gettempdir()) / _DEFAULT_DIR
    return parent / "divergence.jsonl"


def copy_age_s(path: Path) -> Optional[float]:
    """Seconds since the copy was written, or ``None`` when there is no copy yet."""
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def refresh(live_db: str | Path, shadow_db: Path) -> None:
    """Refresh the copy from the live store, then migrate it (§3.3's real path).

    **The live store is opened read-only and never written**; only the copy is.
    ``sqlite3.Connection.backup`` is the online-copy primitive, so a concurrent
    writer on the live store is fine.

    The copy is migrated rather than trusted, which means the shadow exercises the
    *migration* on every refresh — the same code the real cutover runs, on
    throwaway data, long before the cutover happens.
    """
    from em.store.db import open_db
    from em.store.migrations import migrate

    shadow_db.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{live_db}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(str(shadow_db))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    connection = open_db(shadow_db)
    try:
        migrate(connection)
    finally:
        connection.close()


def comparison_ids(conn: sqlite3.Connection, ids: Sequence[str]) -> List[str]:
    """Map v3 ids onto the ids **v2 knows**, so the two sets are comparable.

    The two stacks name the same memory differently: v2 uses the 16-hex content id and
    v3 uses a ``mem_…`` ULID, keeping the v2 id in ``legacy_id`` — which is exactly what
    that column is for. Comparing raw ids therefore marks **every** memory as a
    divergence, reports "v3 fabricated a hit" on every line, and would trip the
    ``v3_only == 0`` promotion condition on the first day. The comparison id is
    ``COALESCE(legacy_id, id)``: a migrated row compares by the id v2 already uses, and
    a row written straight to v3 keeps its own, so it still reads as v3-only.

    Discovered by running the shadow end to end against a real migrated store; the unit
    tests passed while every real line would have been meaningless.
    """
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return []
    marks = ",".join("?" for _ in wanted)
    try:
        rows = conn.execute(
            f"SELECT id, COALESCE(legacy_id, id) AS comparison FROM memories"
            f" WHERE id IN ({marks})",
            wanted,
        ).fetchall()
        mapping = {row["id"]: row["comparison"] for row in rows}
    except sqlite3.Error:
        return wanted
    return [mapping.get(item, item) for item in wanted]


def shadow_ids(shadow_db: Path, *, profile: str, query: str) -> List[str]:
    """Run S3 over the copy and return the injected ids, mapped for comparison."""
    from em.retrieval.pipeline import retrieve
    from em.store.db import Store
    from em.store.types import Scope

    store = Store(str(shadow_db))
    try:
        connection = store.reader()
        outcome = retrieve(
            connection, scope=Scope(profile=profile or "default"), query=query, with_gate=True
        )
        return comparison_ids(connection, outcome.ids)
    finally:
        store.close()


def run(
    live_db: str | Path,
    *,
    profile: str,
    query: str,
    v2_ids: Sequence[str],
    now: Optional[datetime] = None,
    destination: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Refresh-or-reuse the copy, run S3 over it, and append one divergence line.

    Returns the line, or ``None`` when the shadow is off or failed. **Never raises**:
    a diagnostic that can break a turn is worse than no diagnostic.
    """
    target = shadow_path()
    if target is None:
        return None

    started = time.perf_counter()
    try:
        age = copy_age_s(target)
        refreshed = age is None or age > MAX_COPY_AGE_S
        if refreshed:
            refresh(live_db, target)
            age = 0.0
        v3_ids = shadow_ids(target, profile=profile, query=query)
    except Exception as exc:  # noqa: BLE001 - a shadow must never break a turn
        logger.debug("EntropicMem v3 shadow failed: %s", exc)
        return None

    moment = now or datetime.now(timezone.utc)
    line: Dict[str, Any] = {
        "ts": moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "query": (query or "")[:200],
        "v2_ids": list(v2_ids),
        "v3_ids": v3_ids,
        "divergence": sorted(set(v2_ids) ^ set(v3_ids)),
        "v3_only": sorted(set(v3_ids) - set(v2_ids)),
        # The staleness bound travels with every number, so a stale copy cannot be
        # read as agreement.
        "copy_age_s": round(age, 1),
        "copy_refreshed": refreshed,
        "stale": age > MAX_COPY_AGE_S,
        "shadow_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "caveat": CAVEAT,
    }
    _append(line, destination or log_path())
    return line


def _append(line: Dict[str, Any], destination: Path) -> None:
    """Best-effort JSONL append: one line per turn, and never fatal."""
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        logger.debug("EntropicMem shadow log write failed: %s", exc)


# --- P0c: reading the collected data --------------------------------------
#
# The observable above was frozen *before* any data was collected, and amended once —
# by owner ruling on 2026-10-08, still before a single real turn was read, which is the
# only circumstance in which amending it is not fitting it to the sample. The readout has
# one job: apply those numbers and show the distribution around them. The rules that make
# a green light mean something live here, next to the thresholds they use, so the two
# cannot drift apart:
#
# * **Thresholds are read from ``PROMOTION`` at report time.** Nothing is copied into a
#   literal; tightening or loosening the observable changes what the readout says.
# * **Fabrication and misses are separate ceilings** (the 2026-10-08 ruling). ``v3_only``
#   is hard: v3 inventing a memory v2 did not have is a correctness failure. The miss rate
#   is a recall regression, gated only once **armed** — and while it is un-armed it is
#   *reported and announced as ungated*, so a reading can never imply it was checked.
# * **A violation outranks a short sample.** One fabricated hit in three turns is
#   ``not met``, not ``cannot conclude`` — a reading must never dissolve a failure
#   into "we need more data".
# * **A short, unreadable or no-signal sample is never ``met``.** An empty store makes
#   v2 and v3 both inject nothing, so a naive rate is 0% and the whole observable would
#   read as passed on a sample that measured nothing.
# * **The writer's own fields are cross-checked**, not trusted blindly: ``stale``
#   against the frozen bound, ``divergence``/``v3_only`` against the ids on the line.
#   Disagreement means the two ends of the pipeline stopped agreeing, and that is a
#   reading to refuse, not a reading to average over.
# * **Line numbers, not query text.** The log holds the user's question; a report is
#   something you paste to an agent or a ticket.

#: The keys a line must carry to be usable at all. A line missing one is *counted*,
#: never dropped: a truncated log that reads as clean is worse than no reading.
_REQUIRED_KEYS = (
    "ts", "v2_ids", "v3_ids", "divergence", "v3_only", "copy_age_s", "stale", "shadow_ms",
)

#: Conditions that measure the *system*: failing one is a finding.
_BEHAVIOURAL = ("copy_within_bound", "v2_miss_rate", "v3_only_never", "p95_within_budget")


def _number(value: Any) -> bool:
    """True for a real number. ``bool`` is an ``int`` subclass, and a flag in a
    numeric slot is a schema change, not a measurement."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def percentile(values: Sequence[float], p: float) -> Optional[float]:
    """Nearest-rank percentile, the same reading `evals.metrics` uses.

    Nearest-rank with a small sample picks a real sample rather than inventing one
    between two, which is what makes ``p50``/``p95``/``max`` readable together: one
    stray slow turn with a low p50 is a noisy runner, and this says so.
    """
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(-(-p / 100.0 * len(ordered)) // 1) - 1))
    return float(ordered[index])


def evaluate(lines: Sequence[Any], *, log: str = "") -> Dict[str, Any]:
    """Score one shadow sample against ``PROMOTION`` — no I/O, no writes.

    ``lines`` are parsed JSONL objects in file order; anything that is not a usable
    line is counted as malformed and keeps its position, so citations stay the line
    numbers a reader will find in the file.
    """
    thresholds = dict(PROMOTION)
    usable: List[tuple] = []
    unreadable: List[int] = []
    for position, item in enumerate(lines, start=1):
        if not isinstance(item, dict) or not all(key in item for key in _REQUIRED_KEYS):
            unreadable.append(position)
            continue
        if not _number(item["copy_age_s"]) or not _number(item["shadow_ms"]):
            unreadable.append(position)
            continue
        if not isinstance(item["v2_ids"], list) or not isinstance(item["v3_ids"], list):
            unreadable.append(position)
            continue
        usable.append((position, item))
    malformed = len(unreadable)

    reasons: List[str] = []
    conditions: Dict[str, Dict[str, Any]] = {}
    turns = len(usable)

    # 1. enough turns to be worth reading (sufficiency, not behaviour).
    floor = float(thresholds["min_turns"])
    conditions["min_turns"] = {
        "kind": "sufficiency",
        "value": turns,
        "floor": floor,
        "verdict": "met" if turns >= floor else "not met",
    }

    # 2. the copy was inside its staleness bound on every line used.
    bound = float(thresholds["max_copy_age_s"])
    ages = [float(item["copy_age_s"]) for _, item in usable]
    beyond = [position for position, item in usable if float(item["copy_age_s"]) > bound]
    flagged = sum(1 for _, item in usable if bool(item["stale"]))
    disagree = sorted(
        position for position, item in usable if bool(item["stale"]) != (float(item["copy_age_s"]) > bound)
    )
    if disagree:
        reasons.append(
            f"the writer's own stale flag disagrees with the {bound:.0f} s bound on "
            f"{len(disagree)} line(s): {disagree[:10]}"
        )
    conditions["copy_within_bound"] = {
        "kind": "behavioural",
        "value": (max(ages) if ages else None),
        "ceiling": bound,
        "p95": percentile(ages, 95),
        "beyond_lines": beyond[:10],
        "stale_lines": flagged,
        "verdict": ("no signal" if not ages else
                    "not met" if (beyond or disagree) else "met"),
    }

    # 3. the two halves the owner's ruling separated: what v3 **missed** (a recall
    #    regression, gated only once armed) and what v3 **fabricated** (condition 4, a
    #    safety property, always hard). The retired symmetric rate is still computed, as
    #    context, so an earlier reading stays comparable.
    injections = [(position, item) for position, item in usable if item["v2_ids"]]
    diverged = [(position, item) for position, item in injections if item["divergence"]]
    inconsistent = sorted(
        position
        for position, item in usable
        if sorted(set(item["divergence"] or [])) != sorted(set(item["v2_ids"]) ^ set(item["v3_ids"]))
        or sorted(set(item["v3_only"] or [])) != sorted(set(item["v3_ids"]) - set(item["v2_ids"]))
    )
    if inconsistent:
        reasons.append(
            f"inconsistent lines: the recorded divergence/v3_only disagree with the ids on "
            f"{len(inconsistent)} line(s): {inconsistent[:10]}"
        )

    #: Id-level miss rate: ids v3 dropped, over ids v2 injected. Id-level rather than
    #: turn-level because a turn where v3 kept 1 of 3 is a smaller failure than one where
    #: it kept 0 of 3, and the turn-level fraction is reported beside it.
    missed = [(position, item) for position, item in injections
              if set(item["v2_ids"]) - set(item["v3_ids"])]
    injected_ids = sum(len(set(item["v2_ids"])) for _, item in usable)
    missed_ids = sum(len(set(item["v2_ids"]) - set(item["v3_ids"])) for _, item in usable)
    miss_rate = (missed_ids / injected_ids) if injected_ids else None
    miss_ceiling = thresholds["max_v2_miss_rate"]
    armed = _number(miss_ceiling)
    if miss_rate is None:
        miss_verdict = "no signal"
    elif not armed:
        miss_verdict = "not armed"
    elif inconsistent or miss_rate > float(miss_ceiling):
        miss_verdict = "not met"
    else:
        miss_verdict = "met"
    conditions["v2_miss_rate"] = {
        "kind": "behavioural",
        "value": miss_rate,
        "ceiling": (float(miss_ceiling) if armed else None),
        "armed": armed,
        "missed_ids": missed_ids,
        "injected_ids": injected_ids,
        "turns_with_injection": len(injections),
        "turns_with_a_miss": len(missed),
        "missed_lines": [position for position, _ in missed][:10],
        "verdict": miss_verdict,
    }
    if miss_rate is None:
        reasons.append(
            "v2_miss_rate: no signal — v2 injected no ids at all in this sample, so the "
            "rate has no denominator and nothing can be concluded from it"
        )
    elif not armed:
        reasons.append(f"v2_miss_rate is reported but NOT GATED: {MISS_CEILING_RULE}")

    # 4. v3 must never inject what v2 did not.
    ceiling = int(thresholds["max_v3_only"])
    fabrications = [position for position, item in usable if item["v3_only"]]
    conditions["v3_only_never"] = {
        "kind": "behavioural",
        "value": len(fabrications),
        "ceiling": ceiling,
        "lines": fabrications[:20],
        "ids": sorted({one for _, item in usable for one in (item["v3_only"] or [])})[:20],
        "verdict": "met" if len(fabrications) <= ceiling else "not met",
    }
    if fabrications:
        reasons.append(
            f"v3 injected something v2 did not on {len(fabrications)} line(s) — the failure "
            f"the observable treats as decisive"
        )

    # 5. the off-turn cost, against §4.2's warm prefetch budget.
    costs = [float(item["shadow_ms"]) for _, item in usable]
    p95 = percentile(costs, 95)
    budget = float(thresholds["max_p95_shadow_ms"])
    conditions["p95_within_budget"] = {
        "kind": "behavioural",
        "value": p95,
        "ceiling": budget,
        "p50": percentile(costs, 50),
        "max": (max(costs) if costs else None),
        "verdict": ("no signal" if p95 is None else "met" if p95 <= budget else "not met"),
    }

    for name, condition in conditions.items():
        if condition["verdict"] == "not met" and name != "min_turns":
            reasons.append(f"{name}: {condition['verdict']}")
    if turns < floor:
        reasons.append(f"only {turns} usable turn(s) of the {floor:.0f} the observable needs")
    if malformed:
        reasons.append(f"{malformed} line(s) were unreadable and are excluded from every number")

    # Margin, on every condition: how much room was left before it would have failed
    # (negative once it has). A pass with no margin shown is a green light the owner
    # cannot read the meaning of. An **un-armed** ceiling has no margin, because it
    # gates nothing — showing one would imply a limit that is not in force.
    for condition in conditions.values():
        value = condition.get("value")
        if _number(condition.get("ceiling")) and _number(value):
            condition["margin"] = round(float(condition["ceiling"]) - float(value), 6)
        elif _number(condition.get("floor")) and _number(value):
            condition["margin"] = round(float(value) - float(condition["floor"]), 6)

    # Findings: the first few concrete cases behind each failure, with line numbers and
    # ids only — never the question that produced them.
    findings = {
        "misses": [
            {"line": position, "v2_ids": list(item["v2_ids"]), "v3_ids": list(item["v3_ids"])}
            for position, item in missed[:10]
        ],
        "v3_only": [
            {"line": position, "v3_only": list(item["v3_only"])}
            for position, item in usable
            if item["v3_only"]
        ][:10],
        "stale": [
            {"line": position, "copy_age_s": float(item["copy_age_s"])}
            for position, item in usable
            if float(item["copy_age_s"]) > bound or bool(item["stale"])
        ][:10],
        "unreadable": unreadable[:10],
    }

    statuses = {name: condition["verdict"] for name, condition in conditions.items()}
    if any(statuses[name] == "not met" for name in _BEHAVIOURAL):
        verdict = "not met"
    elif (
        statuses["min_turns"] != "met"
        or malformed
        or "no signal" in statuses.values()
        # An un-armed ceiling is a declared dimension that is not being measured. It
        # blocks `met` on purpose: the owner's ruling was to report misses and say
        # explicitly that they are ungated, not to let a pass imply they were checked.
        or "not armed" in statuses.values()
        or disagree
        or inconsistent
    ):
        verdict = "cannot conclude"
    else:
        verdict = "met"

    return {
        "log": log,
        "sample": {
            "lines": len(lines),
            "usable": turns,
            "malformed": malformed,
            "first_ts": (usable[0][1]["ts"] if usable else None),
            "last_ts": (usable[-1][1]["ts"] if usable else None),
        },
        "thresholds": thresholds,
        "arming_rule": MISS_CEILING_RULE,
        "conditions": conditions,
        "context": {
            # Shown so a reader can see what each definition costs. The verdict uses only
            # the id-level miss rate and the hard fabrication ceiling above.
            "divergence_rate_symmetric": (
                (len(diverged) / len(injections)) if injections else None
            ),
            "divergence_over_all_lines": (
                len([1 for _, item in usable if item["divergence"]]) / turns if turns else None
            ),
            "turns_with_injection": len(injections),
            "turns_abstaining": turns - len(injections),
            # The decomposition that the 2026-10-08 ruling acted on: a miss and an
            # addition are opposite failures, and the retired symmetric ceiling counted
            # them alike. Kept in every report so the two readings stay comparable —
            # the earlier 37.5% finding was 150 misses and 0 additions.
            "divergence_shape": {
                "v3_missed": missed_ids,
                "v3_added": sum(len(item["v3_only"] or []) for _, item in usable),
            },
        },
        "distribution": {
            "shadow_ms": {"p50": percentile(costs, 50), "p95": p95,
                          "max": (max(costs) if costs else None)},
            "copy_age_s": {"p50": percentile(ages, 50), "p95": percentile(ages, 95),
                           "max": (max(ages) if ages else None)},
            "ids_per_turn": {
                "v2_max": max((len(item["v2_ids"]) for _, item in usable), default=0),
                "v3_max": max((len(item["v3_ids"]) for _, item in usable), default=0),
            },
        },
        "findings": findings,
        "caveat": CAVEAT,
        "verdict": verdict,
        "reasons": reasons,
    }


def read_log(path: Path) -> List[Any]:
    """Parse the JSONL the writer appends. Blank lines are skipped; everything else
    is handed to :func:`evaluate`, which decides what is a usable line."""
    lines: List[Any] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            try:
                lines.append(json.loads(raw))
            except ValueError:
                lines.append(raw.rstrip("\n"))
    return lines


def report(path: Path) -> Dict[str, Any]:
    """Read one divergence log and score it. **Read-only** — the log is evidence."""
    return evaluate(read_log(path), log=str(path))


def _format_rate(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100.0:.2f}%"


def _format_number(value: Any, unit: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int) or float(value).is_integer() and abs(value) >= 100:
        return f"{int(value)}{unit}"
    return f"{float(value):.2f}{unit}"


def render(result: Dict[str, Any]) -> str:
    """The human reading. Every number travels with its bound, its margin and the
    two caveats that make it a lower bound rather than a verdict on quality."""
    conditions = result["conditions"]
    sample_info = result["sample"]
    out: List[str] = [
        "EntropicMem v3 shadow — promotion observable report",
        f"log: {result['log'] or '(not a file)'}",
        (
            f"sample: {sample_info['lines']} line(s), {sample_info['usable']} usable, "
            f"{sample_info['malformed']} unreadable"
        ),
        f"window: {sample_info['first_ts']} .. {sample_info['last_ts']}",
        "",
    ]

    def label(name: str) -> str:
        return {
            "min_turns": "turns collected",
            "copy_within_bound": "copy staleness",
            "v3_only_never": "fabrication (v3-only)",
            "v2_miss_rate": "v3 miss rate",
            "p95_within_budget": "off-turn p95",
        }[name]

    for name in ("min_turns", "copy_within_bound", "v3_only_never", "v2_miss_rate",
                 "p95_within_budget"):
        condition = conditions[name]
        if name == "min_turns":
            detail = f"{condition['value']} collected / {condition['floor']:.0f} needed"
        elif name == "copy_within_bound":
            detail = (
                f"max age {_format_number(condition['value'], ' s')} / bound "
                f"{condition['ceiling']:.0f} s, stale lines {condition['stale_lines']}"
            )
        elif name == "v2_miss_rate":
            detail = (
                f"{_format_rate(condition['value'])} "
                f"({condition['missed_ids']} of {condition['injected_ids']} ids v2 injected; "
                f"{condition['turns_with_a_miss']} of {condition['turns_with_injection']} turns)"
                f" / ceiling "
                + (_format_rate(condition["ceiling"]) if condition["armed"] else "NOT ARMED")
            )
        elif name == "v3_only_never":
            detail = (
                f"{condition['value']} line(s) / ceiling {condition['ceiling']}"
                + (f", at line {condition['lines'][0]}" if condition["lines"] else "")
                + (", ids " + ", ".join(condition["ids"][:5]) if condition["ids"] else "")
            )
        else:
            detail = (
                f"p50 {_format_number(condition['p50'], ' ms')} / p95 "
                f"{_format_number(condition['value'], ' ms')} / max "
                f"{_format_number(condition['max'], ' ms')} / ceiling "
                f"{condition['ceiling']:.0f} ms"
            )
        out.append(f"[{condition['verdict']}] {label(name)}: {detail}")
        if "margin" in condition:
            room = (
                f"{condition['margin'] * 100.0:+.2f} pts"
                if name == "v2_miss_rate"
                else _format_number(condition["margin"])
            )
            out.append(f"    margin: {room} before the limit")
        if name == "v2_miss_rate":
            out.append(f"    lower bound and not apples-to-apples: {result['caveat']}")
            if not condition["armed"]:
                # The ungated dimension announces itself on every reading, so a report
                # can never be skimmed as "all five conditions passed".
                out.append(f"    pre-registered arming rule: {result['arming_rule']}")
        if name == "v3_only_never":
            out.append("    hard ceiling: a fabricated hit is a correctness failure, not a tuning one")

    findings = result.get("findings", {})
    lines_out: List[str] = []
    for kind in ("v3_only", "misses", "stale", "unreadable"):
        for entry in findings.get(kind, [])[:5]:
            if kind == "misses":
                lines_out.append(
                    f"    line {entry['line']}: v2 {entry['v2_ids']} vs v3 {entry['v3_ids']}"
                )
            elif kind == "v3_only":
                lines_out.append(f"    line {entry['line']}: injected {entry['v3_only']}")
            elif kind == "stale":
                lines_out.append(f"    line {entry['line']}: copy age {entry['copy_age_s']} s")
            else:
                lines_out.append(f"    line {entry}: unreadable")
    if lines_out:
        out += ["", "findings (ids and line numbers only — no question text):"] + lines_out

    context = result["context"]
    shape = context.get("divergence_shape", {})
    out += [
        "",
        f"context: retired symmetric divergence {_format_rate(context['divergence_rate_symmetric'])}"
        f" over injected turns ({_format_rate(context['divergence_over_all_lines'])} over all"
        f" lines), {context['turns_with_injection']} turns injected, "
        f"{context['turns_abstaining']} abstained",
        (
            f"shape: v3 missed {shape.get('v3_missed', 0)} id(s) v2 injected, added "
            f"{shape.get('v3_added', 0)} it did not — misses gate only when armed, "
            "additions never do"
        ),
        f"verdict: {result['verdict'].upper()}",
    ]
    if result["reasons"]:
        out.append("why: " + "; ".join(result["reasons"]))
    return "\n".join(out)


_COLLECTION_HINT = (
    "Collection is off unless the host runs the provider with "
    f"{SHADOW_ENV}=<path to a v3 copy>; the log defaults beside it "
    f"({LOG_ENV} overrides). The copy is refreshed and migrated on use, and the live "
    "store is only ever read."
)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`python _shadow.py report [--log PATH] [--json]` — 0 met, 1 not met, 2 inconclusive."""
    import argparse

    parser = argparse.ArgumentParser(prog="em-shadow", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    show = sub.add_parser("report", help="score a divergence log against the observable")
    show.add_argument("--log", default=None, help="divergence.jsonl to read (default: the configured log)")
    show.add_argument("--json", action="store_true", help="print the report as JSON")
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    if arguments.command != "report":
        parser.print_help()
        return 2

    path = Path(arguments.log).expanduser() if arguments.log else log_path()
    if not path.is_file():
        print(f"No divergence log at {path}.")
        print(_COLLECTION_HINT)
        return 2

    try:
        result = report(path)
    except OSError as exc:
        print(f"Could not read {path}: {exc}")
        return 2

    print(json.dumps(result, indent=2) if arguments.json else render(result))
    return {"met": 0, "not met": 1}.get(result["verdict"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
