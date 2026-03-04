"""Edge-case tests for surrogate dataset loading."""

from __future__ import annotations

import csv
import json

import pytest

from bayesian_metamodeling.spec import SurrogateSpec
from bayesian_metamodeling.surrogates.dataset import (
    _extract_scalar_output,
    _resolve_dataset_root,
    load_tabular_dataset,
)


def _surrogate_spec(store: str, inputs: list[str] = None, outputs: list[str] = None):
    return SurrogateSpec.model_validate(
        {
            "schema_version": "1.0",
            "name": "ds_test",
            "kind": "conditional",
            "inputs": inputs or ["a"],
            "outputs": outputs or ["y"],
            "backend": "pymc_gp",
            "backend_config": {},
            "dataset_ref": {"run_store_root": store},
            "seed": 0,
        }
    )


# --- _extract_scalar_output ---


def test_extract_scalar_from_int():
    assert _extract_scalar_output(42, None) == 42.0


def test_extract_scalar_from_float():
    assert _extract_scalar_output(3.14, None) == 3.14


def test_extract_scalar_from_single_element_list():
    assert _extract_scalar_output([7.5], None) == 7.5


def test_extract_scalar_from_multielement_list_requires_config():
    with pytest.raises(ValueError, match="summary_config"):
        _extract_scalar_output([1.0, 2.0, 3.0], None)


def test_extract_scalar_with_index_config():
    result = _extract_scalar_output([10.0, 20.0, 30.0], {"kind": "index", "index": 1})
    assert result == 20.0


def test_extract_scalar_with_mean_config():
    result = _extract_scalar_output([1.0, 3.0], {"kind": "mean"})
    assert result == 2.0


def test_extract_scalar_from_dict_with_value_key():
    assert _extract_scalar_output({"value": 5.0}, None) == 5.0


def test_extract_scalar_from_single_key_dict():
    assert _extract_scalar_output({"result": 9.0}, None) == 9.0


def test_extract_scalar_unsupported_type_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        _extract_scalar_output("not_a_number", None)


# --- _resolve_dataset_root ---


def test_resolve_dataset_root_rejects_traversal():
    with pytest.raises(ValueError, match="traversal"):
        _resolve_dataset_root("../../etc")


# --- load_tabular_dataset from sweep CSV ---


def test_load_from_centralized_sweeps_skips_failed_rows(tmp_path):
    store = tmp_path / "store"
    sweeps = store / "sweeps" / "s1"
    sweeps.mkdir(parents=True)
    csv_path = sweeps / "sweep_rows.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["a", "y", "status", "returncode"])
        w.writeheader()
        w.writerow({"a": "1.0", "y": "2.0", "status": "success", "returncode": "0"})
        w.writerow({"a": "3.0", "y": "", "status": "failed", "returncode": "1"})

    spec = _surrogate_spec(str(store))
    x, y, digest = load_tabular_dataset(spec)
    assert len(x) == 1
    assert y[0] == 2.0


def test_load_from_runs_missing_output_raises(tmp_path):
    store = tmp_path / "store"
    runs = store / "runs" / "r0"
    runs.mkdir(parents=True)
    (runs / "inputs.json").write_text(json.dumps({"a": 1.0}))
    (runs / "outputs.json").write_text(json.dumps({"z": 2.0}))  # missing 'y'

    spec = _surrogate_spec(str(store))
    with pytest.raises(ValueError, match="missing"):
        load_tabular_dataset(spec)
