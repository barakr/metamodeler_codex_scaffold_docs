"""CLI entrypoint for metamodeler scaffold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from metamodeler.designs import DOEPlanError, plan_points, render_plan_preview
from metamodeler.spec import format_validation_error, load_and_validate_modelspec


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        print(f"Spec file not found: {path}")
        return None
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}")
        return None


def _load_and_validate(path: Path):
    payload = _load_json(path)
    if payload is None:
        return None, 1

    try:
        spec = load_and_validate_modelspec(payload)
    except ValidationError as exc:
        print(format_validation_error(exc))
        return None, 1

    return spec, 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mm", description="Metamodeler CLI")
    parser.add_argument("--version", action="store_true", help="Show scaffold version")

    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser("validate", help="Validate a ModelSpec JSON file")
    validate_parser.add_argument("spec", help="Path to ModelSpec JSON")

    plan_parser = subparsers.add_parser("plan", help="Plan DOE points from a ModelSpec JSON file")
    plan_parser.add_argument("spec", help="Path to ModelSpec JSON")

    return parser


def _validate_command(spec_path: Path) -> int:
    spec, code = _load_and_validate(spec_path)
    if code != 0:
        return code

    print(
        "Spec validation passed: "
        f"model={spec.model.name}, strategy={spec.design.strategy}, adapter={spec.adapter.id}"
    )
    return 0


def _plan_command(spec_path: Path) -> int:
    spec, code = _load_and_validate(spec_path)
    if code != 0:
        return code

    try:
        points = plan_points(spec)
    except DOEPlanError as exc:
        print(f"DOE planning failed: {exc}")
        return 1

    print(render_plan_preview(points))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        print("metamodeler 0.1.0")
        return 0

    if args.command == "validate":
        return _validate_command(Path(args.spec))
    if args.command == "plan":
        return _plan_command(Path(args.spec))

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
