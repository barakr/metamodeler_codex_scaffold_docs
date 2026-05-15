"""Dataset loading for surrogate training from run stores."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from bayesian_metamodeling.spec import SurrogateSpec


def _resolve_dataset_root(dataset_ref: str | dict[str, Any]) -> Path:
    if isinstance(dataset_ref, str):
        p = Path(dataset_ref)
    elif "run_store_root" in dataset_ref:
        p = Path(dataset_ref["run_store_root"])
    else:
        raise ValueError("dataset_ref must be a string path or include 'run_store_root'")
    if ".." in p.parts:
        raise ValueError(f"Dataset path must not contain directory traversal (..): {p}")
    return p


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


def _extract_scalar_from_sweep_row(
    row: dict[str, str], *, out_name: str, summary_config: dict[str, Any] | None
) -> float:
    direct = row.get(out_name, "")
    if direct:
        return float(direct)

    json_key = f"{out_name}__json"
    if row.get(json_key):
        parsed = json.loads(row[json_key])
        normalized = _normalize_output_value(parsed, out_name)
        return _extract_scalar_output(normalized, summary_config)

    indexed_pattern = re.compile(rf"^{re.escape(out_name)}__(\d+)$")
    indexed_values: list[tuple[int, float]] = []
    for key, raw in row.items():
        match = indexed_pattern.match(key)
        if not match or raw == "":
            continue
        indexed_values.append((int(match.group(1)), float(raw)))
    if indexed_values:
        indexed_values.sort(key=lambda item: item[0])
        values = [item[1] for item in indexed_values]
        return _extract_scalar_output(values, summary_config)

    nested_pattern = re.compile(rf"^{re.escape(out_name)}__{re.escape(out_name)}__(\d+)$")
    nested_values: list[tuple[int, float]] = []
    for key, raw in row.items():
        match = nested_pattern.match(key)
        if not match or raw == "":
            continue
        nested_values.append((int(match.group(1)), float(raw)))
    if nested_values:
        nested_values.sort(key=lambda item: item[0])
        values = [item[1] for item in nested_values]
        return _extract_scalar_output(values, summary_config)

    raise ValueError(f"Output '{out_name}' not found in centralized sweep row")


def _extract_output_row_from_json(
    outputs: dict[str, Any],
    output_names: list[str],
    summary_config: dict[str, Any] | None,
    outputs_path: Path,
) -> list[float]:
    row: list[float] = []
    for name in output_names:
        if name not in outputs:
            raise ValueError(f"Output '{name}' missing in {outputs_path}")
        normalized_value = _normalize_output_value(outputs[name], name)
        row.append(_extract_scalar_output(normalized_value, summary_config))
    return row


def _extract_output_row_from_sweep(
    row: dict[str, str],
    output_names: list[str],
    summary_config: dict[str, Any] | None,
) -> list[float]:
    return [
        _extract_scalar_from_sweep_row(row, out_name=name, summary_config=summary_config)
        for name in output_names
    ]


def _load_from_centralized_sweeps(
    spec: SurrogateSpec, dataset_root: Path
) -> tuple[np.ndarray, np.ndarray]:
    sweeps_root = dataset_root / "sweeps"
    if not sweeps_root.exists():
        raise ValueError(f"No centralized sweep store found: {sweeps_root}")

    sweep_csv_paths = sorted(path for path in sweeps_root.rglob("sweep_rows.csv") if path.is_file())
    if not sweep_csv_paths:
        raise ValueError(f"No centralized sweep CSV files found under: {sweeps_root}")

    x_rows: list[list[float]] = []
    y_rows: list[list[float]] = []

    for csv_path in sweep_csv_paths:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row is None:
                    continue
                if row.get("status", "success") != "success":
                    continue
                x_rows.append([float(row[name]) for name in spec.inputs])
                y_rows.append(
                    _extract_output_row_from_sweep(
                        row,
                        output_names=spec.outputs,
                        summary_config=spec.summary_config,
                    )
                )

    if not x_rows:
        raise ValueError(f"No successful rows found in centralized sweep CSVs under {sweeps_root}")
    return np.asarray(x_rows, dtype=float), np.asarray(y_rows, dtype=float)


def load_tabular_dataset(spec: SurrogateSpec) -> tuple[np.ndarray, np.ndarray, str]:
    """Load (x, y, digest) from a run store.

    `x` has shape `(N, n_features)`. `y` has shape `(N, D)` where
    `D = len(spec.outputs)`; D=1 (single output) is the special case of the
    generic D-dimensional reader.
    """
    dataset_root = _resolve_dataset_root(spec.dataset_ref)
    runs_root = dataset_root / "runs"

    if (dataset_root / "sweeps").exists():
        x, y = _load_from_centralized_sweeps(spec, dataset_root)
    else:
        if not runs_root.exists():
            raise ValueError(f"Run store does not exist: {runs_root}")

        x_rows: list[list[float]] = []
        y_rows: list[list[float]] = []

        for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
            inputs_path = run_dir / "inputs.json"
            outputs_path = run_dir / "outputs.json"
            if not inputs_path.exists() or not outputs_path.exists():
                continue

            inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
            outputs = json.loads(outputs_path.read_text(encoding="utf-8"))

            x_rows.append([float(inputs[name]) for name in spec.inputs])
            y_rows.append(
                _extract_output_row_from_json(
                    outputs, spec.outputs, spec.summary_config, outputs_path
                )
            )

        if not x_rows:
            raise ValueError(f"No usable runs found in {runs_root}")

        x = np.asarray(x_rows, dtype=float)
        y = np.asarray(y_rows, dtype=float)

    dataset_payload = {
        "inputs": spec.inputs,
        "outputs": spec.outputs,
        "x": x.tolist(),
        "y": y.tolist(),
    }
    digest = json.dumps(dataset_payload, sort_keys=True)
    return x, y, digest
