"""Multi-output surrogate fit + sample + log_prob tests for PyMC and SBI backends."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import metamodeler.storage.surrogate_store as surrogate_store
from metamodeler.spec import SurrogateSpec
from metamodeler.surrogates import fit_surrogate
from metamodeler.surrogates.backends import load_backend_model


def _write_two_output_run_store(root: Path, n: int = 80, noise: float = 0.05) -> None:
    """y1 = 1.7 a - 0.8 b + 0.2; y2 = -0.5 a + 1.2 b - 0.3 (correlated by sharing a, b)."""
    rng = np.random.default_rng(7)
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for idx in range(n):
        a = float(rng.uniform(-2, 2))
        b = float(rng.uniform(-1, 1))
        y1 = 1.7 * a - 0.8 * b + 0.2 + float(rng.normal(0, noise))
        y2 = -0.5 * a + 1.2 * b - 0.3 + float(rng.normal(0, noise))
        run_dir = runs / f"run_{idx:03d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "inputs.json").write_text(json.dumps({"a": a, "b": b}))
        (run_dir / "outputs.json").write_text(json.dumps({"y1": y1, "y2": y2}))


def _multi_spec(
    backend: str,
    store_root: Path,
    *,
    output_correlation: str = "diagonal",
    seed: int = 17,
    extra_config: dict | None = None,
) -> SurrogateSpec:
    config = {"output_correlation": output_correlation}
    if extra_config:
        config.update(extra_config)
    return SurrogateSpec.model_validate(
        {
            "schema_version": "1.0",
            "name": f"multi_{backend}_{output_correlation}",
            "kind": "joint",
            "inputs": ["a", "b"],
            "outputs": ["y1", "y2"],
            "backend": backend,
            "backend_config": config,
            "dataset_ref": {"run_store_root": str(store_root)},
            "seed": seed,
        }
    )


def test_pymc_gp_multi_output_diagonal_fit_sample_logprob(monkeypatch, tmp_path):
    pytest.importorskip("pymc")

    registry = tmp_path / "reg.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)
    store = tmp_path / "store"
    _write_two_output_run_store(store)

    spec = _multi_spec(
        "pymc_gp",
        store,
        output_correlation="diagonal",
        extra_config={"draws": 80, "tune": 80, "chains": 1, "target_accept": 0.9},
    )
    artifact = fit_surrogate(spec)

    payload = json.loads(Path(artifact["backend_payload"]).read_text())
    assert payload["model_type"] == "pymc_bayesian_linear_v2"
    assert payload["output_correlation"] == "diagonal"
    assert payload["output_names"] == ["y1", "y2"]
    assert "posterior_sigma" in payload

    model = load_backend_model("pymc_gp", Path(artifact["backend_payload"]))
    inputs = {"a": np.array([0.1, 0.5, -0.3]), "b": np.array([0.0, -0.2, 0.4])}
    outputs = {
        "y1": np.array([0.4, 1.4, -0.6]),
        "y2": np.array([-0.4, -0.8, 0.4]),
    }

    samples = model.sample(inputs, n=24, seed=11)
    logp = model.log_prob(inputs, outputs)
    summary = model.summary(inputs)

    assert samples.shape == (3, 24, 2)
    assert np.isfinite(logp).all()
    assert set(summary["mean"].keys()) == {"y1", "y2"}
    assert summary["output_correlation"] == "diagonal"


def test_pymc_gp_multi_output_full_cov_runs_and_recovers_means(monkeypatch, tmp_path):
    pytest.importorskip("pymc")

    registry = tmp_path / "reg_full.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)
    store = tmp_path / "store_full"
    _write_two_output_run_store(store, n=120, noise=0.02)

    spec = _multi_spec(
        "pymc_gp",
        store,
        output_correlation="full",
        extra_config={"draws": 100, "tune": 100, "chains": 1, "target_accept": 0.9},
    )
    artifact = fit_surrogate(spec)

    payload = json.loads(Path(artifact["backend_payload"]).read_text())
    assert payload["output_correlation"] == "full"
    assert "posterior_chol" in payload

    model = load_backend_model("pymc_gp", Path(artifact["backend_payload"]))
    inputs = {"a": np.array([0.5, -0.5, 1.0]), "b": np.array([0.3, -0.3, 0.5])}
    summary = model.summary(inputs)

    target_y1 = 1.7 * np.array([0.5, -0.5, 1.0]) - 0.8 * np.array([0.3, -0.3, 0.5]) + 0.2
    target_y2 = -0.5 * np.array([0.5, -0.5, 1.0]) + 1.2 * np.array([0.3, -0.3, 0.5]) - 0.3
    mse1 = float(np.mean((np.array(summary["mean"]["y1"]) - target_y1) ** 2))
    mse2 = float(np.mean((np.array(summary["mean"]["y2"]) - target_y2) ** 2))

    assert mse1 < 0.3, mse1
    assert mse2 < 0.3, mse2


def test_sbi_npe_multi_output_diagonal_fit_sample_logprob(monkeypatch, tmp_path):
    pytest.importorskip("sbi")
    pytest.importorskip("torch")

    registry = tmp_path / "reg_sbi_diag.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)
    store = tmp_path / "store_sbi_diag"
    _write_two_output_run_store(store, noise=0.08)

    spec = _multi_spec(
        "sbi_npe",
        store,
        output_correlation="diagonal",
        extra_config={
            "density_estimator": "maf",
            "max_num_epochs": 80,
            "training_batch_size": 16,
            "summary_samples": 64,
        },
    )
    artifact = fit_surrogate(spec)

    payload = json.loads(Path(artifact["backend_payload"]).read_text())
    assert payload["model_type"] == "sbi_npe_posterior_v2"
    assert payload["output_correlation"] == "diagonal"
    assert len(payload["posterior_blobs_b64"]) == 2

    model = load_backend_model("sbi_npe", Path(artifact["backend_payload"]))
    inputs = {"a": np.array([0.2, -0.1]), "b": np.array([0.3, 0.4])}
    outputs = {"y1": np.array([0.1, -0.5]), "y2": np.array([0.0, 0.2])}

    samples = model.sample(inputs, n=12, seed=3)
    logp = model.log_prob(inputs, outputs)
    summary = model.summary(inputs)

    assert samples.shape == (2, 12, 2)
    assert np.isfinite(logp).all()
    assert set(summary["mean"].keys()) == {"y1", "y2"}


def test_sbi_npe_multi_output_full_joint_fit_sample_logprob(monkeypatch, tmp_path):
    pytest.importorskip("sbi")
    pytest.importorskip("torch")

    registry = tmp_path / "reg_sbi_full.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)
    store = tmp_path / "store_sbi_full"
    _write_two_output_run_store(store, noise=0.08)

    spec = _multi_spec(
        "sbi_npe",
        store,
        output_correlation="full",
        extra_config={
            "density_estimator": "maf",
            "max_num_epochs": 100,
            "training_batch_size": 16,
            "summary_samples": 64,
        },
    )
    artifact = fit_surrogate(spec)

    payload = json.loads(Path(artifact["backend_payload"]).read_text())
    assert payload["output_correlation"] == "full"
    assert len(payload["posterior_blobs_b64"]) == 1

    model = load_backend_model("sbi_npe", Path(artifact["backend_payload"]))
    inputs = {"a": np.array([0.5, -0.5]), "b": np.array([0.3, -0.3])}
    samples = model.sample(inputs, n=10, seed=4)
    logp = model.log_prob(inputs, outputs={"y1": np.array([0.5, -1.0]), "y2": np.array([0.0, 0.2])})

    assert samples.shape == (2, 10, 2)
    assert np.isfinite(logp).all()


def test_surrogate_spec_allows_multi_output():
    spec = SurrogateSpec.model_validate(
        {
            "schema_version": "1.0",
            "name": "multi",
            "kind": "joint",
            "inputs": ["a"],
            "outputs": ["y1", "y2", "y3"],
            "backend": "pymc_gp",
            "backend_config": {"output_correlation": "full"},
            "dataset_ref": "tmp/store_unused",
            "seed": 0,
        }
    )
    assert spec.outputs == ["y1", "y2", "y3"]


def test_surrogate_spec_rejects_duplicate_outputs():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Duplicate output"):
        SurrogateSpec.model_validate(
            {
                "schema_version": "1.0",
                "name": "dup",
                "kind": "joint",
                "inputs": ["a"],
                "outputs": ["y", "y"],
                "backend": "pymc_gp",
                "backend_config": {},
                "dataset_ref": "tmp/store_unused",
                "seed": 0,
            }
        )


def test_surrogate_spec_rejects_unknown_output_correlation():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="output_correlation"):
        SurrogateSpec.model_validate(
            {
                "schema_version": "1.0",
                "name": "bad_corr",
                "kind": "joint",
                "inputs": ["a"],
                "outputs": ["y"],
                "backend": "pymc_gp",
                "backend_config": {"output_correlation": "block_diagonal"},
                "dataset_ref": "tmp/store_unused",
                "seed": 0,
            }
        )
