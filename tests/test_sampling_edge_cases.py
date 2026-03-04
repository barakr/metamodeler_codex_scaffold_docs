"""Edge-case tests for metamodel sampling."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import bayesian_metamodeling.meta.sampling as sampling_mod
from bayesian_metamodeling.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    VariableIR,
)
from bayesian_metamodeling.meta.sampling import _sample_core


def _simple_ir(factors=None):
    return MetamodelIR(
        name="test_sample",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=factors
        or [
            PriorFactorIR(variable="x", distribution={"kind": "normal", "loc": 0.0, "scale": 1.0}),
            PriorFactorIR(variable="y", distribution={"kind": "normal", "loc": 0.0, "scale": 1.0}),
        ],
    )


def test_sample_determinism(monkeypatch, tmp_path):
    registry_path = tmp_path / "sample_reg.json"
    monkeypatch.setattr(sampling_mod, "META_SAMPLE_REGISTRY_PATH", registry_path)

    ir = _simple_ir()
    spec_payload = {"name": "test"}
    kwargs = dict(
        backend="pymc",
        ir=ir,
        spec_payload=spec_payload,
        dataset_digest="test",
        draws=10,
        tune=0,
        chains=1,
        seed=42,
    )
    r1 = _sample_core(**kwargs)
    r2 = _sample_core(**kwargs)

    d1 = json.loads(Path(r1["samples_dataset_path"]).read_text())
    d2 = json.loads(Path(r2["samples_dataset_path"]).read_text())
    assert d1["variables"]["x"] == d2["variables"]["x"]


def test_sample_writes_registry(monkeypatch, tmp_path):
    registry_path = tmp_path / "sample_reg.json"
    monkeypatch.setattr(sampling_mod, "META_SAMPLE_REGISTRY_PATH", registry_path)

    ir = _simple_ir()
    result = _sample_core(
        backend="pymc",
        ir=ir,
        spec_payload={"name": "test"},
        dataset_digest="test",
        draws=5,
        tune=0,
        chains=1,
        seed=0,
    )
    assert registry_path.exists()
    registry = json.loads(registry_path.read_text())
    assert result["sample_id"] in registry


def test_sample_coupling_applies_transform(monkeypatch, tmp_path):
    registry_path = tmp_path / "sample_reg.json"
    monkeypatch.setattr(sampling_mod, "META_SAMPLE_REGISTRY_PATH", registry_path)

    ir = MetamodelIR(
        name="coupled",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(
                variable="x", distribution={"kind": "normal", "loc": 5.0, "scale": 0.001}
            ),
            CouplingFactorIR(
                coupling_type="deterministic_transform",
                source="x",
                target="y",
                transform={"kind": "affine", "alpha": 2.0, "beta": 1.0},
            ),
        ],
    )
    result = _sample_core(
        backend="pymc",
        ir=ir,
        spec_payload={"name": "coupled"},
        dataset_digest="test",
        draws=10,
        tune=0,
        chains=1,
        seed=0,
    )
    dataset = json.loads(Path(result["samples_dataset_path"]).read_text())
    x_vals = np.array(dataset["variables"]["x"])
    y_vals = np.array(dataset["variables"]["y"])
    np.testing.assert_allclose(y_vals, 2 * x_vals + 1, atol=0.1)


def test_sample_numpyro_backend(monkeypatch, tmp_path):
    registry_path = tmp_path / "sample_reg.json"
    monkeypatch.setattr(sampling_mod, "META_SAMPLE_REGISTRY_PATH", registry_path)

    ir = _simple_ir()
    result = _sample_core(
        backend="numpyro",
        ir=ir,
        spec_payload={"name": "test"},
        dataset_digest="test",
        draws=5,
        tune=0,
        chains=1,
        seed=0,
    )
    dataset = json.loads(Path(result["samples_dataset_path"]).read_text())
    assert "x" in dataset["variables"]
    assert "y" in dataset["variables"]
