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
| **CI, `test` job, Python 3.12** (the figure of record) | `pytest -q tests/` | **3191 passed, 4 skipped, 2 xfailed** *(**projected** from the CI-equivalent by the host-pin relation — the chunk-53 branch has no run to read yet; the record pass stamps the read figure and cites its run id here)* |
| This box, bare (`.venv311`, no extras) | `pytest -q tests/` | **3096 passed, 20 skipped, 2 xfailed** |
| This box, + the private digest list | `ENTROPICMEM_PRIVACY_DIGESTS_FILE=… pytest -q` | **3097 passed, 19 skipped, 2 xfailed** |
| This box, CI-equivalent (`.venv` 3.12 + extras + digest) | `pytest -q tests/` | **3193 passed, 2 skipped, 2 xfailed** |
| This box, Python 3.10 (`.venv310`, full suite) | `pytest -q tests/` | **3191 passed, 4 skipped, 2 xfailed** |

Read as at `6759b33` (chunk 53 — the shadow's fabrication rule narrowed to the memory
id-space, from Hermes's P0c proof run: the v3 render's episodic surface legitimately
injects `ep_*`/`mne_*` ids no v2 fact space can contain, and every proof line tripped
the hard `v3_only == 0` ceiling on them; `comparison_ids` now drops the episode space —
memory ids still map, a v3-native memory still fires, an unclassifiable id still passes
through; 2 new tests, 1 red mutation check) — **measured on the tree that became the
chunk's build commit, before it was committed** (the documented pre-stamp shape). The CI
row is **projected**, not read: no run exists for this tree yet. The previous record
(chunk 52's read pass, run `40829666854`, CI **3189 passed, 4 skipped, 2 xfailed**)
remains in the record's historical set.

Read as at `c7b3b8d` (chunk 52 — the release-readiness commands: `doctor` (the read-only
health report: the store's integrity/schema/engine, the config, the vault, the index, the
embedding state; ASCII PASS/WARN/FAIL, exit 1 on any FAIL, never writes) and `memory
upgrade` (the friendly v2→v3 cutover: `--status` read-only, the refusals — already v3, a
migration lock, a running provider, no `--yes` — before anything touches the store, the
migration with the opt-in scoped to the command and the caller's env restored after);
the command count moves 37→38 (doctor), the CLI reference + the README + the pyproject
description updated; 11 new tests, 4 red mutation checks and one recorded equivalent —
the doctor's integrity-status masking is absorbed by the unopenable-store FAIL path)
— **measured on the tree that became the chunk's build commit, before it was committed**
(the documented pre-stamp shape). The CI row is **projected**, not read: no run exists
for this tree yet. The previous record (chunk 51's read pass, run `40752588511`, CI
**3178 passed, 4 skipped, 2 xfailed**) remains in the record's historical set.

Read as at `a26dd8a` (chunk 51 — the cutover-correctness round, from Hermes's audit:
the migration guard runs only when a migration would run — an already-migrated store
opens without the env var, and an empty store is created without it — the capsule import
refuses a store newer than the build and backs the target up before replacing it, the
profile-patch gate reads the typed `core.writable_by_agent` (the key was inert), and the
stale rename record is corrected (`entropicmem_patch_core_memory` never existed); 8 new
tests, 6 red mutation checks) — **measured on the tree that became the chunk's build
commit, before it was committed** (the documented pre-stamp shape). **The CI row is read, not projected:** run `40752588511` on `4d75616` reads
**3178 passed, 4 skipped, 2 xfailed** from its `test (3.12)` job log — 13/13 jobs green
on that exact SHA, exactly what the host-pin relation had projected (the record is
re-stamped at the read pass's own commit because the allowlist entry touches `tests/`).
The previous record (chunk 50's
read pass, run `40721172839`, CI **3170 passed, 4 skipped, 2 xfailed**) remains in the
record's historical set.

Read as at `adb88bc` (chunk 50 — EM-901's upgrade drills: the committed v2.3/2.5/2.7
fixtures and the derived 2.8.1 generation driven to 3.0 — five migrations, legacy-id
resolution through the v3 read path, the old-style vault and legacy index rebuilt and
served, the capsule sync 2.8→3.0 and the pinned 3.0→2.8 limitation; the drill found and
fixed a real old-vault break — a 2.8 vault's `tags: ` null reached `Note.importance` as
`None` and killed the index rebuild; and the capsule export's `with sqlite3.connect(...)` handles never closed — on Windows that deadlocks the export's temp cleanup, the `windows-import` leg caught it; 10 new tests, 5 red mutation checks) — **measured on
the tree that became the chunk's build commit, before it was committed** (the documented
pre-stamp shape). **The CI row is read, not projected:** run `40721172839` on `1765a2d`
reads **3170 passed, 4 skipped, 2 xfailed** from its `test (3.12)` job log — 13/13 jobs
green on that exact SHA, exactly what the host-pin relation had projected from the
CI-equivalent (the record is re-stamped at the read pass's own commit because the
allowlist entry touches `tests/` — the read-as-at sha moves with it). The previous record (chunk 49's read pass, run `40693532624`, CI **3159 passed, 4 skipped,
2 xfailed**) remains in the record's historical set.

**The previous record** was EM-703 + EM-705 at `a15892e` (built as `859f12d` + `b570065` on `em-703-705-security`:
every store write screens for prompt injection in overlapping windows, the trust policy decides what a
flagged shape means, and `purge` erases the memory's vectors and schedules the vault's regeneration;
43 new tests and 30 red mutation checks, plus the figures re-stamp, the docs record and the run-id
allowlist) — measured for the tree at that commit. **CI has run for this tree, and this row's
figure is read.** The build tip's own run `39951235609` was red on the figures-guard pair alone —
the ancestry assertion (the record then still named `e4910c7`) and these four figures not yet
being in the record, the documented pre-stamp shape — so the CI row above stood **projected**
from the CI-equivalent reading by the host-pin relation; the record commits (`f7fb7a1` +
`17684d9`) then landed the figures into the record and re-stamped it, and the landing run
`39957746506` read **3135 passed, 4 skipped, 2 xfailed** from its `test (3.12)` job log on
`17684d9` — 13/13 jobs green, exactly what the host-pin relation had projected from the
CI-equivalent. Commits that touch `tests/` (this read pass's own run-id allowlist entry) are
never ancestors of a record written before them: **the companion docs-only commit that made this
tip re-stamped the record at this pass's commit** — the figure stays the landing tree's figure.
**The previous record** was EM-607 at `e4910c7` (bare 2997 / 20 / 2, digest 2998 / 19 / 2,
CI-equivalent 3094 / 2 / 2, 3.10 3092 / 4 / 2, CI 3092 / 4 / 2 **read** from run `39666424863`,
which ran on `e0f39a5`), and before it the cited-SHA reachability fix at `cf872e5` (bare 2967 / 20 / 2,
digest 2968 / 19 / 2, CI-equivalent 3064 / 2 / 2, 3.10 3062 / 4 / 2, CI 3062 / 4 / 2 read from
run `39640594895`, and the landed tip's run `39629454711` on `73bed69` read the
identical triple), and before it EM-606 at `575eb06` (bare **2943 / 20 / 2**, digest **2944 / 19 / 2**, CI-equivalent **3040 / 2 / 2**, 3.10 **3038 / 4 / 2**, CI **3038 / 4 / 2** projected); before it, EM-605 slice 2.5 at `0c40385` (bare **2943 / 19 / 2**, digest **2944 / 18 / 2**, CI-equivalent **3025 / 2 / 2**, 3.10 **3023 / 4 / 2**, CI **3023 / 4 / 2** projected); before it, slice 2.4 at `6936574` (bare **2940 / 19 / 2**, digest **2941 / 18 / 2**, CI-equivalent **3022 / 2 / 2**, 3.10 **3020 / 4 / 2**, CI **3020 / 4 / 2** projected); before it, slice 2.3 at `e08694a` (bare **2932 / 19 / 2**, digest **2933 / 18 / 2**, CI-equivalent **3014 / 2 / 2**, 3.10 **3012 / 4 / 2**, CI **3012 / 4 / 2** projected); before it, slice 2.2 at `1e5b739` (bare **2923 / 19 / 2**, digest **2924 / 18 / 2**, CI-equivalent **3005 / 2 / 2**, 3.10 **3003 / 4 / 2**, CI **3003 / 4 / 2** projected); before it, slice 2.1 at `69dc223` (bare **2911 / 19 / 2**, digest **2912 / 18 / 2**,
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
the middle column, not the total — `3137 / 2 / 2` versus `3135 / 4 / 2` is `−2 passed,
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
| `could not import 'fastapi'` | 5 | `test_graph_static.py`, `test_graph_server_v2_6.py`, `test_graph_server_titles.py`, `test_graph_server_security.py`, `test_graph_server_hardening_2.py` |
| `cryptography not installed` | 7 | `test_security_decrypt_guard.py` (5), `test_phase11.py` (2) |
| `could not import 'cryptography'` | 3 | `test_storage_modes.py` |
| `could not import 'numpy'` | 2 | `test_em_embedding_cache.py` |
| internal ops workspace | 2 | `test_v2_1_8.py`, `test_v2_2_0.py` |
| **private digest list not configured** | **1** | `tests/evals/test_no_personal_data.py` |
| **Total** | **20** | |

Those eight dependency files are **+81 passed / −16 skipped** measured
together (`43 passed, 16 skipped` bare vs `124 passed, 0 skipped` with extras).

**Why bare-with-digest shows 19, not 20.** `tests/evals/test_no_personal_data.py`
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
bare          3096 / 20 / 2
+ extras      +96 passed, −17 skipped   (fastapi/crypto/numpy files)
+ digest list +1 passed,  −1 skipped    (test_no_personal_data.py)
= CI-equiv    3193 /  2 / 2
− host pins   −2 passed,  +2 skipped    (the two hermes-agent tests skip in CI)
= CI          3191 /  4 / 2   (projected from the CI-equivalent by the host-pin relation)
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

**A merge commit that touches `tests/` reddens the ancestry rule by construction.** The
rule wants the newest commit on the suite surface to be an *ancestor* of the recorded SHA,
and a merge commit is never an ancestor of the commits it merges — even when it changes no
test count. So a landing that merges a branch touching `tests/` takes **one extra docs-only
commit after the merge** that re-stamps `suite_figures.json`'s `sha` and this page's
`Read as at` at the merge commit; the re-stamp is docs, so it does not move the suite
surface, and the pair is green together. The history alternates exactly this way
(`b99437a` red → `55eb8c5` green; `0705d21` red → `aa9a451` green).

**When a read figure replaces a projection, flip the prose in the same commit.** Two
landings' worth of drift came from doing it in halves: the CI row said "read" while the
paragraph under the table still said "CI has not run for it … projected". Both statements
sit on this page, so the guard cannot catch the contradiction — only reading it can.

That measures the four local variants from pytest's own summary lines, refuses a
red run or a figure that breaks the host-pin arithmetic, writes
[`suite_figures.json`](suite_figures.json) and then runs the guard. The guard
fails when this table, the CHANGELOG, the MASTER_TODO ledger, plan §11 or
`NEXT_CHUNK.md` state a triple that is neither current nor historical, or when the
newest commit touching the suite surface is not an ancestor of the measured SHA
(the security-hardening commits added 17 tests after `5258b46` and every guard
stayed green) — which is the drift a hand-typed figure caused on 2026-10-19, twice.
