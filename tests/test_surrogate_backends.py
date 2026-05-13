import json
from pathlib import Path

import numpy as np
import pytest

import metamodeler.storage.surrogate_store as surrogate_store
import metamodeler.surrogates.backends as backends
from metamodeler.spec import SurrogateSpec
from metamodeler.surrogates import eval_surrogate, fit_surrogate
from metamodeler.surrogates.backends import load_backend_model


def _write_linear_run_store(root: Path, noise: float = 0.0) -> None:
    rng = np.random.default_rng(42)
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for idx in range(60):
        a = float(rng.uniform(-2, 2))
        b = float(rng.uniform(-1, 1))
        y = 1.7 * a - 0.8 * b + 0.2 + float(rng.normal(0, noise))
        run_dir = runs / f"run_{idx:03d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "inputs.json").write_text(json.dumps({"a": a, "b": b}))
        (run_dir / "outputs.json").write_text(json.dumps({"y": y}))


def _spec(
    backend: str,
    store_root: Path,
    seed: int = 123,
    backend_config: dict | None = None,
) -> SurrogateSpec:
    return SurrogateSpec.model_validate(
        {
            "schema_version": "1.0",
            "name": f"spec_{backend}",
            "kind": "conditional",
            "inputs": ["a", "b"],
            "outputs": ["y"],
            "backend": backend,
            "backend_config": backend_config or {},
            "dataset_ref": {"run_store_root": str(store_root)},
            "seed": seed,
        }
    )


def _artifact_payload_path(registry_path: Path) -> Path:
    registry = json.loads(registry_path.read_text())
    artifact_path = Path(next(iter(registry.values())))
    artifact = json.loads(artifact_path.read_text())
    return Path(artifact["backend_payload"])


def test_pymc_gp_backend_fit_sample_and_logprob(monkeypatch, tmp_path):
    pytest.importorskip("pymc")

    registry = tmp_path / "reg_pymc.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)

    store = tmp_path / "store_pymc"
    _write_linear_run_store(store, noise=0.05)

    spec = _spec(
        "pymc_gp",
        store,
        backend_config={"draws": 80, "tune": 80, "chains": 1, "target_accept": 0.9},
    )
    artifact = fit_surrogate(spec)

    payload_path = Path(artifact["backend_payload"])
    payload = json.loads(payload_path.read_text())
    assert payload["model_type"] == "pymc_bayesian_linear_v2"
    assert len(payload["posterior_sigma"]) > 0

    model = load_backend_model("pymc_gp", payload_path)
    inputs = {"a": np.array([0.1, 0.5]), "b": np.array([0.0, -0.2])}
    outputs = {"y": np.array([0.4, 1.4])}

    draws = model.sample(inputs, n=32, seed=7)
    logp = model.log_prob(inputs, outputs)
    summary = model.summary(inputs)
    target = 1.7 * np.asarray([0.1, 0.5]) - 0.8 * np.asarray([0.0, -0.2]) + 0.2
    mean_y = np.asarray(summary["mean"]["y"], dtype=float)
    mse = float(np.mean((mean_y - target) ** 2))

    assert draws.shape == (2, 32, 1)
    assert np.isfinite(logp).all()
    assert mse < 0.2
    assert summary["posterior_draws"] >= 20


def test_pymc_gp_backend_missing_dependency_has_actionable_error(monkeypatch, tmp_path):
    registry = tmp_path / "reg_missing_pymc.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)

    store = tmp_path / "store_missing_pymc"
    _write_linear_run_store(store, noise=0.05)

    spec = _spec("pymc_gp", store, backend_config={"draws": 5, "tune": 5, "chains": 1})

    def _raise_missing():
        raise RuntimeError("Backend 'pymc_gp' requires 'pymc'. Install in your conda env.")

    monkeypatch.setattr(backends, "_require_pymc", _raise_missing)

    with pytest.raises(RuntimeError, match="requires 'pymc'"):
        fit_surrogate(spec)


