"""CLI entrypoint for metamodeler scaffold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from metamodeler.spec import format_validation_error, load_and_validate_modelspec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mm", description="Metamodeler CLI")
    parser.add_argument("--version", action="store_true", help="Show scaffold version")

    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser("validate", help="Validate a ModelSpec JSON file")
    validate_parser.add_argument("spec", help="Path to ModelSpec JSON")

    return parser


def _validate_command(spec_path: Path) -> int:
    try:
        payload = json.loads(spec_path.read_text())
    except FileNotFoundError:
        print(f"Spec file not found: {spec_path}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in {spec_path}: line {exc.lineno}, column {exc.colno}: {exc.msg}")
        return 1

    try:
        spec = load_and_validate_modelspec(payload)
    except ValidationError as exc:
        print(format_validation_error(exc))
        return 1

    print(
        "Spec validation passed: "
        f"model={spec.model.name}, strategy={spec.design.strategy}, adapter={spec.adapter.id}"
    )
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        print("metamodeler 0.1.0")
        return 0

    if args.command == "validate":
        return _validate_command(Path(args.spec))

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
