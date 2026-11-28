"""``python -m evals.multi_writer`` — the two-writers-one-store benchmark.

Prints the markdown table and, with ``--json``, writes the same payload. Exit
status is 0 on a completed run whatever the numbers say: this is a measurement
of a write protocol, not a gate. (``evals run --suite ci`` remains the gate.)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "plugins" / "entropicmem" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from evals.multi_writer.bench import render_markdown, run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.multi_writer",
        description="Two writers, one store: which value does the pipeline serve?",
    )
    parser.add_argument("--keys", type=int, default=12, help="distinct fact slots (max 12)")
    parser.add_argument("--seed", type=int, default=60828, help="corpus seed")
    parser.add_argument("--json", default=None, help="write the payload to this path")
    args = parser.parse_args(argv)

    payload = run(seed=args.seed, keys=args.keys)
    print(render_markdown(payload))
    print()
    print(
        f"seed {payload['seed']}, {payload['keys']} keys, queries asked "
        f"{payload['ask_after_days']} days after the last write."
    )
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
