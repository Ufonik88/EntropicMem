# Suite baseline — the one place the expected counts are written

**This file is the single source of truth for the expected test counts.**
`MASTER_TODO.md`, `NEXT_CHUNK.md` and `REMAINING_PLAN.md` *reference* it; they
must not restate the numbers, because three hand-copied triples mean three
edits per chunk and a silent one-page drift when one is missed. Update **this
file only** at the end of a chunk.

## Legend

The triple is **`passed / skipped / xfailed`** — in that order, everywhere.

* **passed** — ran and asserted true.
* **skipped** — did not run, by design, because something the test needs is
  absent on that machine (an optional dependency, a private file, the host
  checkout). A skip is not a failure.
* **xfailed** — ran, hit a condition the repo has agreed to accept for now
  (`tests/regressions/test_findings_v27.py`'s tracked debt). Not a failure.

**Failed is a fourth number and it is always 0 on a green run.** When a run
reports `2813 passed, 4 skipped, 2 xfailed`, that is green: nothing failed.
If a summary line ever contains `1 failed`, the run is red regardless of the
other three.

## The numbers

| Environment | Command | Triple |
|---|---|---|
| **CI, `test` job, Python 3.12** (the figure of record) | `pytest -q tests/` | **2954 passed, 4 skipped, 2 xfailed** *(projected from this box's CI-equivalent run by the host-pin relation; the run for this branch's SHA is read at landing and stamped in the reconciliation)* |
| This box, bare (`.venv311`, no extras) | `pytest -q tests/` | **2878 passed, 16 skipped, 2 xfailed** |
| This box, + the private digest list | `ENTROPICMEM_PRIVACY_DIGESTS_FILE=… pytest -q` | **2879 passed, 15 skipped, 2 xfailed** |
| This box, CI-equivalent (`.venv` 3.12 + extras + digest) | `pytest -q tests/` | **2956 passed, 2 skipped, 2 xfailed** |
| This box, Python 3.10 (`.venv310`, full suite) | `pytest -q tests/` | **2954 passed, 4 skipped, 2 xfailed** |

Read as at `2fd7812` (the EM-605 slice-1 landing) — the three local rows above are measured
on the EM-605 slice-1 follow-up branch, and the CI row is **projected** from them by the
host-pin relation, so no SHA is claimed for it yet; the landing stamps the read figure and
its run id here. The last run read on this line was **`39236004212`** (the
`em-605-graph-split` push at `2fd7812`: all 11 jobs success, `identity-guard` and
`windows-import` included, CI 3.12 **2936 / 4 / 2** on all four legs), re-verified on `main`
by run **`39237280578`**; before it `e6647e7` (run `39231027295`), `adb1439` (run
`39226716232`) and `4cde953` (run `39219386624`). CI's figure is **read from the job log**,
never assumed: `gh run view <run-id> --log`; all four CI legs (3.10–3.13) report the
identical triple. **The gap between this box's CI-equivalent reading and CI is in the middle
column, not the total — `2956 / 2 / 2` versus `2954 / 4 / 2` is `−2 passed, +2 skipped`, the
two hermes-agent host pins that pass here and skip in CI**, the same pair the ladder below
walks. **The four triples in this table are the figures of record and live in exactly one
other place, [`suite_figures.json`](suite_figures.json), which
[`scripts/record_suite_figures.py`](../../scripts/record_suite_figures.py) writes from
pytest summary lines and [`tests/test_suite_figures.py`](../../tests/test_suite_figures.py)
checks them against.**

## Why the three environments differ

**CI's 4 skips** — the same four on every leg, because the conditions are
host-absence and are identical on all runners (measured by running these four
files with `HOME` pointed at an empty directory, which reproduces CI exactly:
`42 passed, 4 skipped`):

1. `tests/test_v2_1_8.py` — **module-level** skip, so the whole module counts
   as one: "health/stability-gate scripts live in the internal ops workspace
   (not the public repo)".
2. `tests/test_v2_2_0.py::test_health_check_has_new_checks` — same workspace.
3. `tests/test_provider_contract.py::test_the_pin_matches_the_host_when_the_host_is_reachable`
   — "pinned hermes-agent not reachable on this box".
4. `tests/unit/test_em408_cli_mount.py::test_the_host_discovery_contract_is_pinned`
   — "hermes-agent checkout not reachable (CI: the host is absent)".

The last two **pass** on a dev box that has a `hermes-agent` checkout, which is
why the CI-equivalent local run shows only 2 skips and 2 more passes.

**Bare's 16 skips** — the same four above (2 of them), plus the optional
dependencies the bare venv does not install. Measured directly, file by file:

| Reason | Skips | Files |
|---|---|---|
| `could not import 'fastapi'` | 4 | `test_graph_static.py`, `test_graph_server_v2_6.py`, `test_graph_server_titles.py`, `test_graph_server_security.py` |
| `cryptography not installed` | 7 | `test_security_decrypt_guard.py` (5), `test_phase11.py` (2) |
| `could not import 'numpy'` | 2 | `test_em_embedding_cache.py` |
| internal ops workspace | 2 | `test_v2_1_8.py`, `test_v2_2_0.py` |
| **private digest list not configured** | **1** | `tests/evals/test_no_personal_data.py` |
| **Total** | **16** | |

Those seven dependency files are **+77 passed / −13 skipped** measured
together (`41 passed, 13 skipped` bare vs `118 passed, 0 skipped` with extras).

**Why bare-with-digest shows 15, not 16.** `tests/evals/test_no_personal_data.py`
skips when the private digest list is absent and **passes** when it is present —
so pointing `ENTROPICMEM_PRIVACY_DIGESTS_FILE` at the list converts exactly one
skip into one pass. **This is by design, not a flake:** the test is the privacy
collision check, it must not run blind, and the two numbers are meant to be read
as a pair. The dev box does not have the list at the default path
(`~/.config/entropicmem/privacy-digests.txt` is absent); it lives at
`~/Documents/EntropicMem Dev docs/privacy-digests.txt`.

**Python 3.10 is a supported target, and the full suite runs there before a landing.**
`requires-python = ">=3.10"` and the `test` matrix runs 3.10–3.13, so 3.10 is not
best-effort: the row above is a full `pytest -q tests/` on this box's 3.10 venv, not
the touched files. (An earlier record said "the 3.10 leg green for the touched
files", which was the weaker check this replaces.)

## Known CI coverage gap — the two host pins

**Two tests pass on a dev box and never run in CI.** They are the two hermes-agent
host pins named in the skip list above:

* `tests/test_provider_contract.py::test_the_pin_matches_the_host_when_the_host_is_reachable`
* `tests/unit/test_em408_cli_mount.py::test_the_host_discovery_contract_is_pinned`

CI has no `hermes-agent` checkout, so both skip on every runner and on every Python
leg — which means the assertions that would catch a drift between the pinned host
contract and the host the plugin actually runs against are **the only two assertions
in the repo that CI never exercises**. Their *shape* is pinned elsewhere (the
provider-contract surface, the CLI mount), but not the pin itself.

**Decision, recorded rather than left implicit:** this is a known gap, not an
oversight. Closing it needs a scheduled or manual job on a host with the checkout
(the same condition `test_the_pin_matches_the_host_when_the_host_is_reachable`
tests for), which is infrastructure the repo does not have today; a runner cannot
manufacture the checkout without fetching and pinning a host, which is a release-
adjacent decision. Until that job exists, a change touching the host contract must
be verified on a box that has one — this box does, which is why the two pins show as
*passes* in every row above.

**The full bare → CI ladder**, all measured on the same tree:

```
bare          2878 / 16 / 2
+ extras      +77 passed, −13 skipped   (fastapi/crypto/numpy files)
+ digest list +1 passed,  −1 skipped    (test_no_personal_data.py)
= CI-equiv    2956 /  2 / 2
− host pins   −2 passed,  +2 skipped    (the two hermes-agent tests skip in CI)
= CI          2954 /  4 / 2
```

## Citing CI evidence — one trap

The Actions API's `head_sha` for a run can name a commit that **no longer
exists on any branch** — a push that was later rebased, or whose branch was
deleted, with the same content re-landed under a different SHA. Citing that
`head_sha` produces a broken citation, and `tests/test_cited_shas.py` will
(rightly) fail it. **Cite the SHA that is an ancestor of `main`**, and use the
run and job ids (allowlisted there) as the evidence for which run failed.
A 2026-10-17 instance of exactly this: the push that went red on all four legs
reported `head_sha cb88d47`, which is unreachable from every branch; its
content had already landed in main as `8dc725a`.

## Updating this file

At the end of a chunk, after the pre-flight runs: re-measure and let the script
write the record, then edit the four rows above and the `Read as at` SHA to match.

```
python scripts/record_suite_figures.py --measure \
    --ci-run <the branch's run id> --ci-line "<the 3.12 job log's summary line>"
```

That measures the three local variants from pytest's own summary lines, refuses a
red run or a figure that breaks the host-pin arithmetic, writes
[`suite_figures.json`](suite_figures.json) and then runs the guard. The guard
fails when this table, the CHANGELOG, the MASTER_TODO ledger, plan §11 or
`NEXT_CHUNK.md` state a triple that is neither current nor historical — which is
the drift a hand-typed figure caused on 2026-10-19, twice.
