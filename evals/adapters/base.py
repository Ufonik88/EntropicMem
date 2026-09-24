"""Adapter interface shared by engine_v2 / engine_v3 adapters (EM-001).

Contract (plan §EM-001 spec):
    load(scenario) -> EvalHandle
    search(handle, query, k) -> List[Hit]
    prefetch(handle, query) -> str      # the rendered injection block ('' = abstain)

``EvalHandle`` carries the ref-resolution table the runner needs: ``ref_ids``
maps ``$N`` dataset refs to the concrete ids the engine assigned at load, and
``noise_ids`` holds every noise memory's id. ``extra`` is adapter-private
state (engine/provider handles).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Set

from evals.dataset import Scenario


@dataclass
class Hit:
    id: str
    content: str
    score: float = 0.0


@dataclass
class EvalHandle:
    scenario: Scenario
    ref_ids: Dict[str, str] = field(default_factory=dict)   # "$0" → real id
    noise_ids: Set[str] = field(default_factory=set)
    extra: Dict[str, Any] = field(default_factory=dict)


class AdapterBase:
    """Duck-typed interface documentation; adapters need not subclass."""

    name = "base"

    def load(self, scenario: Scenario) -> EvalHandle:  # pragma: no cover - interface
        raise NotImplementedError

    def search(self, handle: EvalHandle, query: str, k: int = 5) -> List[Hit]:  # pragma: no cover
        raise NotImplementedError

    def prefetch(self, handle: EvalHandle, query: str) -> str:  # pragma: no cover
        raise NotImplementedError


def collect_ids(hits: Sequence[Hit]) -> List[str]:
    """Ordered id list of a search result (runner input for ranking metrics)."""
    return [h.id for h in hits]
