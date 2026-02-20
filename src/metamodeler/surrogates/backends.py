"""Surrogate backend implementations behind a neutral interface."""

from __future__ import annotations

import base64
import importlib.metadata
import io
import json
import os
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np
from scipy.special import logsumexp

from metamodeler.surrogate_config import validate_backend_config
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
    """Legacy linear payload compatibility wrapper for pymc_gp."""


class SbiNPESurrogateModel(LinearGaussianModel):
    """Legacy linear payload compatibility wrapper for sbi_npe."""


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


@dataclass
class SbiNPEPosteriorModel:
    posterior: Any
    input_names: list[str]
    output_name: str
    x_mean: np.ndarray
    x_scale: np.ndarray
    y_mean: float
    y_scale: float
    summary_samples: int = 256

    def _normalized_x(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        x_raw = np.column_stack(
            [np.asarray(inputs[name], dtype=float).reshape(-1) for name in self.input_names]
        )
        return (x_raw - self.x_mean[None, :]) / self.x_scale[None, :]

    def sample(self, inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray:
        torch = _require_torch()
        x_norm = self._normalized_x(inputs)
        rows: list[np.ndarray] = []

        for idx, row in enumerate(x_norm):
            torch.manual_seed(seed + idx)
            obs = torch.as_tensor(row, dtype=torch.float32)
            sampled = self.posterior.sample((n,), x=obs)
            sample_np = np.asarray(sampled.detach().cpu().numpy(), dtype=float).reshape(n, -1)
            denorm = sample_np[:, 0] * self.y_scale + self.y_mean
            rows.append(denorm)

        return np.vstack(rows)

    def log_prob(self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray:
        torch = _require_torch()
        x_norm = self._normalized_x(inputs)
        y = np.asarray(outputs[self.output_name], dtype=float).reshape(-1)
        if len(y) != len(x_norm):
            raise ValueError("Output length must match number of input rows for log_prob")

        y_norm = ((y - self.y_mean) / self.y_scale).astype(np.float32)
        logp: list[float] = []

        for idx, row in enumerate(x_norm):
            obs = torch.as_tensor(row, dtype=torch.float32)
            theta = torch.as_tensor([y_norm[idx]], dtype=torch.float32)
            value = self.posterior.log_prob(theta, x=obs)
            scalar = float(np.asarray(value.detach().cpu().numpy(), dtype=float).reshape(-1)[0])
            # Correct for affine re-scaling from normalized y-space back to original units.
            logp.append(scalar - np.log(self.y_scale))

        return np.asarray(logp, dtype=float)

    def summary(self, inputs: dict[str, np.ndarray]) -> dict:
        draws = self.sample(inputs=inputs, n=self.summary_samples, seed=0)
        return {
            "mean": np.mean(draws, axis=1).tolist(),
            "std": np.std(draws, axis=1).tolist(),
            "posterior_draws": int(self.summary_samples),
            "n": int(draws.shape[0]),
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


_ARVIZ_REFACTOR_WARNING_PATTERN = r"\s*ArviZ is undergoing a major refactor.*"


@contextmanager
def _optional_backend_import_context() -> Iterator[None]:
    cache_root = (Path("tmp") / ".cache").resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    home_root = (Path("tmp") / "home").resolve()
    home_root.mkdir(parents=True, exist_ok=True)
    mplconfig_root = (Path("tmp") / "matplotlib").resolve()
    mplconfig_root.mkdir(parents=True, exist_ok=True)

    previous_home = os.environ.get("HOME")
    previous_mplconfigdir = os.environ.get("MPLCONFIGDIR")
    previous_xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    os.environ["HOME"] = str(home_root)
    os.environ["MPLCONFIGDIR"] = str(mplconfig_root)
    os.environ["XDG_CACHE_HOME"] = str(cache_root)
    try:
        with warnings.catch_warnings():
            # ArviZ emits this startup warning during import in recent releases.
            warnings.filterwarnings(
                "ignore",
                message=_ARVIZ_REFACTOR_WARNING_PATTERN,
                category=FutureWarning,
            )
            yield
    finally:
        if previous_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous_home
        if previous_mplconfigdir is None:
            os.environ.pop("MPLCONFIGDIR", None)
        else:
            os.environ["MPLCONFIGDIR"] = previous_mplconfigdir
        if previous_xdg_cache_home is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = previous_xdg_cache_home


def _require_pymc():
    try:
        with _optional_backend_import_context():
            import pymc as pm  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Backend 'pymc_gp' requires 'pymc'. "
            "Install in your conda env: "
            "`conda install -n <env_name> -c conda-forge pymc arviz` "
            "or use `pip install 'metamodeler[pymc]'`."
        ) from exc
    return pm


def _require_torch():
    try:
        import torch  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Backend 'sbi_npe' requires 'torch' and 'sbi'. "
            "Install in your conda env: "
            "`conda install -n <env_name> -c conda-forge pytorch sbi` "
            "or use `pip install 'metamodeler[sbi]'`."
        ) from exc
    return torch


def _require_sbi():
    try:
        import sbi  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Backend 'sbi_npe' requires 'sbi' and 'torch'. "
            "Install in your conda env: "
            "`conda install -n <env_name> -c conda-forge pytorch sbi` "
            "or use `pip install 'metamodeler[sbi]'`."
        ) from exc
    return sbi


class _NoOpSummaryWriter:
    def __init__(self, log_dir: str) -> None:
        self.log_dir = log_dir

    def __getattr__(self, _name: str):
        def _noop(*_args, **_kwargs):
            return None

        return _noop


def _make_sbi_summary_writer() -> Any:
    log_root = Path("tmp") / "sbi-logs"
    log_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat().replace(":", "_")
    log_dir = log_root / f"npe_{timestamp}"
    try:
        from torch.utils.tensorboard import SummaryWriter  # type: ignore[import-not-found]

        return SummaryWriter(log_dir=str(log_dir))
    except Exception:
        # Keep runtime robust even when tensorboard writer extras are unavailable.
        return _NoOpSummaryWriter(log_dir=str(log_dir))


def _build_sbi_inference(density_estimator: str):
    _require_sbi()
    summary_writer = _make_sbi_summary_writer()
    with _optional_backend_import_context():
        try:
            from sbi.inference import NPE  # type: ignore[import-not-found]

            return NPE(density_estimator=density_estimator, summary_writer=summary_writer)
        except Exception:
            from sbi.inference import SNPE  # type: ignore[import-not-found]

            return SNPE(
                prior=None,
                density_estimator=density_estimator,
                summary_writer=summary_writer,
            )


def _train_sbi_density_estimator(
    inference: Any, theta: Any, x: Any, backend_config: dict[str, Any]
) -> Any:
    trainer = inference.append_simulations(theta, x)
    train_kwargs = {
        "max_num_epochs": int(backend_config.get("max_num_epochs", 120)),
        "training_batch_size": int(backend_config.get("training_batch_size", 32)),
        "learning_rate": float(backend_config.get("learning_rate", 5e-4)),
        "validation_fraction": float(backend_config.get("validation_fraction", 0.1)),
        "stop_after_epochs": int(backend_config.get("stop_after_epochs", 20)),
        "show_train_summary": bool(backend_config.get("show_train_summary", False)),
    }

    with warnings.catch_warnings():
        # sbi emits this for 1D outputs with flow families; this is expected and non-fatal.
        warnings.filterwarnings(
            "ignore",
            message="In one-dimensional output space, this flow is limited to Gaussians",
            category=UserWarning,
        )
        try:
            return trainer.train(**train_kwargs)
        except TypeError:
            # Compatibility path for sbi versions that do not support the full train kwargs.
            fallback = {
                "max_num_epochs": train_kwargs["max_num_epochs"],
                "training_batch_size": train_kwargs["training_batch_size"],
            }
            return trainer.train(**fallback)


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


def _fit_sbi_npe(
    *,
    x: np.ndarray,
    y: np.ndarray,
    input_names: list[str],
    output_name: str,
    backend_config: dict[str, Any],
    seed: int,
) -> SbiNPEPosteriorModel:
    torch = _require_torch()
    _require_sbi()

    x_mean = np.mean(x, axis=0)
    x_scale = np.std(x, axis=0)
    x_scale = np.where(x_scale < 1e-8, 1.0, x_scale)

    y_mean = float(np.mean(y))
    y_scale = float(max(np.std(y), 1e-8))

    x_norm = ((x - x_mean[None, :]) / x_scale[None, :]).astype(np.float32)
    theta_norm = ((y - y_mean) / y_scale).astype(np.float32).reshape(-1, 1)

    torch.manual_seed(seed)
    theta = torch.as_tensor(theta_norm, dtype=torch.float32)
    observations = torch.as_tensor(x_norm, dtype=torch.float32)

    density_estimator_name = str(backend_config.get("density_estimator", "maf"))
    inference = _build_sbi_inference(density_estimator=density_estimator_name)
    density_estimator = _train_sbi_density_estimator(
        inference=inference,
        theta=theta,
        x=observations,
        backend_config=backend_config,
    )
    posterior = inference.build_posterior(density_estimator)

    return SbiNPEPosteriorModel(
        posterior=posterior,
        input_names=input_names,
        output_name=output_name,
        x_mean=np.asarray(x_mean, dtype=float),
        x_scale=np.asarray(x_scale, dtype=float),
        y_mean=y_mean,
        y_scale=y_scale,
        summary_samples=int(backend_config.get("summary_samples", 256)),
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
    config = validate_backend_config(backend, backend_config or {})
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
        return _fit_sbi_npe(
            x=x,
            y=y,
            input_names=input_names,
            output_name=output_name,
            backend_config=config,
            seed=seed,
        )
    raise ValueError(f"Unsupported backend: {backend}")


def _serialize_torch_object(payload: Any) -> str:
    torch = _require_torch()
    buffer = io.BytesIO()
    torch.save(payload, buffer)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _deserialize_torch_object(serialized: str) -> Any:
    torch = _require_torch()
    buffer = io.BytesIO(base64.b64decode(serialized.encode("ascii")))
    try:
        return torch.load(buffer, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(buffer, map_location="cpu")


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
    elif isinstance(model, SbiNPEPosteriorModel):
        payload = {
            "model_type": "sbi_npe_posterior",
            "serialization": "torch_save_base64",
            "posterior_blob_b64": _serialize_torch_object(model.posterior),
            "input_names": model.input_names,
            "output_name": model.output_name,
            "x_mean": model.x_mean.tolist(),
            "x_scale": model.x_scale.tolist(),
            "y_mean": model.y_mean,
            "y_scale": model.y_scale,
            "summary_samples": model.summary_samples,
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


def load_backend_model(
    backend: str,
    payload_path: Path,
    *,
    expected_inputs: list[str] | None = None,
    expected_output: str | None = None,
) -> SurrogateModel:
    payload = json.loads(payload_path.read_text())
    model_type = payload.get("model_type", "linear_gaussian")
    payload_inputs = list(payload.get("input_names", []))
    payload_output = str(payload.get("output_name", ""))

    if expected_inputs is not None and payload_inputs != expected_inputs:
        raise ValueError(
            "Surrogate payload input order mismatch: "
            f"artifact has {payload_inputs}, spec expects {expected_inputs}."
        )
    if expected_output is not None and payload_output != expected_output:
        raise ValueError(
            "Surrogate payload output mismatch: "
            f"artifact has '{payload_output}', spec expects '{expected_output}'."
        )

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
        if model_type == "sbi_npe_posterior":
            _require_sbi()
            model = SbiNPEPosteriorModel(
                posterior=_deserialize_torch_object(payload["posterior_blob_b64"]),
                input_names=list(payload["input_names"]),
                output_name=str(payload["output_name"]),
                x_mean=np.asarray(payload["x_mean"], dtype=float),
                x_scale=np.asarray(payload["x_scale"], dtype=float),
                y_mean=float(payload["y_mean"]),
                y_scale=float(payload["y_scale"]),
                summary_samples=int(payload.get("summary_samples", 256)),
            )
        elif model_type == "linear_gaussian":
            model = SbiNPESurrogateModel(
                weights=np.asarray(payload["weights"], dtype=float),
                bias=float(payload["bias"]),
                sigma=float(payload["sigma"]),
                input_names=list(payload["input_names"]),
                output_name=str(payload["output_name"]),
            )
        else:
            raise ValueError(f"Unsupported payload model_type for sbi_npe: {model_type}")
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
    if backend == "sbi_npe":
        versions["sbi"] = _package_version("sbi")
        versions["torch"] = _package_version("torch")
    return versions
