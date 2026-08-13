"""Execute a planned DOE sweep, in any of the supported execution modes.

Moved verbatim-in-behaviour out of `cli/main.py` (D1 in REVIEW_AND_UPGRADE_PLAN.md). Two
things changed in the move, both deliberate:

1. **Types.** The four functions took a bare, unannotated `spec`. They now take `ModelSpec`,
   per rule 8 ("typed contracts first").
2. **Printing became a callback.** A library that prints to stdout is unusable from a
   notebook that wants to render its own progress, and untestable without capturing output.
   `on_progress` defaults to `None`, meaning silent; the CLI passes `print`.

The per-point payload stays a `dict[str, Any]` rather than becoming a dataclass, because it
is the input contract of `persist_sweep` and is written to `sweep_logs.jsonl` — turning it
into a class here would either duplicate the schema or force a storage change, and neither
belongs in a refactor whose value is that behaviour does not move.
"""

from __future__ import annotations

import concurrent.futures
import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from bayesian_metamodeling.adapters import resolve_adapter
from bayesian_metamodeling.designs import plan_points
from bayesian_metamodeling.runners import LocalProcessRunner
from bayesian_metamodeling.spec import ModelSpec
from bayesian_metamodeling.storage import persist_sweep
from bayesian_metamodeling.storage.run_store import StoredRun

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Called with one human-readable progress line. `print` is the obvious argument.
ProgressCallback = Callable[[str], None]


def _noop(_message: str) -> None:
    return None


@dataclass
class SweepOutcome:
    """What a sweep produced, plus enough context to persist and report it.

    `is_writer` exists for MPI: every rank runs its share of the points, but only rank 0
    gathers them and may write. A non-writer rank returns no results and must not persist,
    or every rank would race to write the same store.
    """

    point_results: list[dict[str, Any]] = field(default_factory=list)
    execution_mode: str = "serial"
    is_writer: bool = True
    exit_code: int = 0

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.point_results if item["status"] != "success")

    @property
    def success_count(self) -> int:
        return len(self.point_results) - self.failed_count


def execute_design_point(
    *,
    spec: ModelSpec,
    point_index: int,
    point: dict[str, float],
    run_token: str,
) -> dict[str, Any]:
    """Execute one DOE point and return its normalized result/log payload."""
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
    #
    # `run_label` is safe to interpolate because `model.name` is charset-validated
    # (spec/modelspec.py) — this path is `shutil.rmtree`'d in the `finally` below.
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


def _run_serial(
    spec: ModelSpec,
    points: list[dict[str, float]],
    *,
    run_token: str,
    on_progress: ProgressCallback,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for idx, point in enumerate(points):
        on_progress(f"Running point {idx + 1}/{len(points)}: {point}")
        results.append(
            execute_design_point(
                spec=spec,
                point_index=idx,
                point=point,
                run_token=run_token,
            )
        )
    return results


def _run_parallel_local(
    spec: ModelSpec,
    points: list[dict[str, float]],
    *,
    run_token: str,
    on_progress: ProgressCallback,
) -> list[dict[str, Any]]:
    workers = spec.runner.workers or max(1, spec.runner.resources.cpus)
    on_progress(f"Running {len(points)} points in local parallel mode with workers={workers}")

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                execute_design_point,
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
            on_progress(
                f"Completed point {idx + 1}/{len(points)} "
                f"status={result['status']} returncode={result['returncode']}"
            )
            results.append(result)

    return results


def _run_mpi(
    spec: ModelSpec,
    points: list[dict[str, float]],
    *,
    run_token: str,
    on_progress: ProgressCallback,
) -> SweepOutcome:
    try:
        from mpi4py import MPI
    except ImportError:
        on_progress("MPI mode requested but 'mpi4py' is not installed.")
        return SweepOutcome(execution_mode="mpi", is_writer=True, exit_code=1)

    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()
    local_indices = [idx for idx in range(len(points)) if idx % size == rank]

    if rank == 0:
        on_progress(f"Running {len(points)} points in MPI mode across ranks={size}")

    local_results = [
        execute_design_point(spec=spec, point_index=idx, point=points[idx], run_token=run_token)
        for idx in local_indices
    ]

    gathered = comm.gather(local_results, root=0)
    if rank != 0:
        return SweepOutcome(execution_mode="mpi", is_writer=False)

    merged = [item for chunk in gathered for item in chunk]
    return SweepOutcome(point_results=merged, execution_mode="mpi", is_writer=True)


def run_sweep(
    spec: ModelSpec,
    *,
    points: list[dict[str, float]] | None = None,
    run_token: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> SweepOutcome:
    """Plan (if needed) and execute every design point for `spec`.

    This is the library entry point: it runs the sweep and hands back the per-point
    results without writing anything. Use `run_sweep_to_store` for the CLI's behaviour of
    running *and* persisting.

    `points` is accepted so a caller can sweep a design it planned or filtered itself —
    re-running a handful of failed points, for instance — without going through
    `plan_points` again.
    """
    progress = on_progress or _noop
    resolved_points = plan_points(spec) if points is None else points
    token = run_token or uuid4().hex
    mode = spec.runner.sweep_mode

    if mode == "serial":
        results = _run_serial(spec, resolved_points, run_token=token, on_progress=progress)
        return SweepOutcome(point_results=results, execution_mode=mode)
    if mode == "parallel_local":
        results = _run_parallel_local(spec, resolved_points, run_token=token, on_progress=progress)
        return SweepOutcome(point_results=results, execution_mode=mode)
    if mode == "mpi":
        return _run_mpi(spec, resolved_points, run_token=token, on_progress=progress)
    # Unreachable via a validated spec: `runner.sweep_mode` is a Literal.
    raise ValueError(f"Unsupported runner.sweep_mode: {mode}")


def run_sweep_to_store(
    spec: ModelSpec,
    *,
    spec_payload: dict[str, Any],
    points: list[dict[str, float]] | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[SweepOutcome, StoredRun | None]:
    """Run a sweep and persist it, returning both the outcome and the stored run.

    Returns `(outcome, None)` when this process must not write — a non-root MPI rank, or a
    mode that failed to start. Callers must check `outcome.is_writer` rather than assuming
    a `StoredRun` is always produced.
    """
    outcome = run_sweep(spec, points=points, run_token=None, on_progress=on_progress)
    if not outcome.is_writer or outcome.exit_code != 0 or not outcome.point_results:
        return outcome, None

    stored = persist_sweep(
        spec_payload=spec_payload,
        spec=spec,
        point_results=outcome.point_results,
        execution_mode=outcome.execution_mode,
    )
    return outcome, stored
