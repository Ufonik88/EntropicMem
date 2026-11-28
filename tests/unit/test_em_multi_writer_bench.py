"""Guards for the multi-writer benchmark (``evals/multi_writer``).

The benchmark's whole value is that its numbers come from the shipped write and
read path, so these tests drive the real store and assert the *relations* the
README claims — not a table of frozen numbers. A frozen table would pass while
the corpus silently stopped exercising the mechanism, which is the failure mode
this file exists to prevent.

Every scenario is generated from a seed; nothing here reads a live store, the
network or the clock.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest
from evals.multi_writer import bench
from evals.multi_writer.bench import (
    PROTOCOLS,
    SHAPES,
    apply_writes,
    build_scenario,
    content_for,
    run,
    run_protocol,
)

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"

_VALUE = re.compile(r"^(alpha|bravo|charlie|delta)-[a-z]+-\d{2}$")


def test_the_corpus_is_deterministic_and_every_shape_is_present() -> None:
    first = build_scenario(seed=7, keys=12)
    second = build_scenario(seed=7, keys=12)
    assert [(k.key, k.shape, k.writes) for k in first.keys] == [
        (k.key, k.shape, k.writes) for k in second.keys
    ]
    assert {k.shape for k in first.keys} == set(SHAPES)
    assert build_scenario(seed=8, keys=12).keys != first.keys


def test_every_value_is_a_synthetic_codename() -> None:
    scenario = build_scenario(seed=20261128, keys=12)
    for ks in scenario.keys:
        for value in (*ks.values, ks.conflict):
            if value:
                assert _VALUE.match(value), value
        assert " " not in ks.conflict


def test_a_scenario_has_one_ground_truth_per_scored_key() -> None:
    scenario = build_scenario(seed=11, keys=8)
    for ks in scenario.keys:
        assert ks.current in {w.value for w in ks.writes}
        if ks.has_ground_truth:
            assert ks.conflict == ""
            assert ks.current not in ks.stale
        else:
            assert ks.conflict_second in {w.value for w in ks.writes}


def test_the_echo_is_the_better_lexical_match() -> None:
    """The stale echo must repeat the key more often than the correction.

    If it did not, the benchmark would be measuring BM25 length normalisation
    rather than the failure mode the README claims.
    """
    ks = next(k for k in build_scenario(seed=3, keys=8).keys if k.shape == "rogue_echo")
    echo = next(w for w in ks.writes if w.kind == "echo")
    correct = next(w for w in ks.writes if w.kind == "correct")
    key_words = ks.key.split()
    echo_hits = sum(content_for(echo).count(word) for word in key_words)
    correct_hits = sum(content_for(correct).count(word) for word in key_words)
    assert echo_hits > correct_hits


def test_supersede_removes_a_corrected_value_and_a_plain_append_does_not() -> None:
    """The mechanism: a corrected row stops being a candidate at all."""
    scenario = build_scenario(seed=5, keys=4)
    succession = next(k for k in scenario.keys if k.shape == "succession")

    appended = run_protocol(bench.Scenario(seed=0, keys=(succession,)), "append")
    superseded = run_protocol(bench.Scenario(seed=0, keys=(succession,)), "supersede")

    assert appended.keys[0].served == "stale"
    assert superseded.keys[0].served == "current"
    assert superseded.keys[0].current_rank == 0
    assert superseded.keys[0].active_stale == 0


def test_the_residual_is_the_rogue_echo_and_the_guard_closes_it() -> None:
    scenario = build_scenario(seed=5, keys=4)
    echo = next(k for k in scenario.keys if k.shape == "rogue_echo")
    one = bench.Scenario(seed=0, keys=(echo,))

    assert run_protocol(one, "append").keys[0].served == "stale"
    # Supersede alone cannot help: the echo is a fresh row carrying a dead value.
    assert run_protocol(one, "supersede").keys[0].served == "stale"
    guarded = run_protocol(one, "supersede_guard").keys[0]
    assert guarded.served == "current"
    assert guarded.active_stale == 0


def test_the_dead_value_check_sees_history_not_prose(tmp_path: Path) -> None:
    """The guard's premise: a re-assertion's text differs, its value does not."""
    from em.store.db import Store
    from em.store.memories import MemoryStore
    from em.store.migrations import migrate
    from em.store.types import MemoryDraft, Scope

    stamp = bench.BASE
    draft = MemoryDraft(
        content=f"{bench._KEYS[0]}: alpha-aurora-01.",
        status="active",
        valid_from=bench.to_iso(stamp),
    )
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(str(Path(tmp) / "memory.db"))
        try:
            with store.writer() as conn:
                migrate(conn)
            with store.transaction() as conn:
                memories = MemoryStore(conn)
                first = memories.add(draft, scope=Scope(profile=bench.PROFILE), actor="atlas")
                replacement = MemoryDraft(
                    content=f"{bench._KEYS[0]}: bravo-aurora-01.",
                    status="active",
                    valid_from=bench.to_iso(stamp),
                )
                memories.supersede(
                    first.id, replacement, scope=Scope(profile=bench.PROFILE), actor="atlas",
                    reason="corrected",
                )
            conn = store.reader()
            scope = Scope(profile=bench.PROFILE)
            assert bench._value_is_dead(conn, scope, "alpha-aurora-01") is True
            assert bench._value_is_dead(conn, scope, "bravo-aurora-01") is False
            # The echo's prose is a different string carrying the dead value,
            # which is why an exact-text check would have missed it: the check
            # has to be on the value, as above.
            echo_key = next(
                k for k in bench.build_scenario(seed=3, keys=8).keys if k.shape == "rogue_echo"
            )
            echo = next(w for w in echo_key.writes if w.kind == "echo")
            assert echo.value in content_for(echo)
            assert content_for(echo) != f"{echo.key}: {echo.value}."
        finally:
            store.close()


def test_no_protocol_loses_a_value() -> None:
    """History is a control, not a score: a correction never destroys evidence."""
    payload = run(seed=20261128, keys=8)
    for row in payload["protocols"]:
        assert row["history_recoverable"] == 1.0, row


def test_the_benchmark_table_has_one_row_per_protocol() -> None:
    payload = run(seed=20261128, keys=8)
    table = bench.render_markdown(payload)
    for protocol in PROTOCOLS:
        assert f"`{protocol}`" in table
    assert [row["protocol"] for row in payload["protocols"]] == list(PROTOCOLS)
    assert all(row["scored_keys"] == 6 for row in payload["protocols"])


def test_an_unknown_protocol_is_refused() -> None:
    scenario = build_scenario(seed=1, keys=4)
    with tempfile.TemporaryDirectory() as tmp:
        from em.store.db import Store
        from em.store.migrations import migrate

        store = Store(str(Path(tmp) / "memory.db"))
        try:
            with store.writer() as conn:
                migrate(conn)
            with pytest.raises(ValueError):
                apply_writes(store, scenario, "append_but_clever")
        finally:
            store.close()
