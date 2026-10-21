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
        "--seed-historical",
        action="store_true",
        help="bootstrap: allowlist every triple currently in the docs as historical",
    )
    ap.add_argument("--bare-python", default=str(REPO / ".venv311/bin/python"))
    ap.add_argument("--ciequiv-python", default=str(REPO / ".venv/bin/python"))
    ap.add_argument("--python310-python", default=str(REPO / ".venv310/bin/python"))
    ap.add_argument("--digests-file", default=os.environ.get("ENTROPICMEM_PRIVACY_DIGESTS_FILE"))
    args = ap.parse_args(argv)

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
