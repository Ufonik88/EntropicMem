"""EM-608: the statistic the 50k warm-p95 gate measures with.

The defect EM-608 records is the gate's **measurement**, not its budget. Both
warm-p95 ACs used to take one p95 over 25 probes; on a shared runner that
number moves with the host, not with the code, and it flapped twice in two days
on unchanged SHAs (`6e86c98`, p95 153.35 ms; `bdc1e20`, p95 151.09 ms), each
with a uniformly inflated distribution — the opposite tell from a real
regression, which shows a stall tail.

The fix is EM-407's, generalised: time **five 20-probe windows** and gate on the
**best** window's p95. A transient contention cannot inflate all five windows,
so it is absorbed; a genuine regression inflates every window and still fails.
The 150 ms budget is untouched.

Usage in an AC::

    timed = timed_windows(run, windows=5, probes=20)   # run(i) -> anything
    best = best_window_p95(timed)
    assert best <= 150.0

`run` is called once per probe with a **distinct index** (``0..windows*probes-1``),
which is what keeps the probes' queries distinct — a repeated query would hit
the cache and depress the p95.
"""

from __future__ import annotations

import time

__all__ = ("best_window_p95", "timed_windows", "window_p95")


def window_p95(samples):
    """The nearest-rank p95 the gate has always used: ``sorted[n - 1]`` where
    ``n = max(0, int(0.95 * len) - 1)``. Deliberately identical to the old
    single-window gate, so no recorded reading shifts underneath the fix.
    """
    ordered = sorted(samples)
    return ordered[max(0, int(0.95 * len(ordered)) - 1)]


def timed_windows(run, *, windows=5, probes=20):
    """Call ``run(index)`` for every index in ``range(windows * probes)``, timing
    each, and return ``windows`` lists of ``probes`` floats in milliseconds.
    """
    return [
        [_timed(run, window * probes + probe) for probe in range(probes)]
        for window in range(windows)
    ]


def best_window_p95(timed):
    """The smallest of the windows' p95s. A transient stall inflates one window
    and is absorbed; a genuine regression inflates every window and survives.
    """
    return min(window_p95(samples) for samples in timed)


def _timed(run, index):
    started = time.perf_counter()
    run(index)
    return (time.perf_counter() - started) * 1000.0
