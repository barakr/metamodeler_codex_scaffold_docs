"""JSON schema export helpers for typed specs."""

from __future__ import annotations

import json
from pathlib import Path

from metamodeler.spec.modelspec import ModelSpec


def modelspec_json_schema() -> dict:
    """Return JSON schema for ModelSpec."""
    return ModelSpec.model_json_schema()


def write_modelspec_schema(path: Path) -> None:
    """Write ModelSpec JSON schema artifact to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(modelspec_json_schema(), indent=2, sort_keys=True) + "\n")
