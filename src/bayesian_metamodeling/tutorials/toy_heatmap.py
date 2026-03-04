"""Helpers for Tutorial 1 toy sweep heatmaps."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np


def load_toy_heatmap_grids(csv_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load centralized sweep CSV and return axes + sum/product grids.

    Returns:
      - a_vals (sorted unique axis values)
      - b_vals (sorted unique axis values)
      - sum_grid (rows=a, cols=b)
      - product_grid (rows=a, cols=b)
    """
    rows: list[tuple[float, float, float, float]] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status", "success") != "success":
                continue
            rows.append(
                (
                    float(row["a"]),
                    float(row["b"]),
                    float(row["y__0"]),
                    float(row["y__1"]),
                )
            )

    if not rows:
        raise ValueError(f"No successful toy rows found in CSV: {csv_path}")

    arr = np.asarray(rows, dtype=float)
    a_vals = np.sort(np.unique(arr[:, 0]))
    b_vals = np.sort(np.unique(arr[:, 1]))

    a_index = {value: idx for idx, value in enumerate(a_vals)}
    b_index = {value: idx for idx, value in enumerate(b_vals)}

    sum_grid = np.full((len(a_vals), len(b_vals)), np.nan, dtype=float)
    product_grid = np.full((len(a_vals), len(b_vals)), np.nan, dtype=float)
    for a, b, y_sum, y_product in arr:
        i = a_index[a]
        j = b_index[b]
        sum_grid[i, j] = y_sum
        product_grid[i, j] = y_product

    return a_vals, b_vals, sum_grid, product_grid
