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
| **CI, `test` job, Python 3.12** (the figure of record) | `pytest -q tests/` | **3023 passed, 4 skipped, 2 xfailed** *(projected from this box's CI-equivalent run by the host-pin relation — CI has not run for this landing: it is committed locally and not pushed, so there is no run id to cite)* |
| This box, bare (`.venv311`, no extras) | `pytest -q tests/` | **2943 passed, 19 skipped, 2 xfailed** |
| This box, + the private digest list | `ENTROPICMEM_PRIVACY_DIGESTS_FILE=… pytest -q` | **2944 passed, 18 skipped, 2 xfailed** |
| This box, CI-equivalent (`.venv` 3.12 + extras + digest) | `pytest -q tests/` | **3025 passed, 2 skipped, 2 xfailed** |
| This box, Python 3.10 (`.venv310`, full suite) | `pytest -q tests/` | **3023 passed, 4 skipped, 2 xfailed** |

Read as at `0c40385` (EM-605 slice 2.5 — the 5k-node export AC and the body read it
found) — measured for the tree at that commit. **CI has not run for it:** the commit is local and unpushed, so
the CI figure is **projected** from the CI-equivalent run by the host-pin relation below; no run
id is cited and no job is claimed green. **The previous record** was slice 2.4 at `6936574` (bare **2940 / 19 / 2**, digest **2941 / 18 / 2**, CI-equivalent **3022 / 2 / 2**, 3.10 **3020 / 4 / 2**, CI **3020 / 4 / 2** projected); before it, slice 2.3 at `e08694a` (bare **2932 / 19 / 2**, digest **2933 / 18 / 2**, CI-equivalent **3014 / 2 / 2**, 3.10 **3012 / 4 / 2**, CI **3012 / 4 / 2** projected); before it, slice 2.2 at `1e5b739` (bare **2923 / 19 / 2**, digest **2924 / 18 / 2**, CI-equivalent **3005 / 2 / 2**, 3.10 **3003 / 4 / 2**, CI **3003 / 4 / 2** projected); before it, slice 2.1 at `69dc223` (bare **2911 / 19 / 2**, digest **2912 / 18 / 2**,
CI-equivalent **2993 / 2 / 2**, 3.10 **2991 / 4 / 2**, CI **2991 / 4 / 2** projected); before it,
chunk 43 at `5258b46` —
**confirmed green on that exact SHA:** run **`39251351180`** (a `push` to `em-605-followups`),
all 11 jobs success, `identity-guard` and `windows-import` included (1762 passed there), CI's
3.12 count **2954 / 4 / 2**, all four legs of that matrix identical and read from the job log.
The run before it was **`39236004212`** (the
`em-605-graph-split` push at `2fd7812`: all 11 jobs success, `identity-guard` and
`windows-import` included, CI 3.12 **2936 / 4 / 2** on all four legs), re-verified on `main`
by run **`39237280578`**; before it `e6647e7` (run `39231027295`), `adb1439` (run
`39226716232`) and `4cde953` (run `39219386624`). CI's figure is **read from the job log**,
never assumed: `gh run view <run-id> --log`; at that time all four CI legs (3.10–3.13)
reported the identical triple. **The gap between this box's CI-equivalent reading and CI is in
the middle column, not the total — `3025 / 2 / 2` versus `3023 / 4 / 2` is `−2 passed,
+2 skipped`, the two hermes-agent host pins that pass here and skip in CI**, the same pair the
ladder below walks. **The five rows in this table are the figures of record and live in exactly
one other place, [`suite_figures.json`](suite_figures.json), which
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

**Bare's 19 skips** — the same four above (2 of them), plus the optional
dependencies the bare venv does not install. Measured directly, file by file:

| Reason | Skips | Files |
|---|---|---|
| `could not import 'fastapi'` | 4 | `test_graph_static.py`, `test_graph_server_v2_6.py`, `test_graph_server_titles.py`, `test_graph_server_security.py` |
| `cryptography not installed` | 7 | `test_security_decrypt_guard.py` (5), `test_phase11.py` (2) |
| `could not import 'cryptography'` | 3 | `test_storage_modes.py` |
| `could not import 'numpy'` | 2 | `test_em_embedding_cache.py` |
| internal ops workspace | 2 | `test_v2_1_8.py`, `test_v2_2_0.py` |
| **private digest list not configured** | **1** | `tests/evals/test_no_personal_data.py` |
| **Total** | **19** | |

Those eight dependency files are **+81 passed / −16 skipped** measured
together (`43 passed, 16 skipped` bare vs `124 passed, 0 skipped` with extras).

**Why bare-with-digest shows 18, not 19.** `tests/evals/test_no_personal_data.py`
skips when the private digest list is absent and **passes** when it is present —
so pointing `ENTROPICMEM_PRIVACY_DIGESTS_FILE` at the list converts exactly one
skip into one pass. **This is by design, not a flake:** the test is the privacy
collision check, it must not run blind, and the two numbers are meant to be read
as a pair. The dev box does not have the list at the default path
(`~/.config/entropicmem/privacy-digests.txt` is absent); it lives at
`~/Documents/EntropicMem Dev docs/privacy-digests.txt`.

**Python 3.10 is a supported target, and the full suite runs there before a landing.**
`requires-python = ">=3.10"` and the `test` matrix runs 3.10–3.14, so 3.10 is not
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
*passes* in the CI-equivalent 3.12 row above; the 3.10 venv has no host checkout, so
its row shows the same four skips as CI.

**The full bare → CI ladder**, all measured on the same tree:

```
bare          2943 / 19 / 2
+ extras      +81 passed, −16 skipped   (fastapi/crypto/numpy files)
+ digest list +1 passed,  −1 skipped    (test_no_personal_data.py)
= CI-equiv    3025 /  2 / 2
− host pins   −2 passed,  +2 skipped    (the two hermes-agent tests skip in CI)
= CI          3023 /  4 / 2   (projected; not run — the landing is unpushed)
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

At the end of a chunk: **commit the code and its tests first**, then measure the
clean tree at that commit, then edit the five rows above and the `Read as at` SHA
to match, and commit the docs. Measuring an uncommitted tree stamps a SHA that
does not contain what was measured; the guard's ancestry check rejects it.

```
python scripts/record_suite_figures.py --measure \
    --ci-run <the branch's run id> --ci-line "<the 3.12 job log's summary line>"
```

For a landing that is committed locally and not pushed, pass `--ci-run ""` with no
`--ci-line`: an **explicit** empty value clears the run id and records
`ci_projected: true`, while an omitted flag inherits the previous run id (the usual
re-measure after reading CI). A projected record must say so in the CI row, and a
read one must not — the guard checks both directions.

That measures the four local variants from pytest's own summary lines, refuses a
red run or a figure that breaks the host-pin arithmetic, writes
[`suite_figures.json`](suite_figures.json) and then runs the guard. The guard
fails when this table, the CHANGELOG, the MASTER_TODO ledger, plan §11 or
`NEXT_CHUNK.md` state a triple that is neither current nor historical, or when the
newest commit touching the suite surface is not an ancestor of the measured SHA
(the security-hardening commits added 17 tests after `5258b46` and every guard
stayed green) — which is the drift a hand-typed figure caused on 2026-10-19, twice.
