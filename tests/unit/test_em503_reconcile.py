"""EM-503 — reconciliation and the commit policy (§3.7 steps 2-3).

The card's acceptance criteria, one group each: the rule path decides
`update` and `contradiction` cases at **≥ 0.9**; `UPDATE`/`SUPERSEDE` write a
version row (no memory is overwritten without one); every decision appends an
audit record; and the commit policy keeps an uncertain candidate `pending`.

The deterministic path is the law here (no model configured), so the eval runs
`decide(..., llm=None)`. `CONFLICT` is the model's "unsure" verdict and is
tested through `apply_decision`, not through the resolver.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from em.facade.engine import V3Engine  # noqa: E402
from em.formation.reconcile import (  # noqa: E402
    CONFLICT,
    NOOP,
    SUPERSEDE,
    UPDATE,
    Reconciliation,
    apply_decision,
    commit_policy,
    decide,
    extract_attribute,
    reconcile_candidate,
)
from em.store.db import Store  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

DATASET = REPO / "evals" / "datasets" / "reconcile.jsonl"
SCOPE = Scope(profile="default", user="")


def _load():
    rows = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


# --- the decision engine -----------------------------------------------------


def test_the_rule_path_meets_the_decision_accuracy_gate():
    """**The card's CI-gated AC.** A detector/fusion regression drops a category."""
    per = defaultdict(lambda: [0, 0])
    for case in _load():
        got = decide(case["candidate"], case["neighbours"]).decision
        per[case["category"]][1] += 1
        if got == case["gold"]:
            per[case["category"]][0] += 1

    for category in ("update", "contradiction"):
        correct, total = per[category]
        assert total >= 10, f"{category}: only {total} cases"
        assert correct / total >= 0.9, f"{category}: {correct}/{total} below the 0.9 AC"

    correct = sum(v[0] for v in per.values())
    total = sum(v[1] for v in per.values())
    assert correct / total >= 0.9, f"overall {correct}/{total}"


def test_the_attribute_detector_normalises_subject_and_value():
    mine = extract_attribute("My timezone is Europe/Paris.")
    assert mine is not None
    assert mine.key == ("timezone", "is")
    assert mine.value == "europe/paris"

    server = extract_attribute("The staging server runs on port 9090.")
    assert server is not None
    assert server.key == ("staging server", "runs on")
    assert server.value == "port 9090"

    assert extract_attribute("Just a sentence with no attribute.") is None


def test_an_exact_duplicate_is_a_noop():
    candidate = {"content": "The nightly billing job reconciles customer invoices.", "content_hash": "h1"}
    neighbours = [{"id": "m1", "content": candidate["content"], "content_hash": "h1"}]
    assert decide(candidate, neighbours).decision == NOOP


def test_the_commit_policy_follows_the_three_conditions():
    assert commit_policy({"source": "user_stated"}).status == "active"
    confident = {"source": "auto_extracted", "confidence": 0.8, "kind": "fact", "sensitivity": "internal"}
    assert commit_policy(confident).status == "active"
    assert commit_policy({**confident, "confidence": 0.5}).status == "pending"
    assert commit_policy({**confident, "sensitivity": "sensitive"}).status == "pending"
    assert commit_policy({**confident, "trust_flags": ["conflict:m1"]}).status == "pending"
    assert commit_policy({**confident, "kind": "event"}).status == "pending"


# --- applying a decision -----------------------------------------------------


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    V3Engine(db).close()
    return db


def _seed(db: Path, target: str, candidate: str, *, confidence: float = 0.8):
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            memories = MemoryStore(conn)
            t = memories.add(
                MemoryDraft(content=target, kind="fact", status="active", source="agent"),
                scope=SCOPE, actor="test",
            )
            c = memories.add(
                MemoryDraft(content=candidate, kind="fact", confidence=confidence,
                            status="pending", pending_reason="extracted", source="auto_extracted"),
                scope=SCOPE, actor="test",
            )
            assert t.ok and c.ok, (t, c)
            return t.id, c.id
    finally:
        store.close()


