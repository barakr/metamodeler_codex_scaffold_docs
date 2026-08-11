"""CLI entrypoint for bayesian-metamodeling scaffold."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from bayesian_metamodeling.adapters import resolve_adapter
from bayesian_metamodeling.config import diagnose, format_diagnose_report, setup
from bayesian_metamodeling.config.diagnose import diagnose_to_json
from bayesian_metamodeling.designs import DOEPlanError, plan_points, render_plan_preview
from bayesian_metamodeling.meta import build_ir_from_metamodel_spec, sample_metamodel
from bayesian_metamodeling.runners import LocalProcessRunner
from bayesian_metamodeling.spec import (
    MetaModelSpec,
    SurrogateSpec,
    format_validation_error,
    load_and_validate_modelspec,
)
from bayesian_metamodeling.storage import (
    list_meta_ir_artifacts,
    list_meta_samples,
    list_registered_runs,
    list_surrogate_artifacts,
    persist_ir_artifact,
    persist_sweep,
    show_registered_run,
)
from bayesian_metamodeling.surrogates import eval_surrogate, fit_surrogate

REPO_ROOT = Path(__file__).resolve().parents[3]

_MAX_INPUTS_JSON_BYTES = 10 * 1024 * 1024  # 10 MB


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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
        return None, None, 1
    try:
        spec = SurrogateSpec.model_validate(payload)
    except ValidationError as exc:
        print(format_validation_error(exc))
        return None, None, 1
    return payload, spec, 0


def _load_and_validate_metamodel(path: Path):
    payload = _load_json(path)
    if payload is None:
        return None, None, 1
    try:
        spec = MetaModelSpec.model_validate(payload)
    except ValidationError as exc:
        print(format_validation_error(exc))
        return None, None, 1
    return payload, spec, 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bayesmm", description="Bayesian Metamodeling CLI")
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
    surrogate_subparsers.add_parser("list", help="List stored surrogate artifacts")

    meta_parser = subparsers.add_parser("meta", help="Metamodel commands")
    meta_subparsers = meta_parser.add_subparsers(dest="meta_command")
    meta_build = meta_subparsers.add_parser("build", help="Build metamodel IR artifact")
    meta_build.add_argument("spec", help="Path to MetaModelSpec JSON")
    meta_sample = meta_subparsers.add_parser("sample", help="Sample from metamodel")
    meta_sample.add_argument("spec", help="Path to MetaModelSpec JSON")
    meta_sample.add_argument("--draws", type=int, required=True)
    meta_sample.add_argument("--tune", type=int, default=0)
    meta_sample.add_argument("--chains", type=int, default=1)
    meta_sample.add_argument("--seed", type=int, default=0)
    meta_sample.add_argument(
        "--method",
        choices=["propagate", "joint"],
        default="propagate",
        help=(
            "propagate (default): draw from the priors and apply couplings as a "
            "post-draw transform — fast, and does NOT condition on the surrogates. "
            "joint: Metropolis over the full joint log-density, including the "
            "surrogate likelihoods, so a coupling informs both of its variables."
        ),
    )
    meta_subparsers.add_parser("list", help="List stored metamodel artifacts and samples")

    subparsers.add_parser("tutorial", help="Print guided end-to-end workflow")

    doctor_parser = subparsers.add_parser(
        "doctor", help="Diagnose environment, Python, and optional backends"
    )
    doctor_parser.add_argument(
        "--json", dest="as_json", action="store_true", help="Emit JSON instead of a report"
    )

    setup_parser = subparsers.add_parser(
        "setup", help="Detect the platform and suggest OS-correct install commands"
    )
    setup_parser.add_argument(
        "--non-interactive",
        dest="non_interactive",
        action="store_true",
        help="Do not prompt; use --backend directly",
    )
    setup_parser.add_argument(
        "--backend",
        default=None,
        help="Comma-separated backends to install: pymc, sbi, 'pymc,sbi', or 'none'",
    )

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


def _execute_design_point(
    *,
    spec,
    point_index: int,
    point: dict[str, float],
    run_token: str,
) -> dict[str, Any]:
    """Execute one DOE point and return normalized result/log payload."""
    adapter = resolve_adapter(spec)
    runner = LocalProcessRunner(timeout_sec=spec.runner.resources.walltime_min * 60)

    run_label = f"{spec.model.name}_{point_index + 1}"
    # Absolute, deliberately. The adapter passes this to the model as `--run-dir`
    # and the model subprocess runs with `cwd=REPO_ROOT`, not with this process's
    # cwd. A relative `storage.root` therefore resolved to two different
    # directories: the model wrote its outputs under REPO_ROOT while
    # `parse_outputs` looked under the invoking cwd, and every point failed with
    # "Output parsing failed: No such file or directory" — the outputs existed,
    # just somewhere nobody looked. It only appeared to work when `bayesmm` was
    # invoked from REPO_ROOT, which made the two paths coincide.
    temp_run_dir = (Path(spec.storage.root) / "_active" / run_token / run_label).resolve()
    temp_run_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(UTC)
    status = "failed"
    returncode = 1
    outputs: dict[str, Any] = {}
    error = ""
    stdout_text = ""
    stderr_text = ""

    try:
        materialization = adapter.materialize_inputs(
            spec=spec,
            point=point,
            run_dir=temp_run_dir,
            repo_root=REPO_ROOT,
        )
        run_result = runner.run(materialization=materialization, run_dir=temp_run_dir)
        returncode = run_result.returncode

        if run_result.stdout_path.exists():
            stdout_text = run_result.stdout_path.read_text(errors="replace")
        if run_result.stderr_path.exists():
            stderr_text = run_result.stderr_path.read_text(errors="replace")

        if returncode == 0:
            try:
                outputs = adapter.parse_outputs(spec=spec, run_dir=temp_run_dir)
                status = "success"
            except (ValueError, FileNotFoundError, json.JSONDecodeError, KeyError, OSError) as exc:
                error = f"Output parsing failed: {exc}"
                stderr_text = f"{stderr_text}\n{error}".strip()
                status = "failed"
                returncode = 1
        else:
            status = "failed"
    except (
        ValueError,
        FileNotFoundError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        OSError,
        KeyError,
    ) as exc:
        error = str(exc)
        stderr_text = f"{stderr_text}\n{error}".strip()
        status = "failed"
        returncode = 1
    finally:
        finished_at = datetime.now(UTC)
        duration_sec = (finished_at - started_at).total_seconds()
        shutil.rmtree(temp_run_dir, ignore_errors=True)

    return {
        "point_index": point_index,
        "point": point,
        "status": status,
        "returncode": returncode,
        "outputs": outputs,
        "error": error,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_sec": duration_sec,
    }


def _run_serial(spec, points: list[dict[str, float]], *, run_token: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for idx, point in enumerate(points):
        print(f"Running point {idx + 1}/{len(points)}: {point}")
        results.append(
            _execute_design_point(
                spec=spec,
                point_index=idx,
                point=point,
                run_token=run_token,
            )
        )
    return results


def _run_parallel_local(
    spec,
    points: list[dict[str, float]],
    *,
    run_token: str,
) -> list[dict[str, Any]]:
    workers = spec.runner.workers or max(1, spec.runner.resources.cpus)
    print(f"Running {len(points)} points in local parallel mode with workers={workers}")

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _execute_design_point,
                spec=spec,
                point_index=idx,
                point=point,
                run_token=run_token,
            ): idx
            for idx, point in enumerate(points)
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            idx = int(result["point_index"])
            print(
                f"Completed point {idx + 1}/{len(points)} "
                f"status={result['status']} returncode={result['returncode']}"
            )
            results.append(result)

    return results


def _run_mpi(
    spec,
    points: list[dict[str, float]],
    *,
    run_token: str,
) -> tuple[list[dict[str, Any]], int]:
    try:
        from mpi4py import MPI
    except ImportError:
        print("MPI mode requested but 'mpi4py' is not installed.")
        return [], 1

    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()
    local_indices = [idx for idx in range(len(points)) if idx % size == rank]

    if rank == 0:
        print(f"Running {len(points)} points in MPI mode across ranks={size}")

    local_results: list[dict[str, Any]] = []
    for idx in local_indices:
        local_results.append(
            _execute_design_point(
                spec=spec,
                point_index=idx,
                point=points[idx],
                run_token=run_token,
            )
        )

    gathered = comm.gather(local_results, root=0)
    if rank != 0:
        return [], 0

    merged = [item for chunk in gathered for item in chunk]
    return merged, 0


def _run_command(spec_path: Path) -> int:
    payload, spec, code = _load_and_validate(spec_path)
    if code != 0:
        return code

    try:
        points = plan_points(spec)
    except DOEPlanError as exc:
        print(f"DOE planning failed: {exc}")
        return 1

    run_token = uuid4().hex
    execution_mode = spec.runner.sweep_mode
    mpi_comm = None

    point_results: list[dict[str, Any]]
    if execution_mode == "serial":
        point_results = _run_serial(spec, points, run_token=run_token)
    elif execution_mode == "parallel_local":
        point_results = _run_parallel_local(spec, points, run_token=run_token)
    elif execution_mode == "mpi":
        point_results, mpi_code = _run_mpi(spec, points, run_token=run_token)
        if mpi_code != 0:
            return mpi_code
        try:
            from mpi4py import MPI
        except ImportError:  # pragma: no cover
            return 1
        mpi_comm = MPI.COMM_WORLD
        if mpi_comm.Get_rank() != 0:
            return int(mpi_comm.bcast(None, root=0))
    else:  # pragma: no cover - validation should prevent this
        print(f"Unsupported runner.sweep_mode: {execution_mode}")
        return 1

    stored = persist_sweep(
        spec_payload=payload,
        spec=spec,
        point_results=point_results,
        execution_mode=execution_mode,
    )
    print(f"Stored sweep run: {stored.run_id}")

    failed = sum(1 for item in point_results if item["status"] != "success")
    success = len(point_results) - failed
    print(f"Run complete: {success} successful runs")
    final_code = 0
    if failed:
        print(f"Run complete with failures: {failed}/{len(point_results)} points failed")
        final_code = 1

    if mpi_comm is not None:
        final_code = int(mpi_comm.bcast(final_code, root=0))
    return final_code


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
    _, spec, code = _load_and_validate_surrogate(spec_path)
    if code != 0:
        return code

    try:
        artifact = fit_surrogate(spec)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Surrogate fit failed: {exc}")
        return 1

    print(
        "Surrogate artifact stored: "
        f"artifact_id={artifact['artifact_id']} path={artifact['artifact_path']}"
    )
    return 0


def _surrogate_eval_command(spec_path: Path, inputs_json: str, n: int) -> int:
    _, spec, code = _load_and_validate_surrogate(spec_path)
    if code != 0:
        return code

    if len(inputs_json.encode("utf-8")) > _MAX_INPUTS_JSON_BYTES:
        print(
            f"--inputs JSON too large ({len(inputs_json.encode('utf-8'))} bytes, "
            f"limit {_MAX_INPUTS_JSON_BYTES} bytes)"
        )
        return 1

    try:
        inputs_payload = json.loads(inputs_json)
    except json.JSONDecodeError as exc:
        print(f"Invalid --inputs JSON: line {exc.lineno}, col {exc.colno}: {exc.msg}")
        return 1

    try:
        result = eval_surrogate(spec=spec, inputs_payload=inputs_payload, n=n)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Surrogate eval failed: {exc}")
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _surrogate_list_command() -> int:
    items = list_surrogate_artifacts()
    if not items:
        print("No surrogate artifacts stored")
        return 0
    print(f"Surrogate artifacts: {len(items)}")
    for item in items:
        print(f"- {item['artifact_id']}: {item['artifact_path']}")
    return 0


def _meta_build_command(spec_path: Path) -> int:
    payload, spec, code = _load_and_validate_metamodel(spec_path)
    if code != 0:
        return code

    ir = build_ir_from_metamodel_spec(spec)
    dataset_digest = json.dumps(spec.surrogate_refs, sort_keys=True)
    artifact = persist_ir_artifact(ir, spec_payload=payload, dataset_digest=dataset_digest, seed=0)
    print(
        "Metamodel IR artifact stored: "
        f"artifact_id={artifact['artifact_id']} ir_path={artifact['ir_path']}"
    )
    return 0


def _meta_sample_command(
    spec_path: Path, *, draws: int, tune: int, chains: int, seed: int, method: str = "propagate"
) -> int:
    _, spec, code = _load_and_validate_metamodel(spec_path)
    if code != 0:
        return code

    ir = build_ir_from_metamodel_spec(spec)
    if method == "joint":
        # The coupled joint, conditioned on the surrogates. Kept behind a flag rather
        # than made the default because it is orders of magnitude slower than prior
        # propagation and changes what the numbers mean — an opt-in, not a surprise.
        from bayesian_metamodeling.meta.joint_sampling import (
            load_surrogates_for_ir,
            sample_joint_to_store,
        )

        try:
            surrogates = load_surrogates_for_ir(ir, spec_refs=list(spec.surrogate_refs))
        except (FileNotFoundError, ValueError) as exc:
            # A missing or placeholder surrogate is a setup problem with a clear fix,
            # not a bug: report it the way the other commands report spec errors.
            print(f"Joint sampling unavailable: {exc}")
            return 1
        artifact = sample_joint_to_store(
            spec=spec,
            ir=ir,
            draws=draws,
            tune=tune,
            chains=chains,
            seed=seed,
            surrogates=surrogates,
        )
        print(
            f"Joint sampling: {len(surrogates)} surrogate(s) conditioned on, "
            f"accept_rate={artifact['accept_rate']:.2f}"
        )
        # A healthy accept_rate does not mean the chain went anywhere. With a sharp
        # surrogate likelihood the posterior sits on a thin ridge, tuning shrinks every
        # proposal to match, and the sampler accepts plenty of microscopic moves while
        # exploring almost none of the distribution. Say so here rather than let the
        # numbers be read as a result.
        stuck = artifact.get("poorly_mixed") or []
        if stuck:
            print(
                f"  WARNING: {len(stuck)} variable(s) barely moved: {', '.join(stuck)}.\n"
                "  Their effective sample size is near zero, so their summaries mean "
                "nothing —\n"
                "  a high accept_rate does not rule this out. This usually means a "
                "surrogate\n"
                "  likelihood is far sharper than the priors, putting the posterior on a "
                "ridge a\n"
                "  coordinate-wise random walk cannot follow. Raise --tune, or loosen the "
                "coupling\n"
                "  sigma / refit the surrogate with honest noise."
            )
    else:
        artifact = sample_metamodel(
            spec=spec,
            ir=ir,
            draws=draws,
            tune=tune,
            chains=chains,
            seed=seed,
        )

    print(
        "Metamodel sample stored: "
        f"sample_id={artifact['sample_id']} dataset={artifact['samples_dataset_path']}"
    )
    return 0


def _meta_list_command() -> int:
    ir_items = list_meta_ir_artifacts()
    sample_items = list_meta_samples()

    print(f"Metamodel IR artifacts: {len(ir_items)}")
    for item in ir_items:
        print(f"- IR {item['artifact_id']}: {item['artifact_path']}")

    print(f"Metamodel samples: {len(sample_items)}")
    for item in sample_items:
        print(f"- Sample {item['sample_id']}: backend={item['backend']}")
    return 0


def _doctor_command(*, as_json: bool) -> int:
    report = diagnose()
    if as_json:
        print(diagnose_to_json(report))
    else:
        print(format_diagnose_report(report), end="")
    return 0


def _setup_command(*, interactive: bool, install_backends: str | None) -> int:
    try:
        setup(interactive=interactive, install_backends=install_backends)
    except ValueError as exc:
        print(f"Setup failed: {exc}")
        return 1
    return 0


def _tutorial_command() -> int:
    print("Bayesian Metamodeling tutorial flow:")
    print("0) Diagnose env: bayesmm doctor   (then `bayesmm setup` if backends are missing)")
    print("1) Validate: bayesmm validate examples/toy_program/spec.toy_program.json")
    print("2) Plan: bayesmm plan examples/toy_program/spec.toy_program.json")
    print("3) Run: bayesmm run examples/toy_program/spec.toy_program.json")
    print("4) Fit surrogate: bayesmm surrogate fit examples/surrogates/surrogate.toy.pymc_gp.json")
    print(
        "5) Eval surrogate: bayesmm surrogate eval <spec>"
        ' --inputs \'{"a":[0.5],"b":[1.0]}\' --n 100'
    )
    print("6) Build metamodel: bayesmm meta build examples/metamodels/metamodel.simple.json")
    print(
        "7) Sample metamodel: bayesmm meta sample <spec> --draws 100 --tune 50 --chains 2 --seed 1"
    )
    print("See also: tutorials/Tutorial_0.ipynb")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        print("bayesian-metamodeling 0.1.0")
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
    if args.command == "surrogate" and args.surrogate_command == "list":
        return _surrogate_list_command()
    if args.command == "meta" and args.meta_command == "build":
        return _meta_build_command(Path(args.spec))
    if args.command == "meta" and args.meta_command == "sample":
        return _meta_sample_command(
            Path(args.spec),
            draws=args.draws,
            tune=args.tune,
            chains=args.chains,
            seed=args.seed,
            method=args.method,
        )
    if args.command == "meta" and args.meta_command == "list":
        return _meta_list_command()
    if args.command == "tutorial":
        return _tutorial_command()
    if args.command == "doctor":
        return _doctor_command(as_json=bool(args.as_json))
    if args.command == "setup":
        return _setup_command(
            interactive=not bool(args.non_interactive),
            install_backends=args.backend,
        )

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
