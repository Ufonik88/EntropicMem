"""Deterministic filler-noise generator (stdlib `random`, seeded).

Noise memories stress-test injection ranking: with hundreds of same-domain
filler rows around a handful of scenario facts, retrieval that ranks on
per-set-normalised relevance cannot tell signal from noise. Sentences are
composed from disjoint word banks so results are stable per (generator,
seed, count) — datasets and CI baselines stay reproducible.

Word banks deliberately avoid every keyword the `ci` scenario probes lean on
(see tests/evals/test_noise.py for the enforced list), so a noise hit is
always an engine ranking failure, never a shared-token coincidence.
"""
from __future__ import annotations

import random
from typing import List

# Subject slot × object slot × verb slot gives >20k distinct sentences; the
# rejection loop tops up uniqueness when the same combination is drawn twice.
_SUBJECTS = [
    "The archivist", "The courier", "The librarian", "The cartographer",
    "The botanist", "The horologist", "The bookbinder", "The surveyor",
    "The lens grinder", "The typesetter", "The conservator", "The actuary",
    "The notary", "The apothecary", "The chandler", "The cooper",
    "The farrier", "The glassblower", "the mason", "the miller",
    "The roofer", "the sailor", "the weaver", "the wheelwright",
    "The dockhand", "the engraver", "the ferryman", "the gardener",
    "the joiner", "the plater",
]
_OBJECTS = [
    "the brass compass", "the linen ledger", "the cedar crate", "the tin kettle",
    "the oak panel", "the slate tablet", "the copper wire", "the wicker basket",
    "the parchment scroll", "the iron latch", "the marble tile", "the glass vial",
    "the rope ladder", "the wool blanket", "the clay pot", "the ash ladder",
    "the pine shelf", "the steel clasp", "the paper chart", "the stone basin",
    "the leather satchel", "the wooden model", "the silver frame", "the cotton sail",
    "the bronze bell", "the hemp rope", "the quartz lens", "the mica sheet",
    "the walnut desk", "the zinc tray",
]
_VERBS = [
    "catalogued", "polished", "measured", "sketched", "wrapped", "labelled",
    "inspected", "inventoried", "restored", "stored", "trimmed", "weighed",
    "aligned", "varnished", "sorted", "indexed", "sealed", "shelved",
    "tagged", "traced", "drilled", "sanded", "riveted", "stitched",
    "annealed", "burnished", "calibrated", "engraved", "mounted", "planed",
]
_TAILS = [
    "before lunch", "on a rainy Tuesday", "after the audit", "during the fair",
    "beside the window", "under the old map", "with great patience",
    "while the kettle cooled", "near the harbor gate", "at the end of the row",
    "before the frost", "after the bell rang", "without hurry",
    "in the second drawer", "along the north wall", "under canvas",
    "amid the sawdust", "by lantern light", "in the quiet hour", "past noon",
]
_TEMPLATES = [
    "{s} {v} {o} {t}.",
    "{s} kept {o} {t}, {v} once more.",
]


def _filler_sentence(rng: random.Random) -> str:
    s = rng.choice(_SUBJECTS)
    o = rng.choice(_OBJECTS)
    v = rng.choice(_VERBS)
    t = rng.choice(_TAILS)
    tmpl = rng.choice(_TEMPLATES)
    return tmpl.format(s=s, o=o, v=v, t=t)


def generate(generator: str, count: int, seed: int) -> List[str]:
    """Return ``count`` unique filler sentences for ``seed`` (deterministic)."""
    if generator != "filler":
        raise ValueError(f"unknown noise generator: {generator!r}")
    rng = random.Random(seed)
    out: List[str] = []
    seen = set()
    guard = 0
    while len(out) < count:
        guard += 1
        if guard > count * 100 + 1000:  # banks exhausted
            out.append(f"Filler note number {len(out)}: routine paperwork archived.")
            continue
        sentence = _filler_sentence(rng)
        if sentence in seen:
            continue
        seen.add(sentence)
        out.append(sentence)
    return out
