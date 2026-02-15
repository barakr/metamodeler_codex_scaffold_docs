import csv
from pathlib import Path

import numpy as np

from metamodeler.tutorials import load_toy_heatmap_grids


def _write_sweep_csv(path: Path) -> None:
    rows = [
        {
            "point_index": "0",
            "a": "0.0",
            "b": "0.0",
            "y__0": "0.0",
            "y__1": "0.0",
            "status": "success",
        },
        {
            "point_index": "1",
            "a": "0.0",
            "b": "1.0",
            "y__0": "1.0",
            "y__1": "0.0",
            "status": "success",
        },
        {
            "point_index": "2",
            "a": "1.0",
            "b": "0.0",
            "y__0": "1.0",
            "y__1": "0.0",
            "status": "success",
        },
        {
            "point_index": "3",
            "a": "1.0",
            "b": "1.0",
            "y__0": "2.0",
            "y__1": "1.0",
            "status": "success",
        },
    ]
    fieldnames = ["point_index", "a", "b", "y__0", "y__1", "status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_load_toy_heatmap_grids_builds_expected_matrices(tmp_path):
    csv_path = tmp_path / "sweep_rows.csv"
    _write_sweep_csv(csv_path)

    a_vals, b_vals, sum_grid, product_grid = load_toy_heatmap_grids(csv_path)

    assert np.allclose(a_vals, np.array([0.0, 1.0]))
    assert np.allclose(b_vals, np.array([0.0, 1.0]))
    assert np.allclose(sum_grid, np.array([[0.0, 1.0], [1.0, 2.0]]))
    assert np.allclose(product_grid, np.array([[0.0, 0.0], [0.0, 1.0]]))
