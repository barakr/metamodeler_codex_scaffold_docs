"""Dataset loading for surrogate training from run stores."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from metamodeler.spec import SurrogateSpec


def _resolve_dataset_root(dataset_ref: str | dict[str, Any]) -> Path:
    if isinstance(dataset_ref, str):
        return Path(dataset_ref)
    if "run_store_root" in dataset_ref:
        return Path(dataset_ref["run_store_root"])
    raise ValueError("dataset_ref must be a string path or include 'run_store_root'")


def _extract_scalar_output(value: Any, summary_config: dict[str, Any] | None) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        if len(value) == 1:
            return float(value[0])
        if summary_config is None:
            raise ValueError(
                "High-dimensional output requires summary_config. Default is no summaries."
            )
        kind = summary_config.get("kind")
        if kind == "index":
            idx = int(summary_config.get("index", 0))
            return float(value[idx])
        if kind == "mean":
            return float(np.mean(np.asarray(value, dtype=float)))
        raise ValueError(f"Unsupported summary_config kind: {kind}")
    if isinstance(value, dict):
        if "value" in value:
            return _extract_scalar_output(value["value"], summary_config)
        if len(value) == 1:
            only = next(iter(value.values()))
            return _extract_scalar_output(only, summary_config)
    raise ValueError(f"Unsupported output value type for surrogate training: {type(value)}")


def _normalize_output_value(raw_value: Any, out_name: str) -> Any:
    """Normalize adapter-specific output envelopes to the scalar/array payload.

    Some adapters persist outputs as `{out_name: {"inputs": ..., out_name: [...]}}`.
    Surrogate fitting should consume the inner value for `out_name`.
    """
    if isinstance(raw_value, dict) and out_name in raw_value:
        return raw_value[out_name]
    return raw_value


def load_tabular_dataset(spec: SurrogateSpec) -> tuple[np.ndarray, np.ndarray, str]:
    dataset_root = _resolve_dataset_root(spec.dataset_ref)
    runs_root = dataset_root / "runs"
    if not runs_root.exists():
        raise ValueError(f"Run store does not exist: {runs_root}")

    x_rows: list[list[float]] = []
    y_rows: list[float] = []

    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        inputs_path = run_dir / "inputs.json"
        outputs_path = run_dir / "outputs.json"
        if not inputs_path.exists() or not outputs_path.exists():
            continue

        inputs = json.loads(inputs_path.read_text())
        outputs = json.loads(outputs_path.read_text())

        x_rows.append([float(inputs[name]) for name in spec.inputs])

        out_name = spec.outputs[0]
        if out_name not in outputs:
            raise ValueError(f"Output '{out_name}' missing in {outputs_path}")
        normalized_value = _normalize_output_value(outputs[out_name], out_name)
        y_rows.append(_extract_scalar_output(normalized_value, spec.summary_config))

    if not x_rows:
        raise ValueError(f"No usable runs found in {runs_root}")

    x = np.asarray(x_rows, dtype=float)
    y = np.asarray(y_rows, dtype=float)

    dataset_payload = {
        "inputs": spec.inputs,
        "outputs": spec.outputs,
        "x": x_rows,
        "y": y_rows,
    }
    digest = json.dumps(dataset_payload, sort_keys=True)
    return x, y, digest
