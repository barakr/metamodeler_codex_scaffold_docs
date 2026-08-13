"""Edge-case tests for ModelSpec, VariableSpec, TimeGrid, Design specs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bayesian_metamodeling.spec import (
    DesignSpec,
    TimeGridSpec,
    VariableSpec,
    load_and_validate_modelspec,
)


def _base_payload(**overrides) -> dict:
    base = {
        "schema_version": "1.0",
        "model": {
            "name": "test",
            "version": "1.0",
            "artifact": {"type": "local", "entrypoint": ["python", "nope.py"]},
        },
        "runner": {
            "mode": "local_process",
            "resources": {"cpus": 1, "mem_gb": 1, "walltime_min": 1},
        },
        "io_schema": {
            "inputs": [{"name": "a", "type": "float", "units": "m"}],
            "outputs": [{"name": "y", "type": "float", "units": "m"}],
        },
        "design": {"strategy": "grid", "grid": {"a": [1.0]}},
        "adapter": {"id": "python_cli_adapter_v1"},
        "reproducibility": {"seed": 0},
        "storage": {"root": "tmp/test"},
    }
    base.update(overrides)
    return base


# --- VariableSpec ---


def test_variable_support_must_have_two_elements():
    with pytest.raises(ValidationError, match="support"):
        VariableSpec(name="x", type="float", units="m", support=[1.0])


def test_variable_support_max_must_exceed_min():
    with pytest.raises(ValidationError, match="max must be greater"):
        VariableSpec(name="x", type="float", units="m", support=[5.0, 2.0])


def test_variable_support_equal_bounds_rejected():
    with pytest.raises(ValidationError, match="max must be greater"):
        VariableSpec(name="x", type="float", units="m", support=[2.0, 2.0])


def test_variable_valid_support():
    v = VariableSpec(name="x", type="float", units="m", support=[0.0, 10.0])
    assert v.support == [0.0, 10.0]


def test_variable_array_requires_dims():
    with pytest.raises(ValidationError, match="dims"):
        VariableSpec(name="x", type="array", units="m")


def test_variable_array_with_dims():
    v = VariableSpec(name="x", type="array", units="m", dims=["time"])
    assert v.dims == ["time"]


# --- TimeGridSpec ---


def test_timegrid_requires_t1_greater_than_t0():
    with pytest.raises(ValidationError, match="t1 must be greater"):
        TimeGridSpec(t0=5.0, t1=2.0, dt=1.0)


def test_timegrid_requires_exactly_one_of_dt_or_npoints():
    with pytest.raises(ValidationError, match="exactly one"):
        TimeGridSpec(t0=0.0, t1=1.0, dt=0.1, n_points=10)

    with pytest.raises(ValidationError, match="exactly one"):
        TimeGridSpec(t0=0.0, t1=1.0)


def test_timegrid_dt_must_be_positive():
    with pytest.raises(ValidationError, match="dt must be positive"):
        TimeGridSpec(t0=0.0, t1=1.0, dt=-0.1)


def test_timegrid_npoints_must_be_at_least_2():
    with pytest.raises(ValidationError, match="n_points must be >= 2"):
        TimeGridSpec(t0=0.0, t1=1.0, n_points=1)


def test_timegrid_valid_with_dt():
    tg = TimeGridSpec(t0=0.0, t1=1.0, dt=0.1)
    assert tg.dt == 0.1


def test_timegrid_valid_with_npoints():
    tg = TimeGridSpec(t0=0.0, t1=1.0, n_points=10)
    assert tg.n_points == 10


# --- DesignSpec ---


def test_design_grid_requires_grid_field():
    with pytest.raises(ValidationError, match="grid is required"):
        DesignSpec(strategy="grid")


def test_design_sobol_requires_sobol_field():
    with pytest.raises(ValidationError, match="sobol is required"):
        DesignSpec(strategy="sobol")


def test_design_grid_valid():
    d = DesignSpec(strategy="grid", grid={"a": [1.0, 2.0]})
    assert d.grid == {"a": [1.0, 2.0]}


def test_design_sobol_valid():
    d = DesignSpec(strategy="sobol", sobol={"n_points": 16, "scramble": True, "seed": 3})
    assert d.sobol.n_points == 16
    assert d.sobol.scramble is True


def test_design_sobol_rejects_a_key_the_planner_would_never_read():
    """This test previously asserted the opposite, and that was the bug (D4).

    It read `DesignSpec(strategy="sobol", sobol={"n": 16})` and called it valid. `n` is not
    a key the planner reads — `plan_sobol_points` looks for `n_points` — so the design it
    described would have been planned with a different number of points than it named, or
    failed later with a confusing message. `design.sobol` was `dict[str, Any]`, the one
    untyped object in an otherwise strictly-validated spec tree, so nothing objected.

    That is the same shape as the `ranges` key both research specs still carry: a plausible
    name, silently ignored.
    """
    with pytest.raises(ValidationError, match="n_points"):
        DesignSpec(strategy="sobol", sobol={"n": 16})


# --- ModelSpec duplicate variable names (io_schema) ---


def test_modelspec_valid_roundtrip():
    spec = load_and_validate_modelspec(_base_payload())
    assert spec.model.name == "test"


def test_modelspec_extra_fields_rejected():
    payload = _base_payload()
    payload["unexpected_field"] = 42
    with pytest.raises(ValidationError):
        load_and_validate_modelspec(payload)


def test_modelspec_storage_root_rejects_absolute_path():
    payload = _base_payload(storage={"root": "/absolute/path"})
    with pytest.raises(ValidationError, match="project-relative"):
        load_and_validate_modelspec(payload)


def test_modelspec_storage_root_rejects_traversal():
    payload = _base_payload(storage={"root": "tmp/../../../etc"})
    with pytest.raises(ValidationError, match="traversal"):
        load_and_validate_modelspec(payload)
