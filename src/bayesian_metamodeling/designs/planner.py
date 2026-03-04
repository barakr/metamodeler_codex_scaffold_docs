"""DOE planning utilities for ModelSpec."""

from __future__ import annotations

from itertools import product
from typing import Any

from scipy.stats import qmc

from bayesian_metamodeling.spec import ModelSpec


class DOEPlanError(ValueError):
    """Raised when DOE planning inputs are invalid."""


def _input_support_map(spec: ModelSpec) -> dict[str, tuple[float, float]]:
    support_map: dict[str, tuple[float, float]] = {}
    for variable in spec.io_schema.inputs:
        if variable.support is None:
            raise DOEPlanError(f"Input variable '{variable.name}' is missing support bounds")
        support_map[variable.name] = (float(variable.support[0]), float(variable.support[1]))
    return support_map


def plan_grid_points(spec: ModelSpec) -> list[dict[str, float]]:
    if spec.design.grid is None:
        raise DOEPlanError("design.grid is required for grid strategy")

    var_names = sorted(spec.design.grid.keys())
    if not var_names:
        raise DOEPlanError("design.grid must include at least one variable")

    value_lists = [spec.design.grid[name] for name in var_names]
    if any(len(values) == 0 for values in value_lists):
        raise DOEPlanError("design.grid values cannot be empty")

    points: list[dict[str, float]] = []
    for combo in product(*value_lists):
        points.append({name: float(value) for name, value in zip(var_names, combo, strict=True)})
    return points


def plan_sobol_points(spec: ModelSpec) -> list[dict[str, float]]:
    if spec.design.sobol is None:
        raise DOEPlanError("design.sobol is required for sobol strategy")

    support_map = _input_support_map(spec)
    var_names = sorted(support_map.keys())
    if not var_names:
        raise DOEPlanError("io_schema.inputs must include at least one variable")

    sobol_cfg: dict[str, Any] = spec.design.sobol
    n_points = int(sobol_cfg.get("n_points", 0))
    if n_points <= 0:
        raise DOEPlanError("design.sobol.n_points must be a positive integer")

    scramble = bool(sobol_cfg.get("scramble", False))
    seed = int(sobol_cfg.get("seed", spec.reproducibility.seed))

    engine = qmc.Sobol(d=len(var_names), scramble=scramble, seed=seed)
    unit_samples = engine.random(n=n_points)

    points: list[dict[str, float]] = []
    for sample in unit_samples:
        point: dict[str, float] = {}
        for idx, name in enumerate(var_names):
            low, high = support_map[name]
            point[name] = low + float(sample[idx]) * (high - low)
        points.append(point)
    return points


def plan_points(spec: ModelSpec) -> list[dict[str, float]]:
    if spec.design.strategy == "grid":
        return plan_grid_points(spec)
    if spec.design.strategy == "sobol":
        return plan_sobol_points(spec)
    raise DOEPlanError(f"Unsupported design strategy: {spec.design.strategy}")


def render_plan_preview(points: list[dict[str, float]], n_preview: int = 5) -> str:
    preview_count = min(n_preview, len(points))
    preview_lines = [f"Plan points: {len(points)}", "Preview:"]
    for idx in range(preview_count):
        preview_lines.append(f"{idx + 1}: {points[idx]}")
    return "\n".join(preview_lines)
