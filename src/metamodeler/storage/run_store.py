"""Run persistence utilities with provenance and registry."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from metamodeler.spec import ModelSpec

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
    return json.loads(REGISTRY_PATH.read_text())


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
    record_path = Path(registry[run_id])
    return json.loads(record_path.read_text())


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

    registry = _load_registry()
    registry[run_id] = str(run_record_path)
    _save_registry(registry)

    return StoredRun(run_id=run_id, run_dir=run_dir, run_record_path=run_record_path)
