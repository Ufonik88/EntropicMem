"""``em.facade`` — the v2-compatible engine API over the v3 store (card EM-211).

``contract`` defines the target: what the Hermes provider calls, with which
arguments, and the behaviour it relies on. The facade implementation (EM-211)
lives next to it and is registered in ``tests/unit/test_em_facade_contract.py``
and ``tests/parity/`` so both suites run against it.

Stdlib-only (plan §3.2); never imports the provider or the Hermes host.
"""

from .contract import BEHAVIOURS, PROVIDER_ATTRIBUTES, PROVIDER_CALLS, FactView, LegacyEngine

__all__ = ["BEHAVIOURS", "FactView", "LegacyEngine", "PROVIDER_ATTRIBUTES", "PROVIDER_CALLS"]
