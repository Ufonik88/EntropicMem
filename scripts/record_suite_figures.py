#!/usr/bin/env python3
"""Record the suite's figures of record — measured, never typed.

Why this exists: a chunk's figures were hand-typed into five places (the
BASELINE table, the CHANGELOG entry, the MASTER_TODO ledger row, the plan §11
rows and the NEXT_CHUNK pass) and one pass wrote them all one low, because it
measured the tree *before* the last test existed. CI's own read caught it. The
fix is not the corrected numbers; it is that the numbers should be measured once,
recorded once, and *checked* against the prose.

`docs/plan/suite_figures.json` is that record. It is written only by this script
and read by `tests/test_suite_figures.py`, which fails when BASELINE, the
CHANGELOG, the ledger, plan §11 or NEXT_CHUNK disagree with it.

The figures come from pytest's own summary line, not from arithmetic:

    python scripts/record_suite_figures.py --measure \\
        --ci-run 39236004212 --ci-line "2936 passed, 4 skipped, 2 xfailed, 4 warnings in 311.86s"

`--measure` runs the three local variants and parses each summary line; `--ci-line`
takes the line read out of the CI job log (paste it verbatim). Both refuse a
non-zero `failed`: **failed is always 0 on a green run**, so a figure that carries
one is not a figure of record.

Options:
  --measure / --bare "a b c" / --digest ... / --ci-equiv ...   where the triples come from
  --ci-line "<pytest summary line>" or --ci "a b c"             the CI figure
  --sha <ref>        the commit the figures were measured for (default HEAD)
  --ci-run <id>      the GitHub Actions run id the CI figure was read from
  --check            verify the on-disk record against a fresh measurement; write nothing
  --bare-python / --ciequiv-python / --python310-python   interpreter paths (this box's venvs)

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doc_figures  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RECORD = doc_figures.RECORD_PATH
GUARD = "tests/test_suite_figures.py"

VARIANTS = ("bare", "digest", "ci_equiv", "python310")

#: The two hermes-agent host pins pass on a dev box and skip in CI, so CI's
#: triple is this box's CI-equivalent minus 2 passed, plus 2 skipped. Pinned here
#: rather than assumed: if the host-pin situation ever changes, this check fails
#: loudly instead of letting a stale relation back into the docs.
HOST_PINS = (2, 2)

_SUMMARY = doc_figures.TRIPLE_RE


def parse_triple(text: str) -> tuple:
    if "/" in text and "passed" not in text:
        parts = [p.strip() for p in text.split("/")]
        if len(parts) != 3:
            raise SystemExit(f"--triple wants 'passed / skipped / xfailed', got {text!r}")
        return tuple(int(p) for p in parts)
    return doc_figures.parse_summary(text)


def run_variant(name: str, python: str, digests: str | None) -> tuple:
    env = {k: v for k, v in os.environ.items()}
    for key in ("ENTROPICMEM_MEMORY_DB", "ENTROPICMEM_VAULT_PATH", "ENTROPICMEM_INDEX_DB"):
        env.pop(key, None)
    if name in ("digest", "ci_equiv", "python310"):
        if digests:
            env["ENTROPICMEM_PRIVACY_DIGESTS_FILE"] = digests
    else:
        env.pop("ENTROPICMEM_PRIVACY_DIGESTS_FILE", None)

    print(f"measuring {name} ({python}) ...", flush=True)
    proc = subprocess.run(
        [python, "-m", "pytest", "-q", "tests/"],
        cwd=REPO, capture_output=True, text=True, env=env,
    )
    return doc_figures.parse_summary(proc.stdout + proc.stderr)


def load(path: Path) -> dict:
    if not path.exists():
        return {"sha": "", "ci_run": "", "current": {}, "historical": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _add_delta(old, delta):
    """Element-wise addition of a (passed, skipped, xfailed) delta."""
    return [old[0] + delta[0], old[1] + delta[1], old[2] + delta[2]]


def derive_triples(old: dict, new_ci_equiv: tuple) -> dict:
    """Derive bare/python310/digest from the old record by the measured ci_equiv delta.

    bare_new   = bare_old   + (ci_equiv_new - ci_equiv_old)
    python310  = python310_old + (ci_equiv_new - ci_equiv_old)
    digest_new = (bare_new_passed + 1, bare_new_skipped - 1, bare_new_xfailed)

    Refuses (SystemExit) when the base record has no ci_equiv or any derived
    triple would go negative.
    """
    old_current = old.get("current", {})
    old_ci_equiv = old_current.get("ci_equiv")
    if not old_ci_equiv:
        raise SystemExit(
            "refusing: the on-disk record has no ci_equiv figure to derive from. "
            "Re-measure with --measure first, or supply --ci-equiv explicitly."
        )
    delta = tuple(n - o for n, o in zip(new_ci_equiv, old_ci_equiv))

    bare_new = _add_delta(old_current["bare"], delta)
    py310_old = old_current.get("python310", old_current["bare"])
    py310_new = _add_delta(py310_old, delta)
    digest_new = [bare_new[0] + 1, bare_new[1] - 1, bare_new[2]]

    result = {
        "bare": bare_new,
        "digest": digest_new,
        "ci_equiv": list(new_ci_equiv),
        "python310": py310_new,
    }
    _check_non_negative(result)
    return result


def _check_non_negative(current: dict) -> None:
    """Refuse (SystemExit) when any derived count is negative."""
    for name in ("bare", "digest", "ci_equiv", "ci", "python310"):
        triple = current.get(name)
        if triple is None:
            continue
        for i, label in enumerate(("passed", "skipped", "xfailed")):
            if triple[i] < 0:
                raise SystemExit(
                    f"refusing: derived {name} {label} would be negative ({triple[i]}). "
                    "The base record or the measured ci_equiv is inconsistent with the delta."
                )


def _check_ladder(current: dict) -> None:
    """The two existing ladder checks, shared by derive and measure paths.

    digest == bare + (1, -1, 0)  and  ci == ci_equiv - HOST_PINS.
    """
    bare = tuple(current["bare"])
    digest = tuple(current["digest"])
    ci_equiv = tuple(current["ci_equiv"])
    ci = tuple(current["ci"])
    if digest != (bare[0] + 1, bare[1] - 1, bare[2]):
        raise SystemExit(
            f"refusing: the digest reads {digest} but bare is {bare}; enabling the digest "
            "list must convert exactly one skip into one pass (test_no_personal_data.py)."
        )
    expected_ci = (ci_equiv[0] - HOST_PINS[0], ci_equiv[1] + HOST_PINS[1], ci_equiv[2])
    if ci != expected_ci:
        raise SystemExit(
            f"refusing: CI reads {ci} but this box's CI-equivalent is {ci_equiv}, which the "
            f"host-pin relation ({HOST_PINS[0]} passed -> skipped) makes {expected_ci}. "
            "One of the two was measured on a different tree."
        )


def derive_record(old: dict, new_ci_equiv: tuple, ci_line: str | None, ci_run: str | None) -> dict:
    """Build the full new record from the old one and a measured ci_equiv.

    * bare / python310 / digest are derived by the measured delta (derive_triples).
    * ci comes from --ci-line when given, else the host-pin projection.
    * `derived: true`; `ci_projected` true unless a real run backs a read ci line.
    * sha is the caller's concern: derive_record never invents one, it inherits
      old["sha"] and the CLI overwrites it with the actual HEAD.
    """
    current = derive_triples(old, new_ci_equiv)

    if ci_line:
        current["ci"] = list(parse_triple(ci_line))
        projected = not ci_run
    else:
        current["ci"] = [
            new_ci_equiv[0] - HOST_PINS[0],
            new_ci_equiv[1] + HOST_PINS[1],
            new_ci_equiv[2],
        ]
        projected = True

    _check_ladder(current)
    _check_non_negative(current)

    historical = {tuple(t) for t in old.get("historical", [])}
    historical |= {tuple(v) for v in old.get("current", {}).values()}
    historical -= {tuple(v) for v in current.values()}

    return {
        "sha": old.get("sha", ""),
        "ci_run": ci_run if ci_run is not None else old.get("ci_run", ""),
        "ci_projected": projected,
        "derived": True,
        "comment": old.get("comment", ""),
        "current": {k: current[k] for k in ("bare", "digest", "ci_equiv", "ci", "python310")},
        "historical": sorted(list(t) for t in historical),
    }


def _run_derive(args) -> int:
    """The --derive-from-record mode: measure only ci_equiv, derive the rest.

    Refuses (SystemExit, writes nothing) when there is no usable base record.
    Exits 1 with DRIFT when --check and the on-disk counts disagree with a fresh
    measurement, so the mode cannot launder drift.
    """
    old = load(RECORD)
    if not old.get("current"):
        raise SystemExit("refusing: no usable base record on disk. Run --measure first.")

    print("=== derive-from-record ===")
    if args.ci_equiv:
        new_ci_equiv = parse_triple(args.ci_equiv)
        print(f"  ci_equiv given: {new_ci_equiv[0]} / {new_ci_equiv[1]} / {new_ci_equiv[2]}")
    else:
        print(f"measuring ci_equiv ({args.ciequiv_python}) ...", flush=True)
        new_ci_equiv = run_variant("ci_equiv", args.ciequiv_python, args.digests_file)
        print(f"  ci_equiv: {new_ci_equiv[0]} / {new_ci_equiv[1]} / {new_ci_equiv[2]}")

    sha = args.sha or subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()

    record = derive_record(old, new_ci_equiv, args.ci_line, args.ci_run)
    record["sha"] = sha

    if args.check:
        drift = {
            k: (old["current"].get(k), record["current"][k])
            for k in record["current"]
            if old["current"].get(k) != record["current"][k]
        }
        if drift or old.get("sha") != sha:
            print("DRIFT:", json.dumps({"sha": (old.get("sha"), sha), "triples": drift}, indent=2))
            return 1
        print(f"record matches the derivation at {sha}")
        return 0

    RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {RECORD.relative_to(REPO)} at {sha} (derived, historical: {len(record['historical'])})")

    print("=== the guard ===")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", GUARD, "--no-header"],
        cwd=REPO, text=True,
    )
    return proc.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in VARIANTS:
        ap.add_argument(f"--{name.replace('_', '-')}", default=None,
                        help=f"the {name} triple: 'passed / skipped / xfailed' or a pytest summary line")
    ap.add_argument("--measure", action="store_true", help="run the three local variants")
    ap.add_argument("--ci", default=None, help="the CI triple: 'passed / skipped / xfailed'")
    ap.add_argument("--ci-line", default=None, help="the CI pytest summary line, verbatim from the job log")
    ap.add_argument("--sha", default=None, help="the measured commit (default HEAD)")
    ap.add_argument("--ci-run", default=None, help="the GitHub Actions run id the CI figure came from")
    ap.add_argument("--check", action="store_true", help="verify, write nothing")
    ap.add_argument(
        "--derive-from-record", action="store_true",
        help="measure only ci_equiv locally; derive bare, python310 and digest from the on-disk record",
    )
    ap.add_argument(
        "--seed-historical",
        action="store_true",
        help="bootstrap: allowlist every triple currently in the docs as historical",
    )
    ap.add_argument("--bare-python", default=str(REPO / ".venv311/bin/python"))
    ap.add_argument("--ciequiv-python", default=str(REPO / ".venv/bin/python"))
    ap.add_argument("--python310-python", default=str(REPO / ".venv310/bin/python"))
    ap.add_argument("--digests-file", default=os.environ.get("ENTROPICMEM_PRIVACY_DIGESTS_FILE"))
    args = ap.parse_args(argv)

    if args.derive_from_record:
        return _run_derive(args)

    current: dict = {}
    print("=== local variants ===")
    for name in VARIANTS:
        given = getattr(args, name)
        if given:
            print(f"{name}:")
            current[name] = parse_triple(given)
        elif args.measure:
            python = {
                "bare": args.bare_python,
                "digest": args.bare_python,
                "ci_equiv": args.ciequiv_python,
                "python310": args.python310_python,
            }[name]
            current[name] = run_variant(name, python, args.digests_file)
        else:
            raise SystemExit(f"{name} not given and --measure not set")

    print("=== the CI figure ===")
    projected = False
    if args.ci_line:
        current["ci"] = parse_triple(args.ci_line)
    elif args.ci:
        current["ci"] = parse_triple(args.ci)
    else:
        # Not read yet: derive it from this box's CI-equivalent by the host-pin
        # relation and say so. The landing stamps the read figure afterwards.
        ci_equiv = current["ci_equiv"]
        current["ci"] = (
            ci_equiv[0] - HOST_PINS[0],
            ci_equiv[1] + HOST_PINS[1],
            ci_equiv[2],
        )
        projected = True
        print(f"  no --ci given: PROJECTED {current['ci'][0]} / {current['ci'][1]} / {current['ci'][2]} "
              "from the CI-equivalent run by the host-pin relation")
    # "projected" means: not backed by a run id we actually read. A CI figure
    # typed in without a run to check it against is a projection however it was
    # obtained, and the docs must say so.
    if not args.ci_run:
        projected = True

    # The arithmetic that would have caught the lost test: CI must be this box's
    # CI-equivalent moved by exactly the host pins, and the digest run exactly one
    # skip converted to a pass against bare.
    bare, digest, ci_equiv, ci = (current[k] for k in ("bare", "digest", "ci_equiv", "ci"))
    expected_ci = (ci_equiv[0] - HOST_PINS[0], ci_equiv[1] + HOST_PINS[1], ci_equiv[2])
    if tuple(ci) != expected_ci:
        raise SystemExit(
            f"refusing: CI reads {ci} but this box's CI-equivalent is {ci_equiv}, which the "
            f"host-pin relation ({HOST_PINS[0]} passed -> skipped) makes {expected_ci}. "
            "One of the two was measured on a different tree. If the host-pin situation really "
            "changed, update HOST_PINS in this script and record why in BASELINE.md."
        )
    if tuple(digest) != (bare[0] + 1, bare[1] - 1, bare[2]):
        raise SystemExit(
            f"refusing: the digest run reads {digest} but bare is {bare}; enabling the digest "
            "list must convert exactly one skip into one pass (test_no_personal_data.py)."
        )
    print(f"  arithmetic agrees: CI {ci} == CI-equiv {ci_equiv} - {HOST_PINS[0]} passed + {HOST_PINS[1]} skipped")

    sha = args.sha or subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()

    if args.check:
        old = load(RECORD)
        drift = {k: (old["current"].get(k), current[k]) for k in current if old["current"].get(k) != list(current[k])}
        if drift or old.get("sha") != sha:
            print("DRIFT:", json.dumps({"sha": (old.get("sha"), sha), "triples": drift}, indent=2))
            return 1
        print(f"record matches the measurement at {sha}")
        return 0

    old = load(RECORD)
    historical = {tuple(t) for t in old.get("historical", [])}
    historical |= {tuple(v) for v in old.get("current", {}).values()}
    if args.seed_historical:
        # One-time bootstrap: the docs are full of superseded triples from
        # earlier landings, and this is a new guard. Harvest them so the record
        # starts green; from here on, a triple that is not current and was never
        # a figure of record is a drift the guard must fail on.
        seeded = doc_figures.harvest()
        print(f"  seeding {len(seeded)} triples from the docs as historical")
        historical |= seeded
    historical -= {tuple(v) for v in current.values()}

    record = {
        "sha": sha,
        # An omitted --ci-run inherits (the usual re-measure after a CI read);
        # an explicit empty one clears it, which is how a projected landing is
        # recorded without silently citing the previous run id against it.
        "ci_run": args.ci_run if args.ci_run is not None else old.get("ci_run", ""),
        "ci_projected": projected,
        "comment": (
            "Written only by scripts/record_suite_figures.py, from pytest summary lines. "
            "tests/test_suite_figures.py fails when BASELINE, the CHANGELOG, the MASTER_TODO "
            "ledger, plan §11 or NEXT_CHUNK state a triple that is neither current nor historical."
        ),
        "current": {k: list(current[k]) for k in ("bare", "digest", "ci_equiv", "ci", "python310")},
        "historical": sorted(list(t) for t in historical),
    }
    RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {RECORD.relative_to(REPO)} at {sha} (historical: {len(record['historical'])})")

    print("=== the guard ===")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", GUARD, "--no-header"],
        cwd=REPO, text=True,
    )
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
