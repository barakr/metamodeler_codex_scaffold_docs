"""
Synopsis:
Toy executable program used for local-run integration tests.
This toy program takes two numbers as input, computes their sum and product,
and writes the results to a JSON file in the specified output directory.

The program is designed to be simple and self-contained, making it ideal for testing
the integration of the Metamodeler framework with external executables.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", type=float, required=True)
    parser.add_argument("--b", type=float, required=True)
    parser.add_argument("--run-dir", type=str, required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = run_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "y": [args.a + args.b, args.a * args.b],
        "inputs": {"a": args.a, "b": args.b},
    }
    (out_dir / "y.json").write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
