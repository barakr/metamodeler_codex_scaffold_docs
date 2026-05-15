"""Run and sweep persistence utilities with provenance and registry."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from bayesian_metamodeling.spec import ModelSpec
from bayesian_metamodeling.storage._filelock import locked_registry
from bayesian_metamodeling.storage.sweep_store import (
    flatten_outputs_for_row,
    write_sweep_logs_jsonl,
    write_sweep_rows_csv,
)

REGISTRY_PATH = Path("tmp/run_registry.json")


@dataclass
class StoredRun:
    run_id: str
    run_dir: Path
    run_record_path: Path


def sha256_json(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_registry() -> dict[str, str]:
    if not REGISTRY_PATH.exists():
        return {}
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _save_registry(registry: dict[str, str]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2, sort_keys=True))


def list_registered_runs() -> list[dict[str, str]]:
    registry = _load_registry()
    return [{"run_id": run_id, "record_path": path} for run_id, path in sorted(registry.items())]


def show_registered_run(run_id: str) -> dict:
    registry = _load_registry()
    if run_id not in registry:
        raise ValueError(f"Run not found in registry: {run_id}")
    record_path = Path(registry[run_id]).resolve()
    cwd = Path.cwd().resolve()
    tmp_root = (cwd / "tmp").resolve()
    if not (record_path.is_relative_to(cwd) or record_path.is_relative_to(tmp_root)):
        raise ValueError(f"Registry entry points outside project: {record_path}")
    return json.loads(record_path.read_text(encoding="utf-8"))


def persist_run(
    *,
    spec_payload: dict,
    spec: ModelSpec,
    point: dict[str, float],
    outputs: dict,
    status: str,
    returncode: int,
    stdout_path: Path,
    stderr_path: Path,
) -> StoredRun:
    run_id = uuid4().hex
    run_root = Path(spec.storage.root) / "runs"
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    inputs_path = run_dir / "inputs.json"
    outputs_path = run_dir / "outputs.json"
    run_record_path = run_dir / "run.json"

    inputs_path.write_text(json.dumps(point, indent=2, sort_keys=True))
    outputs_path.write_text(json.dumps(outputs, indent=2, sort_keys=True))

    spec_digest = sha256_json(spec_payload)
    artifact_digest = sha256_json(spec.model.artifact.model_dump(mode="json"))

    run_record = {
        "run_id": run_id,
        "status": status,
        "returncode": returncode,
        "seed": spec.reproducibility.seed,
        "spec_digest": spec_digest,
        "artifact_digest": artifact_digest,
        "adapter_id": spec.adapter.id,
        "runner_mode": spec.runner.mode,
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "inputs_path": str(inputs_path),
        "outputs_path": str(outputs_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }
    run_record_path.write_text(json.dumps(run_record, indent=2, sort_keys=True))

    with locked_registry(REGISTRY_PATH):
        registry = _load_registry()
        registry[run_id] = str(run_record_path)
        _save_registry(registry)

    return StoredRun(run_id=run_id, run_dir=run_dir, run_record_path=run_record_path)


def persist_sweep(
    *,
    spec_payload: dict[str, Any],
    spec: ModelSpec,
    point_results: list[dict[str, Any]],
    execution_mode: str,
    sweep_id: str | None = None,
) -> StoredRun:
    """Persist a full DOE sweep into centralized artifacts."""
    if not point_results:
        raise ValueError("persist_sweep requires at least one point result")

    run_id = sweep_id or uuid4().hex
    sweep_root = Path(spec.storage.root) / "sweeps" / run_id
    sweep_root.mkdir(parents=True, exist_ok=True)

    rows_path = sweep_root / "sweep_rows.csv"
    logs_path = sweep_root / "sweep_logs.jsonl"
    manifest_path = sweep_root / "sweep_manifest.json"
    run_record_path = sweep_root / "run.json"

    input_names = [item.name for item in spec.io_schema.inputs]
    rows: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []

    for result in point_results:
        row = {
            "point_index": int(result["point_index"]),
            "status": result["status"],
            "returncode": int(result["returncode"]),
            "error": result.get("error", ""),
            "duration_sec": float(result.get("duration_sec", 0.0)),
            "started_at": result["started_at"],
            "finished_at": result["finished_at"],
        }
        for name in input_names:
            row[name] = float(result["point"][name])
        row.update(flatten_outputs_for_row(result.get("outputs", {})))
        rows.append(row)

        logs.append(
            {
                "point_index": int(result["point_index"]),
                "status": result["status"],
                "returncode": int(result["returncode"]),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
            }
        )

    columns = write_sweep_rows_csv(rows, path=rows_path, input_names=input_names)
    write_sweep_logs_jsonl(logs, path=logs_path)

    success_count = sum(1 for item in point_results if item["status"] == "success")
    failed_count = len(point_results) - success_count

    spec_digest = sha256_json(spec_payload)
    artifact_digest = sha256_json(spec.model.artifact.model_dump(mode="json"))
    started_at = min(item["started_at"] for item in point_results)
    finished_at = max(item["finished_at"] for item in point_results)
    status = "success" if failed_count == 0 else "failed"

    manifest_payload = {
        "sweep_id": run_id,
        "status": status,
        "total_points": len(point_results),
        "success_count": success_count,
        "failed_count": failed_count,
        "seed": spec.reproducibility.seed,
        "spec_digest": spec_digest,
        "artifact_digest": artifact_digest,
        "execution_mode": execution_mode,
        "row_columns": columns,
        "rows_path": str(rows_path),
        "logs_path": str(logs_path),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True))

    run_record = {
        "run_id": run_id,
        "run_type": "sweep",
        "status": status,
        "seed": spec.reproducibility.seed,
        "spec_digest": spec_digest,
        "artifact_digest": artifact_digest,
        "adapter_id": spec.adapter.id,
        "runner_mode": spec.runner.mode,
        "sweep_execution_mode": execution_mode,
        "total_points": len(point_results),
        "success_count": success_count,
        "failed_count": failed_count,
        "sweep_manifest_path": str(manifest_path),
        "sweep_rows_path": str(rows_path),
        "sweep_logs_path": str(logs_path),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    run_record_path.write_text(json.dumps(run_record, indent=2, sort_keys=True))

    with locked_registry(REGISTRY_PATH):
        registry = _load_registry()
        registry[run_id] = str(run_record_path)
        _save_registry(registry)

    return StoredRun(run_id=run_id, run_dir=sweep_root, run_record_path=run_record_path)
