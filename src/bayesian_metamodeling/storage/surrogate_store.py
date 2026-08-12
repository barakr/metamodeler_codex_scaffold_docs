"""Surrogate artifact storage and registry."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from bayesian_metamodeling.spec import SurrogateSpec
from bayesian_metamodeling.storage._filelock import locked_registry

SURROGATE_REGISTRY_PATH = Path("tmp/surrogate_registry.json")


def _store_root() -> Path:
    """The directory the registry lives in — everything it names must be under it.

    Read at call time, not import time, because the registry path is a module-level
    constant that tests (and, once D3 lands, configuration) rebind.
    """
    return SURROGATE_REGISTRY_PATH.parent


def _load_registry() -> dict[str, str]:
    if not SURROGATE_REGISTRY_PATH.exists():
        return {}
    return json.loads(SURROGATE_REGISTRY_PATH.read_text(encoding="utf-8"))


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
    # Derive the artifact directory from the registry's location rather than hardcoding
    # `tmp/`. The two must live under one root or the registry can name paths outside the
    # store it belongs to — which is precisely what `_check_inside_store` refuses below,
    # and what made these two disagree: the registry path was overridable while this one
    # was not. With the default registry (`tmp/surrogate_registry.json`) this resolves to
    # `tmp/surrogate_artifacts/<id>`, exactly as before. Part of D3 in
    # REVIEW_AND_UPGRADE_PLAN.md; the rest of D3 makes the root explicit rather than
    # implied by a module constant.
    artifact_dir = _store_root() / "surrogate_artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    backend_payload_path = artifact_dir / "backend_payload.json"
    backend_payload_path.write_text(payload_path.read_text(encoding="utf-8"))

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

    with locked_registry(SURROGATE_REGISTRY_PATH):
        registry = _load_registry()
        registry[artifact_id] = str(artifact_path)
        _save_registry(registry)

    return {
        "artifact_id": artifact_id,
        "artifact_path": str(artifact_path),
        "backend_payload": str(backend_payload_path),
    }


def _check_inside_store(artifact_path: Path) -> Path:
    """Refuse to read a registry entry pointing outside the store that lists it.

    `run_store.show_registered_run` has done something like this since it was written;
    this path did not, so the same registry-poisoning concern was handled in one place
    and ignored in the other. The registry is a plain JSON file anyone can edit, and the
    payload an entry names can lead to `torch.load`, so it is worth refusing on the way
    in.

    **Anchored on the registry's own directory, not the process cwd.** A registry at
    `<root>/surrogate_registry.json` may only reference artifacts under `<root>/`, which
    is the actual invariant — `persist_surrogate_artifact` writes both. Anchoring on
    `Path.cwd()` instead (as `run_store` does) makes the rule depend on where you
    happened to launch `bayesmm` from, which is the same cwd-sensitivity recorded as D3
    in REVIEW_AND_UPGRADE_PLAN.md. When D3 lands and store roots become explicit, both
    call sites should converge on that root.
    """
    root = _store_root().resolve()
    resolved = artifact_path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Registry entry points outside the surrogate store ({root}): {resolved}")
    return resolved


def find_latest_artifact_for_spec(spec_name: str) -> tuple[str, Path]:
    registry = _load_registry()
    candidates: list[tuple[str, dict, Path]] = []
    for artifact_id, path in registry.items():
        artifact_path = Path(path)
        payload = json.loads(_check_inside_store(artifact_path).read_text(encoding="utf-8"))
        if payload.get("spec_name") == spec_name:
            candidates.append((artifact_id, payload, artifact_path))
    if not candidates:
        raise ValueError(f"No surrogate artifact found for spec_name={spec_name}")

    candidates.sort(key=lambda item: item[1].get("created_at", ""))
    latest = candidates[-1]
    return latest[0], latest[2]
