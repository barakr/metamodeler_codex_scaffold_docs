"""Centralized sweep artifact helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def normalize_output_envelope(raw_value: Any, output_name: str) -> Any:
    """Unwrap adapter envelopes such as {output_name: value, ...}."""
    if isinstance(raw_value, dict) and output_name in raw_value:
        return raw_value[output_name]
    return raw_value


def _flatten_scalar_or_list(value: Any, prefix: str) -> dict[str, Any]:
    if isinstance(value, (int, float, bool, str)):
        return {prefix: value}
    if isinstance(value, list):
        if all(isinstance(item, (int, float, bool, str)) for item in value):
            return {f"{prefix}__{idx}": item for idx, item in enumerate(value)}
        return {f"{prefix}__json": json.dumps(value, sort_keys=True)}
    return {}


def _flatten_nested(value: Any, prefix: str) -> dict[str, Any]:
    flat = _flatten_scalar_or_list(value, prefix)
    if flat:
        return flat
    if isinstance(value, dict):
        nested_scalars: dict[str, Any] = {}
        has_non_scalar = False
        for key, item in sorted(value.items()):
            item_prefix = f"{prefix}__{key}"
            item_flat = _flatten_scalar_or_list(item, item_prefix)
            if item_flat:
                nested_scalars.update(item_flat)
            else:
                has_non_scalar = True
        if has_non_scalar:
            nested_scalars[f"{prefix}__json"] = json.dumps(value, sort_keys=True)
        return nested_scalars
    return {f"{prefix}__json": json.dumps(value, sort_keys=True, default=str)}


def flatten_outputs_for_row(outputs: dict[str, Any]) -> dict[str, Any]:
    """Flatten output payload into deterministic CSV-compatible columns."""
    flat: dict[str, Any] = {}
    for output_name in sorted(outputs):
        normalized = normalize_output_envelope(outputs[output_name], output_name)
        flat.update(_flatten_nested(normalized, output_name))
    return flat


def write_sweep_rows_csv(
    rows: list[dict[str, Any]], *, path: Path, input_names: list[str]
) -> list[str]:
    """Write centralized sweep rows and return column order."""
    rows_sorted = sorted(rows, key=lambda item: int(item["point_index"]))

    base_columns = ["point_index", *input_names]
    tail_columns = [
        "status",
        "returncode",
        "error",
        "duration_sec",
        "started_at",
        "finished_at",
    ]
    seen = set(base_columns + tail_columns)
    dynamic_columns: list[str] = []

    for row in rows_sorted:
        for key in row:
            if key in seen:
                continue
            seen.add(key)
            dynamic_columns.append(key)

    fieldnames = base_columns + sorted(dynamic_columns) + tail_columns
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows_sorted:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return fieldnames


def write_sweep_logs_jsonl(logs: list[dict[str, Any]], *, path: Path) -> None:
    """Write centralized per-point logs in jsonl format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(item, sort_keys=True) for item in sorted(logs, key=lambda x: x["point_index"])
    ]
    payload = "\n".join(lines) + ("\n" if lines else "")
    path.write_text(payload)
