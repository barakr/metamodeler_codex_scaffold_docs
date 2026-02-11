"""Storage helpers for metamodel IR artifacts."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from metamodeler.meta.ir import MetamodelIR, ir_to_json_dict

META_REGISTRY_PATH = Path("tmp/meta_registry.json")


def _load_registry() -> dict[str, str]:
    if not META_REGISTRY_PATH.exists():
        return {}
    return json.loads(META_REGISTRY_PATH.read_text())


def _save_registry(registry: dict[str, str]) -> None:
    META_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_REGISTRY_PATH.write_text(json.dumps(registry, indent=2, sort_keys=True))


def list_meta_ir_artifacts() -> list[dict[str, str]]:
    registry = _load_registry()
    return [{"artifact_id": aid, "artifact_path": path} for aid, path in sorted(registry.items())]


def persist_ir_artifact(
    ir: MetamodelIR,
    *,
    spec_payload: dict,
    dataset_digest: str,
    seed: int,
) -> dict[str, str]:
    artifact_id = uuid4().hex
    artifact_dir = Path("tmp/metamodel_ir") / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    ir_payload = ir_to_json_dict(ir)
    ir_path = artifact_dir / "ir.json"
    ir_path.write_text(json.dumps(ir_payload, indent=2, sort_keys=True))

    digest = hashlib.sha256(json.dumps(ir_payload, sort_keys=True).encode("utf-8")).hexdigest()
    spec_digest = hashlib.sha256(
        json.dumps(spec_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    meta_path = artifact_dir / "artifact.json"
    meta_path.write_text(
        json.dumps(
            {
                "artifact_id": artifact_id,
                "ir_path": str(ir_path),
                "ir_digest": digest,
                "spec_digest": spec_digest,
                "dataset_digest": hashlib.sha256(dataset_digest.encode("utf-8")).hexdigest(),
                "dependency_versions": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                },
                "seed": seed,
                "created_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
    )

    registry = _load_registry()
    registry[artifact_id] = str(meta_path)
    _save_registry(registry)

    return {"artifact_id": artifact_id, "artifact_path": str(meta_path), "ir_path": str(ir_path)}
