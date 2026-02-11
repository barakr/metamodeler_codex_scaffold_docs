"""Surrogate backend implementations behind a neutral interface."""

from __future__ import annotations

import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.special import logsumexp

from metamodeler.surrogates import SurrogateModel


@dataclass
class LinearGaussianModel:
    weights: np.ndarray
    bias: float
    sigma: float
    input_names: list[str]
    output_name: str

    def _x(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        return np.column_stack(
            [np.asarray(inputs[name], dtype=float).reshape(-1) for name in self.input_names]
        )

    def _mean(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        x = self._x(inputs)
        return x @ self.weights + self.bias

    def sample(self, inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray:
        mean = self._mean(inputs)
        rng = np.random.default_rng(seed)
        return rng.normal(loc=mean[:, None], scale=self.sigma, size=(len(mean), n))

    def log_prob(self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray:
        mean = self._mean(inputs)
        y = np.asarray(outputs[self.output_name], dtype=float).reshape(-1)
        var = self.sigma**2
        return -0.5 * (np.log(2 * np.pi * var) + ((y - mean) ** 2) / var)

    def summary(self, inputs: dict[str, np.ndarray]) -> dict:
        mean = self._mean(inputs)
        return {"mean": mean.tolist(), "sigma": self.sigma, "n": int(len(mean))}


class PymcGPSurrogateModel(LinearGaussianModel):
    """Pragmatic baseline that exposes a pymc_gp backend contract."""


class SbiNPESurrogateModel(LinearGaussianModel):
    """Pragmatic baseline that exposes an sbi_npe-like contract."""


@dataclass
class PymcPosteriorLinearModel:
    posterior_weights: np.ndarray
    posterior_bias: np.ndarray
    posterior_sigma: np.ndarray
    input_names: list[str]
    output_name: str

    def _x(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        return np.column_stack(
            [np.asarray(inputs[name], dtype=float).reshape(-1) for name in self.input_names]
        )

    def _predictive_mu(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        x = self._x(inputs)
        return x @ self.posterior_weights.T + self.posterior_bias[None, :]

    def sample(self, inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray:
        mu = self._predictive_mu(inputs=inputs)
        n_rows, n_draws = mu.shape
        rng = np.random.default_rng(seed)
        draw_idx = rng.integers(0, n_draws, size=(n_rows, n))
        selected_mu = np.take_along_axis(mu, draw_idx, axis=1)
        selected_sigma = np.take(self.posterior_sigma, draw_idx)
        return rng.normal(loc=selected_mu, scale=selected_sigma)

    def log_prob(self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray:
        mu = self._predictive_mu(inputs=inputs)
        sigma = np.clip(self.posterior_sigma, a_min=1e-8, a_max=None)[None, :]
        y = np.asarray(outputs[self.output_name], dtype=float).reshape(-1, 1)
        var = sigma**2
        component_logp = -0.5 * (np.log(2 * np.pi * var) + ((y - mu) ** 2) / var)
        return logsumexp(component_logp, axis=1) - np.log(mu.shape[1])

    def summary(self, inputs: dict[str, np.ndarray]) -> dict:
        mu = self._predictive_mu(inputs=inputs)
        point_mean = np.mean(mu, axis=1)
        predictive_std = np.sqrt(
            np.mean((mu - point_mean[:, None]) ** 2 + self.posterior_sigma[None, :] ** 2, axis=1)
        )
        return {
            "mean": point_mean.tolist(),
            "std": predictive_std.tolist(),
            "posterior_draws": int(mu.shape[1]),
            "n": int(len(point_mean)),
        }


class _ModelWrapper(SurrogateModel):
    def __init__(self, model: SurrogateModel) -> None:
        self.model = model

    def sample(self, inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray:
        return self.model.sample(inputs, n, seed)

    def log_prob(self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray:
        return self.model.log_prob(inputs, outputs)

    def summary(self, inputs: dict[str, np.ndarray]) -> dict:
        return self.model.summary(inputs)


def _fit_linear(
    x: np.ndarray, y: np.ndarray, input_names: list[str], output_name: str
) -> LinearGaussianModel:
    x_design = np.column_stack([x, np.ones(len(x))])
    beta, *_ = np.linalg.lstsq(x_design, y, rcond=None)
    weights = np.asarray(beta[:-1], dtype=float)
    bias = float(beta[-1])
    residual = y - (x @ weights + bias)
    sigma = float(max(np.sqrt(np.mean(residual**2)), 1e-6))
    return LinearGaussianModel(
        weights=weights,
        bias=bias,
        sigma=sigma,
        input_names=input_names,
        output_name=output_name,
    )


def _require_pymc():
    try:
        import pymc as pm  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Backend 'pymc_gp' requires 'pymc'. "
            "Install in your conda env: "
            "`conda install -n py314_metamodeling -c conda-forge pymc arviz` "
            "or use `pip install 'metamodeler[pymc]'`."
        ) from exc
    return pm


def _fit_pymc_bayesian_linear(
    *,
    x: np.ndarray,
    y: np.ndarray,
    input_names: list[str],
    output_name: str,
    backend_config: dict[str, Any],
    seed: int,
) -> PymcPosteriorLinearModel:
    pm = _require_pymc()
    draws = int(backend_config.get("draws", 300))
    tune = int(backend_config.get("tune", 300))
    chains = int(backend_config.get("chains", 1))
    target_accept = float(backend_config.get("target_accept", 0.9))

    with pm.Model():
        beta = pm.Normal("beta", mu=0.0, sigma=2.0, shape=x.shape[1])
        intercept = pm.Normal("intercept", mu=0.0, sigma=2.0)
        sigma = pm.HalfNormal("sigma", sigma=1.0)
        mu = intercept + pm.math.dot(x, beta)
        pm.Normal("obs", mu=mu, sigma=sigma, observed=y)
        idata = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            cores=1,
            random_seed=seed,
            target_accept=target_accept,
            progressbar=False,
            compute_convergence_checks=False,
        )

    posterior_weights = np.asarray(idata.posterior["beta"], dtype=float).reshape(-1, x.shape[1])
    posterior_bias = np.asarray(idata.posterior["intercept"], dtype=float).reshape(-1)
    posterior_sigma = np.asarray(idata.posterior["sigma"], dtype=float).reshape(-1)
    posterior_sigma = np.clip(posterior_sigma, a_min=1e-8, a_max=None)

    return PymcPosteriorLinearModel(
        posterior_weights=posterior_weights,
        posterior_bias=posterior_bias,
        posterior_sigma=posterior_sigma,
        input_names=input_names,
        output_name=output_name,
    )


def fit_backend_model(
    *,
    backend: str,
    x: np.ndarray,
    y: np.ndarray,
    input_names: list[str],
    output_name: str,
    backend_config: dict[str, Any] | None = None,
    seed: int = 0,
):
    config = backend_config or {}
    if backend == "pymc_gp":
        return _fit_pymc_bayesian_linear(
            x=x,
            y=y,
            input_names=input_names,
            output_name=output_name,
            backend_config=config,
            seed=seed,
        )
    if backend == "sbi_npe":
        model = _fit_linear(x=x, y=y, input_names=input_names, output_name=output_name)
        return SbiNPESurrogateModel(**model.__dict__)
    raise ValueError(f"Unsupported backend: {backend}")


def save_backend_payload(model: SurrogateModel, payload_path: Path) -> None:
    if isinstance(model, PymcPosteriorLinearModel):
        payload = {
            "model_type": "pymc_bayesian_linear",
            "posterior_weights": model.posterior_weights.tolist(),
            "posterior_bias": model.posterior_bias.tolist(),
            "posterior_sigma": model.posterior_sigma.tolist(),
            "input_names": model.input_names,
            "output_name": model.output_name,
        }
    elif isinstance(model, LinearGaussianModel):
        payload = {
            "model_type": "linear_gaussian",
            "weights": model.weights.tolist(),
            "bias": model.bias,
            "sigma": model.sigma,
            "input_names": model.input_names,
            "output_name": model.output_name,
        }
    else:
        raise ValueError(f"Unsupported surrogate model type for payload save: {type(model)}")

    payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def load_backend_model(backend: str, payload_path: Path) -> SurrogateModel:
    payload = json.loads(payload_path.read_text())
    model_type = payload.get("model_type", "linear_gaussian")

    if backend == "pymc_gp":
        if model_type == "pymc_bayesian_linear":
            model = PymcPosteriorLinearModel(
                posterior_weights=np.asarray(payload["posterior_weights"], dtype=float),
                posterior_bias=np.asarray(payload["posterior_bias"], dtype=float),
                posterior_sigma=np.asarray(payload["posterior_sigma"], dtype=float),
                input_names=list(payload["input_names"]),
                output_name=str(payload["output_name"]),
            )
        elif model_type == "linear_gaussian":
            model = PymcGPSurrogateModel(
                weights=np.asarray(payload["weights"], dtype=float),
                bias=float(payload["bias"]),
                sigma=float(payload["sigma"]),
                input_names=list(payload["input_names"]),
                output_name=str(payload["output_name"]),
            )
        else:
            raise ValueError(f"Unsupported payload model_type for pymc_gp: {model_type}")
    elif backend == "sbi_npe":
        if model_type != "linear_gaussian":
            raise ValueError(f"Unsupported payload model_type for sbi_npe: {model_type}")
        model = SbiNPESurrogateModel(
            weights=np.asarray(payload["weights"], dtype=float),
            bias=float(payload["bias"]),
            sigma=float(payload["sigma"]),
            input_names=list(payload["input_names"]),
            output_name=str(payload["output_name"]),
        )
    else:
        raise ValueError(f"Unsupported backend: {backend}")
    return _ModelWrapper(model)


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


def get_backend_dependency_versions(backend: str) -> dict[str, str]:
    versions = {
        "numpy": np.__version__,
        "scipy": _package_version("scipy"),
    }
    if backend == "pymc_gp":
        versions["pymc"] = _package_version("pymc")
        versions["arviz"] = _package_version("arviz")
    return versions