def test_sbi_npe_backend_fit_sample_and_logprob(monkeypatch, tmp_path):
    pytest.importorskip("sbi")
    pytest.importorskip("torch")

    registry = tmp_path / "reg_sbi.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)

    store = tmp_path / "store_sbi"
    _write_linear_run_store(store, noise=0.08)

    spec = _spec(
        "sbi_npe",
        store,
        backend_config={
            "density_estimator": "maf",
            "max_num_epochs": 80,
            "training_batch_size": 32,
            "learning_rate": 5e-4,
            "summary_samples": 128,
        },
    )
    artifact = fit_surrogate(spec)

    payload_path = Path(artifact["backend_payload"])
    payload = json.loads(payload_path.read_text())
    assert payload["model_type"] == "sbi_npe_posterior_v2"
    assert "posterior_blobs_b64" in payload

    model = load_backend_model("sbi_npe", payload_path)
    inputs = {"a": np.array([0.2, -0.1]), "b": np.array([0.3, 0.4])}
    outputs = {"y": np.array([0.1, -0.5])}

    draws = model.sample(inputs, n=16, seed=9)
    logp = model.log_prob(inputs, outputs)
    summary = model.summary(inputs)
    target = 1.7 * np.asarray([0.2, -0.1]) - 0.8 * np.asarray([0.3, 0.4]) + 0.2
    mean_y = np.asarray(summary["mean"]["y"], dtype=float)
    mse = float(np.mean((mean_y - target) ** 2))

    assert draws.shape == (2, 16, 1)
    assert np.isfinite(logp).all()
    assert mse < 0.35
    assert summary["posterior_draws"] >= 64


def test_sbi_npe_backend_missing_dependency_has_actionable_error(monkeypatch, tmp_path):
    registry = tmp_path / "reg_missing_sbi.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)

    store = tmp_path / "store_missing_sbi"
    _write_linear_run_store(store, noise=0.08)

    spec = _spec(
        "sbi_npe",
        store,
        backend_config={"max_num_epochs": 10, "training_batch_size": 16},
    )

    def _raise_missing():
        raise RuntimeError(
            "Backend 'sbi_npe' requires 'sbi' and 'torch'. Install in your conda env."
        )

    monkeypatch.setattr(backends, "_require_sbi", _raise_missing)

    with pytest.raises(
        RuntimeError, match=r"requires 'torch' and 'sbi'|requires 'sbi' and 'torch'"
    ):
        fit_surrogate(spec)


def test_backend_specific_fit_quality_increasing_difficulty(monkeypatch, tmp_path):
    registry = tmp_path / "reg_quality.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)

    store_easy = tmp_path / "store_easy"
    store_med = tmp_path / "store_med"
    store_hard = tmp_path / "store_hard"

    _write_linear_run_store(store_easy, noise=0.02)
    _write_linear_run_store(store_med, noise=0.1)
    _write_linear_run_store(store_hard, noise=0.2)

    has_pymc = backends.get_backend_dependency_versions("pymc_gp").get("pymc") != "not_installed"
    sbi_versions = backends.get_backend_dependency_versions("sbi_npe")
    has_sbi = (
        sbi_versions.get("sbi") != "not_installed" and sbi_versions.get("torch") != "not_installed"
    )
    if not has_pymc and not has_sbi:
        pytest.skip("No optional surrogate backend available for fit-quality checks")

    if has_pymc and has_sbi:
        backend_order = ["pymc_gp", "sbi_npe", "pymc_gp"]
    elif has_pymc:
        backend_order = ["pymc_gp"] * 3
    else:
        backend_order = ["sbi_npe"] * 3

    mse_values = []
    for idx, store in enumerate([store_easy, store_med, store_hard]):
        backend = backend_order[idx]
        if backend == "pymc_gp":
            config = {"draws": 60, "tune": 60, "chains": 1, "target_accept": 0.9}
        else:
            config = {
                "density_estimator": "maf",
                "max_num_epochs": 60,
                "training_batch_size": 32,
                "learning_rate": 5e-4,
                "summary_samples": 96,
            }
        spec = _spec(backend, store, seed=idx + 1, backend_config=config)
        fit_surrogate(spec)

        eval_result = eval_surrogate(
            spec,
            inputs_payload={"a": [0.1, 0.5, 1.0], "b": [0.2, -0.3, 0.7]},
            n=64,
        )
        means = np.asarray(eval_result["summary"]["mean"]["y"], dtype=float)
        target = 1.7 * np.asarray([0.1, 0.5, 1.0]) - 0.8 * np.asarray([0.2, -0.3, 0.7]) + 0.2
        mse_values.append(float(np.mean((means - target) ** 2)))

    assert mse_values[0] <= mse_values[1] + 0.1
    assert mse_values[1] <= mse_values[2] + 0.15
