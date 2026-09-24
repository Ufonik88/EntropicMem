"""Deterministic filler-noise generator tests."""
from evals import noise


def test_noise_is_deterministic_per_seed():
    a = noise.generate("filler", count=10, seed=7)
    b = noise.generate("filler", count=10, seed=7)
    assert a == b
    assert len(a) == 10


def test_noise_differs_across_seeds():
    assert noise.generate("filler", 10, 1) != noise.generate("filler", 10, 2)


def test_noise_sentences_are_unique():
    items = noise.generate("filler", 120, 3)
    assert len(set(items)) == len(items)


def test_noise_avoids_scenario_keywords():
    # Filler must never lexically collide with the words scenarios probe on.
    banned = {"port", "server", "city", "riverton", "gateway", "payment",
              "charge", "retry", "retries", "terse", "home", "weather",
              "forecast", "kubernetes", "namespace"}
    for item in noise.generate("filler", 150, 11):
        toks = {t.lower().strip(".,!?") for t in item.split()}
        assert not (toks & banned), f"collision: {toks & banned} in {item!r}"


def test_unknown_generator_raises():
    import pytest

    with pytest.raises(ValueError):
        noise.generate("nonexistent", 1, 0)
