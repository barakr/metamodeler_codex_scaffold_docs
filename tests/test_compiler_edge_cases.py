"""Edge-case tests for metamodel compiler."""

from __future__ import annotations

import numpy as np
import pytest

from bayesian_metamodeling.meta.compiler import (
    _DETERMINISTIC_PENALTY,
    _DETERMINISTIC_TOL,
    compile_metamodel,
)
from bayesian_metamodeling.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    SurrogateLikelihoodFactorIR,
    VariableIR,
)


def _ir_with_factors(factors):
    variables = set()
    for f in factors:
        if isinstance(f, PriorFactorIR):
            variables.add(f.variable)
        elif isinstance(f, CouplingFactorIR):
            variables.add(f.source)
            variables.add(f.target)
        elif isinstance(f, SurrogateLikelihoodFactorIR):
            variables.update(f.inputs)
            variables.update(f.outputs)
    return MetamodelIR(
        name="test",
        variables=[VariableIR(name=v) for v in sorted(variables)] or [VariableIR(name="x")],
        factors=factors,
    )


def test_compile_no_factors():
    ir = _ir_with_factors([])
    compiled = compile_metamodel(ir, backend="pymc")
    lp = compiled.evaluate_log_prob({"x": 0.0})
    assert lp == 0.0


def test_compile_prior_only():
    ir = _ir_with_factors(
        [PriorFactorIR(variable="x", distribution={"kind": "normal", "loc": 0.0, "scale": 1.0})]
    )
    compiled = compile_metamodel(ir, backend="pymc")
    lp = compiled.evaluate_log_prob({"x": 0.0})
    assert np.isfinite(lp)


def test_compile_coupling_only():
    ir = _ir_with_factors(
        [CouplingFactorIR(coupling_type="gaussian_link", source="a", target="b", sigma=0.5)]
    )
    compiled = compile_metamodel(ir, backend="pymc")
    lp = compiled.evaluate_log_prob({"a": 1.0, "b": 1.0})
    assert np.isfinite(lp)


def test_compile_deterministic_penalty():
    ir = _ir_with_factors(
        [CouplingFactorIR(coupling_type="deterministic_transform", source="a", target="b")]
    )
    compiled = compile_metamodel(ir, backend="pymc")
    # Exact match
    assert compiled.evaluate_log_prob({"a": 1.0, "b": 1.0}) == 0.0
    # Mismatch gets penalty
    assert compiled.evaluate_log_prob({"a": 1.0, "b": 2.0}) == _DETERMINISTIC_PENALTY


def test_compile_unsupported_backend():
    ir = _ir_with_factors([])
    with pytest.raises(ValueError, match="Unsupported backend"):
        compile_metamodel(ir, backend="jax_unknown")


def test_compile_surrogate_likelihood_no_surrogate_loaded():
    ir = _ir_with_factors(
        [SurrogateLikelihoodFactorIR(surrogate_ref="missing_ref", inputs=["x"], outputs=["y"])]
    )
    compiled = compile_metamodel(ir, backend="pymc")
    # No surrogate loaded, should contribute 0
    lp = compiled.evaluate_log_prob({"x": 0.0, "y": 0.0})
    assert lp == 0.0


def test_deterministic_constants():
    assert _DETERMINISTIC_PENALTY == -1e6
    assert _DETERMINISTIC_TOL == 1e-9
