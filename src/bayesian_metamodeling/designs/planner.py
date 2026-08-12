"""DOE planning utilities for ModelSpec."""

from __future__ import annotations

import warnings
from itertools import product

from scipy.stats import qmc

from bayesian_metamodeling.spec import ModelSpec


class DOEPlanError(ValueError):
    """Raised when DOE planning inputs are invalid."""


class SobolBalanceWarning(UserWarning):
    """A Sobol design was requested at a size where its balance property does not hold.

    Not an error: `n_points` is usually set by a compute budget, and a slightly unbalanced
    design is still a design. But it is the kind of thing that should never pass unremarked
    in a project that teaches DOE — the reason to pick Sobol over uniform random sampling is
    exactly the property being given up.
    """


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

    sobol_cfg = spec.design.sobol
    n_points = sobol_cfg.n_points
    scramble = sobol_cfg.scramble
    seed = sobol_cfg.seed if sobol_cfg.seed is not None else spec.reproducibility.seed

    # A Sobol sequence's whole selling point is that its points are more evenly spread than
    # random ones. That guarantee — the "balance property" — holds for n a power of 2, and
    # scipy says so itself. Using n = 9 does not fail; it quietly gives you a design with
    # less of the uniformity you chose Sobol for. Warn, do not refuse: it is a defensible
    # choice when a compute budget is what it is, and refusing would break shipped specs.
    if n_points & (n_points - 1) != 0:
        lower = 1 << (n_points.bit_length() - 1)
        warnings.warn(
            f"design.sobol.n_points={n_points} is not a power of 2. Sobol' points are "
            f"balanced (evenly spread) only at powers of 2, which is the property Sobol is "
            f"usually chosen for; scipy warns about this too. Consider {lower} or "
            f"{lower * 2}. This is a quality note, not an error.",
            SobolBalanceWarning,
            stacklevel=2,
        )

    engine = qmc.Sobol(d=len(var_names), scramble=scramble, seed=seed)
    with warnings.catch_warnings():
        # scipy raises its own "balance properties ... power of 2" UserWarning here. We have
        # just emitted the same fact with the actionable part attached (which sizes to use),
        # so letting both through is noise. Suppressed by exact message so any *other*
        # scipy warning still reaches the user.
        #
        # This also keeps `plan_points` usable under `-W error`, which this project's
        # pytest.ini sets: without it, planning any non-power-of-2 Sobol design raised from
        # inside scipy, which is a confusing way to learn about a design-quality issue.
        warnings.filterwarnings(
            "ignore",
            message=r".*balance properties of Sobol.*",
            category=UserWarning,
        )
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
