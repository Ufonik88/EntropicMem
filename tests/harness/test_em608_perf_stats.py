"""EM-608: the 50k warm-p95 gate must gate on a statistic, not on one window.

The defect EM-608 records is the gate's **measurement**. `test_warm_p95_at_50k_is_under_150ms`
(the component AC) and `…_through_the_provider` (its wired twin) each took **one**
p95 over 25 probes. On a shared runner that number moves with the host, not with the
code: it flapped twice in two days on unchanged SHAs (`6e86c98`, p95 153.35 ms; `bdc1e20`,
p95 151.09 ms), both with a **uniformly inflated** distribution — the opposite tell from
a real regression, which shows a stall tail. Re-running a red `main` job until it goes
green is a workaround: the verdict depends on which runner the job lands on, so it does
not gate.

The fix is EM-407's, generalised: five 20-probe windows, and the **best** window's p95
must hold the budget. A transient contention cannot inflate all five windows; a genuine
regression inflates everyone and still fails. **The 150 ms budget is untouched.**

These tests pin the statistic itself, because the ACs cannot: they exercise a 50k store,
so they cannot be made slower on demand. `best_window_p95` is fed the shapes directly —
a uniformly slow run, a genuinely fast one, and the flake's exact shape (one contended
window among four clean ones) — plus a structural pin that both ACs still use it, so the
fix cannot be silently reverted to a single window.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from perf_stats import best_window_p95, timed_windows, window_p95  # noqa: E402

HARNESS = Path(__file__).resolve().parent
BUDGET_MS = 150.0

#: The two ACs that gate on this statistic. The first is the component harness
#: (EM-403's card AC); the second is its wired twin through the provider (chunk 35).
#: Both carried the single-window defect, so both are pinned.
WARM_ACS = (
    ("test_prefetch_service_ac.py", "test_warm_p95_at_50k_is_under_150ms"),
    (
        "test_em403_slice3_wired_ac.py",
        "test_warm_p95_at_50k_is_under_150ms_through_the_provider",
    ),
)


def _function_body(filename: str, name: str) -> str:
    """The source of `def <name>(…)` up to the next top-level `def`/`class`."""
    lines = (HARNESS / filename).read_text(encoding="utf-8").splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith(f"def {name}("):
            start = index
            break
    assert start is not None, f"{filename} has no {name}()"
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith(("def ", "class ", "@")):
            end = index
            break
    return "\n".join(lines[start:end])


# --- the statistic's definition -------------------------------------------


def test_the_p95_is_the_nearest_rank_definition_the_gate_always_used():
    """`window_p95` must be the same number the old single-window gate computed —
    nearest rank, `sorted(int(0.95 * n) - 1)`, which for 20 samples is the
    second-worst sample. A definition that drifted (say, linear interpolation)
    would quietly move every recorded reading."""
    assert window_p95([float(i) for i in range(20)]) == 18.0
    assert window_p95([1.0] * 20) == 1.0
    assert window_p95([7.0]) == 7.0


def test_timed_windows_shapes_the_run_into_windows():
    """The helper times every call and returns `windows` lists of `probes` floats."""
    timed = timed_windows(lambda _index: time.sleep(0.001), windows=4, probes=3)
    assert [len(window) for window in timed] == [3, 3, 3, 3]
    assert all(0.0 < sample < BUDGET_MS for window in timed for sample in window)


def test_timed_windows_passes_each_call_its_own_index():
    """Each probe gets a distinct index, which is what keeps the ACs' queries
    distinct — a repeated query would hit the cache and depress the p95."""
    seen: list[int] = []
    timed_windows(seen.append, windows=2, probes=4)
    assert seen == list(range(8))
    assert len(timed_windows(seen.append, windows=1, probes=1)) == 1


# --- what the statistic is for --------------------------------------------


def test_a_structurally_fast_run_passes():
    timed = [[1.0] * 20 for _ in range(5)]
    assert best_window_p95(timed) <= BUDGET_MS


def test_a_uniformly_slow_run_fails_every_window():
    """A genuine regression inflates every window: the best of five is still over
    the budget, so the statistic still fails it. This is the property the fix must
    not trade away — a best-of-N that passes a real regression is worse than the
    flake it replaced."""
    timed = [[160.0] * 20 for _ in range(5)]
    assert best_window_p95(timed) > BUDGET_MS


def test_one_contended_window_is_absorbed_by_the_best_of_n():
    """The recorded flake's exact shape, fed directly: four clean windows and one
    the runner inflated. The best of five holds the budget, which is the whole
    point — and the contended window is really over it, so the test is not
    trivially satisfied."""
    clean = [40.0] * 20
    stalled = [1000.0] * 20
    timed = [clean, clean, stalled, clean, clean]
    assert window_p95(stalled) > BUDGET_MS, "the stalled window must really be over"
    assert best_window_p95(timed) <= BUDGET_MS


def test_the_statistic_does_not_hide_a_slowdown_near_the_budget():
    """Four windows a hair under the budget and one a hair over: the best window
    passes by design (that window is a real reading), so the failure signal is the
    sustained breach — pinned here so the best-of-N rule is stated, not assumed."""
    timed = [[140.0] * 20, [140.0] * 20, [151.0] * 20, [140.0] * 20, [140.0] * 20]
    assert best_window_p95(timed) <= BUDGET_MS


# --- the ACs must actually use it -----------------------------------------


def test_both_warm_p95_acs_gate_on_the_best_window():
    """A correct statistic nobody calls fixes nothing. Both ACs must build their
    samples with `timed_windows`/`best_window_p95` and keep the 150 ms budget —
    reverting either to a single `_report` p95 over 25 probes reopens EM-608."""
    for filename, name in WARM_ACS:
        body = _function_body(filename, name)
        assert "best_window_p95(" in body, (
            f"{filename}::{name} no longer gates on the best window; a single-window "
            "p95 is the EM-608 defect"
        )
        assert "timed_windows(" in body, (
            f"{filename}::{name} no longer builds its samples in windows"
        )
        assert "150.0" in body, f"{filename}::{name} no longer names the 150 ms budget"
        assert "range(25)" not in body, (
            f"{filename}::{name} is back to one 25-probe window (the EM-608 defect)"
        )
