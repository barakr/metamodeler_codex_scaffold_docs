"""Edge-case tests for metamodel IR, roundtrip, and sigma consistency."""

from __future__ import annotations

import pytest

from bayesian_metamodeling.meta.compiler import compile_metamodel
from bayesian_metamodeling.meta.ir import (
    DEFAULT_COUPLING_SIGMA,
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    SurrogateLikelihoodFactorIR,
    VariableIR,
    ir_from_json_dict,
    ir_to_json_dict,
)


def _simple_ir(**overrides):
    base = dict(
        name="test_ir",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(
                variable="x",
                distribution={"kind": "normal", "loc": 0.0, "scale": 1.0},
            ),
        ],
    )
    base.update(overrides)
    return MetamodelIR(**base)


def test_sigma_default_consistency():
    """Compiler and sampling both use DEFAULT_COUPLING_SIGMA for None sigma."""
    ir = MetamodelIR(
        name="sigma_test",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(
                variable="x",
                distribution={"kind": "normal", "loc": 0.0, "scale": 1.0},
            ),
            CouplingFactorIR(
                coupling_type="gaussian_link",
                source="x",
                target="y",
                sigma=None,
            ),
        ],
    )
    compiled = compile_metamodel(ir, backend="pymc")
    values = {"x": 0.0, "y": 0.0}
    lp = compiled.evaluate_log_prob(values)
    assert lp != 0.0
    assert DEFAULT_COUPLING_SIGMA == 0.1


def test_ir_roundtrip():
    ir = _simple_ir()
    payload = ir_to_json_dict(ir)
    restored = ir_from_json_dict(payload)
    assert restored.name == ir.name
    assert len(restored.variables) == len(ir.variables)
    assert len(restored.factors) == len(ir.factors)


def test_ir_zero_factors():
    ir = MetamodelIR(name="empty", variables=[VariableIR(name="x")], factors=[])
    assert len(ir.factors) == 0
    payload = ir_to_json_dict(ir)
    assert payload["factors"] == []


def test_coupling_kinds():
    for kind in ("equality_soft", "gaussian_link", "deterministic_transform"):
        c = CouplingFactorIR(coupling_type=kind, source="a", target="b")
        assert c.coupling_type == kind


def test_surrogate_likelihood_requires_inputs():
    with pytest.raises(Exception):
        SurrogateLikelihoodFactorIR(surrogate_ref="ref", inputs=[], outputs=["y"])


def test_variable_ir_defaults():
    v = VariableIR(name="x")
    assert v.type == "scalar"
    assert v.shape == []
    assert v.support is None
