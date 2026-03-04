"""Surrogate artifact storage and registry."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from bayesian_metamodeling.spec import SurrogateSpec

SURROGATE_REGISTRY_PATH = Path("tmp/surrogate_registry.json")


def _load_registry() -> dict[str, str]:
    if not SURROGATE_REGISTRY_PATH.exists():
        return {}
    return json.loads(SURROGATE_REGISTRY_PATH.read_text())


def _save_registry(registry: dict[str, str]) -> None:
    SURROGATE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SURROGATE_REGISTRY_PATH.write_text(json.dumps(registry, indent=2, sort_keys=True))


def _digest_json(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def list_surrogate_artifacts() -> list[dict[str, str]]:
    registry = _load_registry()
    return [
        {"artifact_id": artifact_id, "artifact_path": path}
        for artifact_id, path in sorted(registry.items())
    ]


def persist_surrogate_artifact(
    *,
    spec: SurrogateSpec,
    dataset_digest: str,
    payload_path: Path,
    dependency_versions: dict[str, str] | None = None,
) -> dict[str, str]:
    artifact_id = uuid4().hex
    artifact_dir = Path("tmp/surrogate_artifacts") / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    backend_payload_path = artifact_dir / "backend_payload.json"
    backend_payload_path.write_text(payload_path.read_text())

    spec_payload = spec.model_dump(mode="json")
    versions = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    if dependency_versions:
        versions.update(dependency_versions)

    artifact_json = {
        "artifact_id": artifact_id,
        "spec_name": spec.name,
        "backend": spec.backend,
        "spec_digest": _digest_json(spec_payload),
        "dataset_digest": hashlib.sha256(dataset_digest.encode("utf-8")).hexdigest(),
        "variable_lists": {"inputs": spec.inputs, "outputs": spec.outputs},
        "io_signature": {"inputs_ordered": spec.inputs, "outputs_ordered": spec.outputs},
        "seed": spec.seed,
        "dependency_versions": versions,
        "backend_payload": str(backend_payload_path),
        "created_at": datetime.now(UTC).isoformat(),
    }

    artifact_path = artifact_dir / "artifact.json"
    artifact_path.write_text(json.dumps(artifact_json, indent=2, sort_keys=True))

    registry = _load_registry()
    registry[artifact_id] = str(artifact_path)
    _save_registry(registry)

    return {
        "artifact_id": artifact_id,
        "artifact_path": str(artifact_path),
        "backend_payload": str(backend_payload_path),
    }


def find_latest_artifact_for_spec(spec_name: str) -> tuple[str, Path]:
    registry = _load_registry()
    candidates: list[tuple[str, dict, Path]] = []
    for artifact_id, path in registry.items():
        artifact_path = Path(path)
        payload = json.loads(artifact_path.read_text())
        if payload.get("spec_name") == spec_name:
            candidates.append((artifact_id, payload, artifact_path))
    if not candidates:
        raise ValueError(f"No surrogate artifact found for spec_name={spec_name}")

    candidates.sort(key=lambda item: item[1].get("created_at", ""))
    latest = candidates[-1]
    return latest[0], latest[2]
