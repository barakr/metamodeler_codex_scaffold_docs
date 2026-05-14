"""Verify that pre-existing v1 payload artifacts still load via the v2 reader."""

from __future__ import annotations

import json

import numpy as np

import bayesian_metamodeling.surrogates.backends as backends
from bayesian_metamodeling.surrogates.backends import load_backend_model


def test_pymc_v1_payload_loads_as_d1_v2(tmp_path):
    payload = {
        "model_type": "pymc_bayesian_linear",
        "posterior_weights": [[0.5, 0.3], [0.6, 0.4], [0.55, 0.35]],
        "posterior_bias": [0.1, 0.15, 0.12],
        "posterior_sigma": [0.2, 0.22, 0.21],
        "input_names": ["a", "b"],
        "output_name": "y",
    }
    payload_path = tmp_path / "v1_pymc.json"
    payload_path.write_text(json.dumps(payload))

    model = load_backend_model("pymc_gp", payload_path)
    inputs = {"a": np.array([0.1, 0.5]), "b": np.array([0.0, -0.2])}
    outputs = {"y": np.array([0.2, 0.3])}

    samples = model.sample(inputs, n=8, seed=1)
    logp = model.log_prob(inputs, outputs)
    summary = model.summary(inputs)

    # Single-output models use the squeeze form: samples (N, n), summary["mean"]
    # a flat list of length N (not a dict keyed by output name).
    assert samples.shape == (2, 8)
    assert np.isfinite(logp).all()
    assert isinstance(summary["mean"], list)
    assert len(summary["mean"]) == 2


def test_pymc_v1_linear_gaussian_payload_loads(tmp_path):
    """The fallback `linear_gaussian` model_type still loads single-output."""
    payload = {
        "model_type": "linear_gaussian",
        "weights": [0.5, 0.3],
        "bias": 0.1,
        "sigma": 0.2,
        "input_names": ["a", "b"],
        "output_name": "y",
    }
    payload_path = tmp_path / "v1_linear.json"
    payload_path.write_text(json.dumps(payload))

    model = load_backend_model("pymc_gp", payload_path)
    inputs = {"a": np.array([0.1]), "b": np.array([0.2])}
    samples = model.sample(inputs, n=4, seed=0)
    assert samples.shape == (1, 4)


def test_sbi_v1_payload_loads_as_d1_v2(tmp_path, monkeypatch):
    """An old single-output SBI v1 payload loads through the v2 reader as D=1."""

    class _FakePosterior:
        def sample(self, shape, x):  # noqa: ARG002 — interface stub
            return None

        def log_prob(self, theta, x):  # noqa: ARG002 — interface stub
            return None

    monkeypatch.setattr(backends, "_require_sbi", lambda: object())
    monkeypatch.setattr(backends, "_deserialize_torch_object", lambda _blob: _FakePosterior())

    payload = {
        "model_type": "sbi_npe_posterior",
        "serialization": "torch_save_base64",
        "posterior_blob_b64": "fake_blob",
        "input_names": ["a", "b"],
        "output_name": "y",
        "x_mean": [0.0, 0.0],
        "x_scale": [1.0, 1.0],
        "y_mean": 0.0,
        "y_scale": 1.0,
        "summary_samples": 32,
    }
    payload_path = tmp_path / "v1_sbi.json"
    payload_path.write_text(json.dumps(payload))

    model = load_backend_model("sbi_npe", payload_path)
    assert model.model.output_names == ["y"]
    assert model.model.output_correlation == "full"
    # v1 scalar y_mean/y_scale are promoted to length-1 arrays.
    assert model.model.y_mean.shape == (1,)
    assert model.model.summary_samples == 32
