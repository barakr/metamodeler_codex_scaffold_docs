import csv
import json
from pathlib import Path

import numpy as np

from bayesian_metamodeling.spec import SurrogateSpec
from bayesian_metamodeling.surrogates.dataset import load_tabular_dataset


def _write_nested_output_run_store(root: Path) -> None:
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for idx in range(4):
        a = float(idx)
        b = float(idx + 1)
        y0 = a + b
        run_dir = runs / f"run_{idx:03d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "inputs.json").write_text(json.dumps({"a": a, "b": b}))
        # Mimic toy adapter envelope: outputs['y'] = {"inputs": ..., "y": [...]}.
        (run_dir / "outputs.json").write_text(
            json.dumps({"y": {"inputs": {"a": a, "b": b}, "y": [y0, a * b]}})
        )


def _write_centralized_sweep_store(root: Path) -> None:
    sweep_dir = root / "sweeps" / "sweep_test"
    sweep_dir.mkdir(parents=True, exist_ok=True)
    rows_path = sweep_dir / "sweep_rows.csv"

    fieldnames = ["point_index", "a", "b", "y__0", "y__1", "status"]
    with rows_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for idx in range(4):
            a = float(idx)
            b = float(idx + 1)
            writer.writerow(
                {
                    "point_index": idx,
                    "a": a,
                    "b": b,
                    "y__0": a + b,
                    "y__1": a * b,
                    "status": "success",
                }
            )


def test_load_tabular_dataset_handles_nested_output_envelope(tmp_path):
    store = tmp_path / "toy_like_store"
    _write_nested_output_run_store(store)

    spec = SurrogateSpec.model_validate(
        {
            "schema_version": "1.0",
            "name": "toy_nested_dataset",
            "kind": "conditional",
            "inputs": ["a", "b"],
            "outputs": ["y"],
            "backend": "pymc_gp",
            "backend_config": {},
            "dataset_ref": {"run_store_root": str(store)},
            "seed": 123,
            "summary_config": {"kind": "index", "index": 0},
        }
    )

    x, y, digest = load_tabular_dataset(spec)

    assert x.shape == (4, 2)
    assert y.shape == (4, 1)
    assert np.allclose(y[:, 0], np.array([1.0, 3.0, 5.0, 7.0]))
    assert isinstance(digest, str)
    assert len(digest) > 10


def test_load_tabular_dataset_from_centralized_sweep_csv(tmp_path):
    store = tmp_path / "centralized_store"
    _write_centralized_sweep_store(store)

    spec = SurrogateSpec.model_validate(
        {
            "schema_version": "1.0",
            "name": "toy_centralized_dataset",
            "kind": "conditional",
            "inputs": ["a", "b"],
            "outputs": ["y"],
            "backend": "pymc_gp",
            "backend_config": {},
            "dataset_ref": {"run_store_root": str(store)},
            "seed": 123,
            "summary_config": {"kind": "index", "index": 0},
        }
    )

    x, y, digest = load_tabular_dataset(spec)

    assert x.shape == (4, 2)
    assert y.shape == (4, 1)
    assert np.allclose(y[:, 0], np.array([1.0, 3.0, 5.0, 7.0]))
    assert isinstance(digest, str)
    assert len(digest) > 10
