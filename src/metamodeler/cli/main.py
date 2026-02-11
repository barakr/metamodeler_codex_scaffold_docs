"""CLI entrypoint for metamodeler scaffold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from metamodeler.adapters import resolve_adapter
from metamodeler.designs import DOEPlanError, plan_points, render_plan_preview
from metamodeler.meta import build_ir_from_metamodel_spec
from metamodeler.runners import LocalProcessRunner
from metamodeler.spec import (
    MetaModelSpec,
    SurrogateSpec,
    format_validation_error,
    load_and_validate_modelspec,
)
from metamodeler.storage import (
    list_registered_runs,
    persist_ir_artifact,
    persist_run,
    show_registered_run,
)
from metamodeler.surrogates import eval_surrogate, fit_surrogate

REPO_ROOT = Path(__file__).resolve().parents[3]


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
        return None, None, 1

    try:
        spec = load_and_validate_modelspec(payload)
    except ValidationError as exc:
        print(format_validation_error(exc))
        return None, None, 1

    return payload, spec, 0


def _load_and_validate_surrogate(path: Path):
    payload = _load_json(path)
    if payload is None:
        return None, 1
    try:
        spec = SurrogateSpec.model_validate(payload)
    except ValidationError as exc:
        print(format_validation_error(exc))
        return None, 1
    return spec, 0


def _load_and_validate_metamodel(path: Path):
    payload = _load_json(path)
    if payload is None:
        return None, 1
    try:
        spec = MetaModelSpec.model_validate(payload)
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

    run_parser = subparsers.add_parser("run", help="Execute all planned runs for a ModelSpec")
    run_parser.add_argument("spec", help="Path to ModelSpec JSON")

    runs_parser = subparsers.add_parser("runs", help="Inspect run registry")
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command")
    runs_subparsers.add_parser("list", help="List known run ids")
    show_parser = runs_subparsers.add_parser("show", help="Show one run record")
    show_parser.add_argument("run_id", help="Run ID")

    surrogate_parser = subparsers.add_parser("surrogate", help="Surrogate commands")
    surrogate_subparsers = surrogate_parser.add_subparsers(dest="surrogate_command")
    surrogate_fit = surrogate_subparsers.add_parser("fit", help="Train a surrogate")
    surrogate_fit.add_argument("spec", help="Path to SurrogateSpec JSON")
    surrogate_eval = surrogate_subparsers.add_parser("eval", help="Evaluate a fitted surrogate")
    surrogate_eval.add_argument("spec", help="Path to SurrogateSpec JSON")
    surrogate_eval.add_argument("--inputs", required=True, help="JSON dict of input arrays")
    surrogate_eval.add_argument("--n", type=int, default=1000, help="Number of samples")

    meta_parser = subparsers.add_parser("meta", help="Metamodel commands")
    meta_subparsers = meta_parser.add_subparsers(dest="meta_command")
    meta_build = meta_subparsers.add_parser("build", help="Build metamodel IR artifact")
    meta_build.add_argument("spec", help="Path to MetaModelSpec JSON")

    return parser


def _validate_command(spec_path: Path) -> int:
    _, spec, code = _load_and_validate(spec_path)
    if code != 0:
        return code

    print(
        "Spec validation passed: "
        f"model={spec.model.name}, strategy={spec.design.strategy}, adapter={spec.adapter.id}"
    )
    return 0


def _plan_command(spec_path: Path) -> int:
    _, spec, code = _load_and_validate(spec_path)
    if code != 0:
        return code

    try:
        points = plan_points(spec)
    except DOEPlanError as exc:
        print(f"DOE planning failed: {exc}")
        return 1

    print(render_plan_preview(points))
    return 0


def _run_command(spec_path: Path) -> int:
    payload, spec, code = _load_and_validate(spec_path)
    if code != 0:
        return code

    try:
        points = plan_points(spec)
    except DOEPlanError as exc:
        print(f"DOE planning failed: {exc}")
        return 1

    adapter = resolve_adapter(spec)
    runner = LocalProcessRunner()

    completed = 0
    for point in points:
        run_id_hint = f"{spec.model.name}_{completed + 1}"
        print(f"Running point {completed + 1}/{len(points)} ({run_id_hint}): {point}")

        temp_run_dir = Path(spec.storage.root) / "_active" / run_id_hint
        temp_run_dir.mkdir(parents=True, exist_ok=True)

        materialization = adapter.materialize_inputs(
            spec=spec,
            point=point,
            run_dir=temp_run_dir,
            repo_root=REPO_ROOT,
        )
        result = runner.run(materialization=materialization, run_dir=temp_run_dir)

        status = "success" if result.returncode == 0 else "failed"
        outputs = {}
        if result.returncode == 0:
            outputs = adapter.parse_outputs(spec=spec, run_dir=temp_run_dir)

        stored = persist_run(
            spec_payload=payload,
            spec=spec,
            point=point,
            outputs=outputs,
            status=status,
            returncode=result.returncode,
            stdout_path=result.stdout_path,
            stderr_path=result.stderr_path,
        )
        print(f"Stored run: {stored.run_id}")

        if result.returncode != 0:
            print(f"Run failed with return code {result.returncode}. See: {result.stderr_path}")
            return 1

        completed += 1

    print(f"Run complete: {completed} successful runs")
    return 0


def _runs_list_command() -> int:
    items = list_registered_runs()
    if not items:
        print("No runs registered")
        return 0

    print(f"Registered runs: {len(items)}")
    for item in items:
        print(f"- {item['run_id']}")
    return 0


def _runs_show_command(run_id: str) -> int:
    try:
        payload = show_registered_run(run_id)
    except ValueError as exc:
        print(str(exc))
        return 1

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _surrogate_fit_command(spec_path: Path) -> int:
    spec, code = _load_and_validate_surrogate(spec_path)
    if code != 0:
        return code

    artifact = fit_surrogate(spec)
    print(
        "Surrogate artifact stored: "
        f"artifact_id={artifact['artifact_id']} path={artifact['artifact_path']}"
    )
    return 0


def _surrogate_eval_command(spec_path: Path, inputs_json: str, n: int) -> int:
    spec, code = _load_and_validate_surrogate(spec_path)
    if code != 0:
        return code

    try:
        inputs_payload = json.loads(inputs_json)
    except json.JSONDecodeError as exc:
        print(f"Invalid --inputs JSON: line {exc.lineno}, col {exc.colno}: {exc.msg}")
        return 1

    result = eval_surrogate(spec=spec, inputs_payload=inputs_payload, n=n)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _meta_build_command(spec_path: Path) -> int:
    spec, code = _load_and_validate_metamodel(spec_path)
    if code != 0:
        return code

    ir = build_ir_from_metamodel_spec(spec)
    artifact = persist_ir_artifact(ir)
    print(
        "Metamodel IR artifact stored: "
        f"artifact_id={artifact['artifact_id']} ir_path={artifact['ir_path']}"
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
    if args.command == "plan":
        return _plan_command(Path(args.spec))
    if args.command == "run":
        return _run_command(Path(args.spec))
    if args.command == "runs" and args.runs_command == "list":
        return _runs_list_command()
    if args.command == "runs" and args.runs_command == "show":
        return _runs_show_command(args.run_id)
    if args.command == "surrogate" and args.surrogate_command == "fit":
        return _surrogate_fit_command(Path(args.spec))
    if args.command == "surrogate" and args.surrogate_command == "eval":
        return _surrogate_eval_command(Path(args.spec), args.inputs, args.n)
    if args.command == "meta" and args.meta_command == "build":
        return _meta_build_command(Path(args.spec))

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
