"""Scenario dataset loading and ``$``-reference resolution (EM-001).

Dataset format: JSONL, one scenario per line. Blank lines and lines starting
with ``#`` are ignored.

``$N`` in turn refs addresses the N-th memory of the scenario (as loaded);
``$noise`` expands to every noise memory id. Resolution maps refs to the real
entropic ids returned by the adapter at load time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Set


class ScenarioError(ValueError):
    """Raised when a dataset line is malformed or refs are unresolvable."""


@dataclass
class Memory:
    content: str
    kind: str = "fact"
    age_days: float = 0.0
    importance: float = 0.5
    domain: str = "Knowledge"
    scope_user: str = ""


@dataclass
class NoiseSpec:
    generator: str = "filler"
    count: int = 0
    seed: int = 0


@dataclass
class Turn:
    query: str
    expect_ids: List[str] = field(default_factory=list)
    expect_substrings: List[str] = field(default_factory=list)
    must_not: List[str] = field(default_factory=list)


@dataclass
class Scenario:
    scenario_id: str
    category: str
    memories: List[Memory]
    noise: NoiseSpec
    turns: List[Turn]


def _require(obj: dict, key: str, where: str):
    if key not in obj:
        raise ScenarioError(f"{where}: missing required field '{key}'")
    return obj[key]


def _parse_memory(raw: dict, where: str) -> Memory:
    return Memory(
        content=str(_require(raw, "content", where)),
        kind=str(raw.get("kind", "fact")),
        age_days=float(raw.get("age_days", 0.0)),
        importance=float(raw.get("importance", 0.5)),
        domain=str(raw.get("domain", "Knowledge")),
        scope_user=str(raw.get("scope_user", "")),
    )


def _parse_turn(raw: dict, where: str) -> Turn:
    return Turn(
        query=str(_require(raw, "query", where)),
        expect_ids=[str(x) for x in raw.get("expect_ids", [])],
        expect_substrings=[str(x) for x in raw.get("expect_substrings", [])],
        must_not=[str(x) for x in raw.get("must_not", [])],
    )


def parse_scenario(raw: dict, where: str = "<inline>") -> Scenario:
    sid = str(_require(raw, "id", where))
    category = str(_require(raw, "category", where))
    mems_raw = _require(raw, "memories", where)
    if not isinstance(mems_raw, list):
        raise ScenarioError(f"{where}: 'memories' must be a list")
    memories = [_parse_memory(m, f"{where} memories") for m in mems_raw]
    noise_raw = raw.get("noise") or {}
    noise = NoiseSpec(
        generator=str(noise_raw.get("generator", "filler")),
        count=int(noise_raw.get("count", 0)),
        seed=int(noise_raw.get("seed", 0)),
    )
    turns_raw = raw.get("turns")
    if not isinstance(turns_raw, list) or not turns_raw:
        raise ScenarioError(f"{where}: 'turns' must be a non-empty list")
    turns = [_parse_turn(t, f"{where} turns") for t in turns_raw]
    return Scenario(scenario_id=sid, category=category, memories=memories, noise=noise, turns=turns)


def load_scenarios(path: Path) -> List[Scenario]:
    """Load a JSONL dataset file into Scenario objects (order preserved)."""
    scenarios: List[Scenario] = []
    seen: Set[str] = set()
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise ScenarioError(f"{path}:{lineno}: bad JSON: {e}") from e
            where = f"{path.name}:{lineno}"
            sc = parse_scenario(raw, where)
            if sc.scenario_id in seen:
                raise ScenarioError(f"{where}: duplicate scenario id '{sc.scenario_id}'")
            seen.add(sc.scenario_id)
            scenarios.append(sc)
    return scenarios


def resolve_refs(
    refs: Sequence[str],
    real_ids: Dict[str, str],
    noise_ids: Set[str],
) -> List[str]:
    """Map scenario refs (``$0``, ``$noise``, literal ids) to concrete ids.

    ``real_ids`` maps ``$N`` → entropic id assigned at load. ``$noise`` expands
    to all noise ids (sorted for determinism). Unknown refs raise
    ScenarioError — silently dropping a bad ref would hide dataset bugs.
    """
    out: List[str] = []
    for ref in refs:
        if ref == "$noise":
            out.extend(sorted(noise_ids))
        elif ref.startswith("$"):
            if ref not in real_ids:
                raise ScenarioError(f"unresolvable reference '{ref}'")
            out.append(real_ids[ref])
        else:
            out.append(ref)
    return out
