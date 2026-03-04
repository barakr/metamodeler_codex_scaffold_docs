"""Extended metamodel coupling quality tests (slow, optional_backend)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import bayesian_metamodeling.meta.sampling as sampling_mod
from bayesian_metamodeling.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    VariableIR,
)
from bayesian_metamodeling.meta.sampling import _sample_core


@pytest.mark.slow
@pytest.mark.optional_backend
def test_sigma_tightening_reduces_coupling_variance(monkeypatch, tmp_path):
    """Smaller sigma in gaussian_link should produce tighter coupling."""
    registry_path = tmp_path / "reg.json"
    monkeypatch.setattr(sampling_mod, "META_SAMPLE_REGISTRY_PATH", registry_path)

    variances = []
    for sigma in [1.0, 0.1, 0.01]:
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
                    sigma=sigma,
                ),
            ],
        )
        result = _sample_core(
            backend="pymc",
            ir=ir,
            spec_payload={"name": "test"},
            dataset_digest="test",
            draws=200,
            tune=0,
            chains=1,
            seed=42,
        )
        dataset = json.loads(Path(result["samples_dataset_path"]).read_text())
        x_vals = np.array(dataset["variables"]["x"])
        y_vals = np.array(dataset["variables"]["y"])
        variances.append(float(np.var(y_vals - x_vals)))

    # Variance should decrease as sigma decreases
    assert variances[0] > variances[1] > variances[2]


@pytest.mark.slow
@pytest.mark.optional_backend
def test_deterministic_coupling_is_exact(monkeypatch, tmp_path):
    """Deterministic transform should produce exact coupling."""
    registry_path = tmp_path / "reg.json"
    monkeypatch.setattr(sampling_mod, "META_SAMPLE_REGISTRY_PATH", registry_path)

    ir = MetamodelIR(
        name="det_test",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(
                variable="x",
                distribution={"kind": "normal", "loc": 0.0, "scale": 1.0},
            ),
            CouplingFactorIR(
                coupling_type="deterministic_transform",
                source="x",
                target="y",
                transform={"kind": "affine", "alpha": 3.0, "beta": 2.0},
            ),
        ],
    )
    result = _sample_core(
        backend="pymc",
        ir=ir,
        spec_payload={"name": "det"},
        dataset_digest="test",
        draws=50,
        tune=0,
        chains=1,
        seed=0,
    )
    dataset = json.loads(Path(result["samples_dataset_path"]).read_text())
    x_vals = np.array(dataset["variables"]["x"])
    y_vals = np.array(dataset["variables"]["y"])
    np.testing.assert_allclose(y_vals, 3.0 * x_vals + 2.0, atol=1e-10)