def test_update_writes_a_version_row_and_keeps_the_old_content(tmp_path):
    db = _db(tmp_path)
    target_id, cand_id = _seed(
        db,
        "The nightly billing job reconciles customer invoices.",
        "The nightly billing job reconciles customer invoices daily.",
    )
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            memories = MemoryStore(conn)
            candidate = memories.get(cand_id, scope=SCOPE)
            target = memories.get(target_id, scope=SCOPE)
            decision, _ = reconcile_candidate(conn, candidate, [target], scope=SCOPE)
            row = memories.get(target_id, scope=SCOPE)
            versions = conn.execute(
                "SELECT version, content FROM memory_versions WHERE memory_id=? ORDER BY version",
                (target_id,),
            ).fetchall()
            actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
            candidate_row = memories.get(cand_id, scope=SCOPE)
    finally:
        store.close()

    assert decision.decision == UPDATE
    assert row["content"].endswith("daily.") and row["version"] > 1
    assert any(v["content"] == "The nightly billing job reconciles customer invoices." for v in versions), (
        "the pre-edit content must survive as a version row"
    )
    assert candidate_row["status"] == "deleted"
    assert "reconcile" in actions and "update" in actions


def test_supersede_links_the_old_row_and_writes_a_successor(tmp_path):
    db = _db(tmp_path)
    target_id, cand_id = _seed(db, "The staging port is 9090.", "The staging port is 7070.")
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            memories = MemoryStore(conn)
            candidate = memories.get(cand_id, scope=SCOPE)
            target = memories.get(target_id, scope=SCOPE)
            decision, outcome = reconcile_candidate(conn, candidate, [target], scope=SCOPE)
            old = memories.get(target_id, scope=SCOPE)
            successor = memories.get(outcome.get("successor_id"), scope=SCOPE)
            candidate_row = memories.get(cand_id, scope=SCOPE)
            actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    finally:
        store.close()

    assert decision.decision == SUPERSEDE
    assert old["status"] == "superseded" and old["superseded_by"] == outcome["successor_id"]
    assert outcome["successor_id"] != cand_id
    assert successor is not None and "7070" in successor["content"]
    assert candidate_row["status"] == "deleted"
    assert "reconcile" in actions


def test_add_promotes_only_when_the_policy_allows(tmp_path):
    db = _db(tmp_path)
    _, cand_id = _seed(
        db, "The staging cluster runs on Ubuntu.", "Alice Example prefers tea.", confidence=0.8
    )
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            memories = MemoryStore(conn)
            candidate = memories.get(cand_id, scope=SCOPE)
            decision, outcome = reconcile_candidate(conn, candidate, [], scope=SCOPE)
            promoted = memories.get(cand_id, scope=SCOPE)
    finally:
        store.close()
    assert decision.decision == "ADD"
    assert outcome["status"] == "active" and promoted["status"] == "active"

    db2 = _db(tmp_path / "low")
    db2.parent.mkdir(parents=True, exist_ok=True)
    _, cand2 = _seed(db2, "The staging cluster runs on Ubuntu.", "Alice Example prefers tea.", confidence=0.4)
    store = Store(str(db2))
    try:
        with store.transaction() as conn:
            memories = MemoryStore(conn)
            candidate = memories.get(cand2, scope=SCOPE)
            reconcile_candidate(conn, candidate, [], scope=SCOPE)
            still = memories.get(cand2, scope=SCOPE)
    finally:
        store.close()
    assert still["status"] == "pending"


def test_noop_discards_the_candidate_without_touching_the_target(tmp_path):
    db = _db(tmp_path)
    target_id, cand_id = _seed(db, "The vault holds twelve notes.", "The vault holds twelve notes today.")
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            memories = MemoryStore(conn)
            candidate = memories.get(cand_id, scope=SCOPE)
            apply_decision(
                conn, candidate, Reconciliation(NOOP, target_id, reason="exact_duplicate"),
                scope=SCOPE, plan=commit_policy(candidate),
            )
            target = memories.get(target_id, scope=SCOPE)
            candidate_row = memories.get(cand_id, scope=SCOPE)
    finally:
        store.close()
    assert target["status"] == "active" and target["version"] == 1
    assert candidate_row["status"] == "deleted"


def test_conflict_keeps_the_candidate_pending_with_a_trust_flag(tmp_path):
    db = _db(tmp_path)
    target_id, cand_id = _seed(db, "The deploy target is staging.", "The deploy target is production.")
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            memories = MemoryStore(conn)
            candidate = memories.get(cand_id, scope=SCOPE)
            apply_decision(
                conn, candidate, Reconciliation(CONFLICT, target_id, reason="unsure"),
                scope=SCOPE, plan=commit_policy(candidate),
            )
            row = memories.get(cand_id, scope=SCOPE)
            actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    finally:
        store.close()
    assert row["status"] == "pending"
    assert f"conflict:{target_id}" in json.loads(row["trust_flags"])
    assert "trust_flags" in actions and "reconcile" in actions
