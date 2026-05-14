"""Surrogate backend implementations behind a neutral interface.

Multi-output design
-------------------
All posterior models store outputs as ``(N, D)`` where ``D = len(output_names)``.
Single-output is the special case ``D == 1``. ``backend_config["output_correlation"]``
selects between ``"diagonal"`` (independent outputs, default — fast) and
``"full"`` (joint covariance — captures cross-output correlation).

Payload schema is versioned: new artifacts use ``..._v2`` model_types; old v1
artifacts (single-output) are still loadable as ``D == 1``.
"""

from __future__ import annotations

import base64
import importlib.metadata
import io
import json
import os
import threading
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np
from scipy.special import logsumexp
from scipy.stats import multivariate_normal

from bayesian_metamodeling.surrogate_config import validate_backend_config
from bayesian_metamodeling.surrogates import SurrogateModel


@dataclass
class LinearGaussianModel:
    """Single-output linear+Gaussian fallback (legacy v1 payloads). D=1 only.

    Kept on the original 2-D ``(N, n)`` sample contract; the multi-output
    posterior models below use the ``(N, n, D)`` contract.
    """

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
    """Multi-output Bayesian linear posterior.

    Shapes (D = number of outputs, F = number of input features, S = posterior draws):
        posterior_weights: (S, F, D)
        posterior_bias:    (S, D)
        posterior_sigma:   (S, D)        — when output_correlation == "diagonal"
        posterior_chol:    (S, D, D)     — when output_correlation == "full"
    """

    posterior_weights: np.ndarray
    posterior_bias: np.ndarray
    input_names: list[str]
    output_names: list[str]
    output_correlation: str = "diagonal"
    posterior_sigma: np.ndarray | None = None
    posterior_chol: np.ndarray | None = None

    @property
    def n_outputs(self) -> int:
        return len(self.output_names)

    def _x(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        return np.column_stack(
            [np.asarray(inputs[name], dtype=float).reshape(-1) for name in self.input_names]
        )

    def _predictive_mu(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        """Return shape (N, S, D) — predictive mean per row, per posterior draw, per output."""
        x = self._x(inputs)  # (N, F)
        mu = np.einsum("nf,sfd->nsd", x, self.posterior_weights) + self.posterior_bias[None, :, :]
        return mu

    def sample(self, inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray:
        """Posterior-predictive samples.

        Shape ``(N, n)`` for single-output (D=1), ``(N, n, D)`` for multi-output.
        """
        mu = self._predictive_mu(inputs)  # (N, S, D)
        n_rows, n_draws, d = mu.shape
        rng = np.random.default_rng(seed)
        out = np.empty((n_rows, n, d), dtype=float)

        draw_idx = rng.integers(0, n_draws, size=(n_rows, n))
        if self.output_correlation == "full":
            chol = self.posterior_chol  # (S, D, D)
            assert chol is not None
            z = rng.normal(size=(n_rows, n, d))
            for r in range(n_rows):
                for k in range(n):
                    s = draw_idx[r, k]
                    out[r, k] = mu[r, s] + chol[s] @ z[r, k]
        else:
            sigma = self.posterior_sigma  # (S, D)
            assert sigma is not None
            for r in range(n_rows):
                for k in range(n):
                    s = draw_idx[r, k]
                    out[r, k] = rng.normal(loc=mu[r, s], scale=sigma[s])
        return out[:, :, 0] if d == 1 else out

    def log_prob(self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray:
        """Per-row joint log probability of observed outputs under the posterior predictive.

        Returns shape (N,). The per-row value is the joint log-prob across all output
        dimensions (sum over D for diagonal; full MvNormal for full), averaged over
        posterior draws via logsumexp.
        """
        mu = self._predictive_mu(inputs)  # (N, S, D)
        n_rows, n_draws, d = mu.shape
        y = np.column_stack(
            [np.asarray(outputs[name], dtype=float).reshape(-1) for name in self.output_names]
        )  # (N, D)
        if y.shape != (n_rows, d):
            raise ValueError(
                f"Output array shape {y.shape} does not match expected ({n_rows}, {d})."
            )

        if self.output_correlation == "full":
            chol = self.posterior_chol  # (S, D, D)
            assert chol is not None
            covs = np.einsum("sij,skj->sik", chol, chol)  # (S, D, D)
            logp_per_draw = np.empty((n_rows, n_draws), dtype=float)
            for s in range(n_draws):
                rv = multivariate_normal(mean=np.zeros(d), cov=covs[s], allow_singular=True)
                logp_per_draw[:, s] = rv.logpdf(y - mu[:, s, :])
        else:
            sigma = self.posterior_sigma  # (S, D)
            assert sigma is not None
            sigma_clip = np.clip(sigma, a_min=1e-8, a_max=None)
            var = sigma_clip[None, :, :] ** 2  # (1, S, D)
            diff = y[:, None, :] - mu  # (N, S, D)
            per_dim = -0.5 * (np.log(2 * np.pi * var) + (diff**2) / var)  # (N, S, D)
            logp_per_draw = per_dim.sum(axis=2)  # (N, S)

        return logsumexp(logp_per_draw, axis=1) - np.log(n_draws)

    def summary(self, inputs: dict[str, np.ndarray]) -> dict:
        mu = self._predictive_mu(inputs)  # (N, S, D)
        point_mean = mu.mean(axis=1)  # (N, D)

        if self.output_correlation == "full":
            chol = self.posterior_chol
            assert chol is not None
            covs = np.einsum("sij,skj->sik", chol, chol)  # (S, D, D)
            mean_diag_var = np.mean(np.diagonal(covs, axis1=1, axis2=2), axis=0)  # (D,)
            predictive_std = np.sqrt(np.var(mu, axis=1) + mean_diag_var[None, :])
        else:
            sigma = self.posterior_sigma
            assert sigma is not None
            mean_var = np.mean(sigma**2, axis=0)  # (D,)
            predictive_std = np.sqrt(np.var(mu, axis=1) + mean_var[None, :])

        return {
            "mean": {name: point_mean[:, i].tolist() for i, name in enumerate(self.output_names)},
            "std": {
                name: predictive_std[:, i].tolist() for i, name in enumerate(self.output_names)
            },
            "posterior_draws": int(mu.shape[1]),
            "n": int(point_mean.shape[0]),
            "output_correlation": self.output_correlation,
        }


class SbiNPEPosteriorModel:
    """Multi-output SBI NPE posterior.

    For ``output_correlation == "full"``, ``posteriors`` holds a single D-dim
    posterior; ``.sample((n,), x=obs)`` returns shape ``(n, D)``.
    For ``output_correlation == "diagonal"``, ``posteriors`` holds D 1-D posteriors.

    The constructor accepts both the multi-output kwargs (``posteriors``,
    ``output_names``, array ``y_mean``/``y_scale``) and the legacy single-output
    kwargs (``posterior``, ``output_name``, scalar ``y_mean``/``y_scale``) so that
    older call sites keep working. ``.sample()`` returns ``(N, n)`` for D=1 and
    ``(N, n, D)`` for multi-output.
    """

    def __init__(
        self,
        *,
        input_names: list[str],
        x_mean: np.ndarray,
        x_scale: np.ndarray,
        y_mean: Any,
        y_scale: Any,
        posteriors: list[Any] | None = None,
        posterior: Any | None = None,
        output_names: list[str] | None = None,
        output_name: str | None = None,
        output_correlation: str = "full",
        summary_samples: int = 256,
    ) -> None:
        if posteriors is None:
            if posterior is None:
                raise ValueError("Provide either posteriors=[...] or posterior=...")
            posteriors = [posterior]
        if output_names is None:
            if output_name is None:
                raise ValueError("Provide either output_names=[...] or output_name=...")
            output_names = [output_name]

        self.posteriors = posteriors
        self.input_names = input_names
        self.output_names = output_names
        self.x_mean = np.asarray(x_mean, dtype=float)
        self.x_scale = np.asarray(x_scale, dtype=float)
        self.y_mean = np.atleast_1d(np.asarray(y_mean, dtype=float))
        self.y_scale = np.atleast_1d(np.asarray(y_scale, dtype=float))
        self.output_correlation = output_correlation
        self.summary_samples = summary_samples

    @property
    def n_outputs(self) -> int:
        return len(self.output_names)

    @property
    def posterior(self) -> Any:
        """Legacy single-posterior accessor (first entry of ``posteriors``)."""
        return self.posteriors[0]

    def _normalized_x(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        x_raw = np.column_stack(
            [np.asarray(inputs[name], dtype=float).reshape(-1) for name in self.input_names]
        )
        return (x_raw - self.x_mean[None, :]) / self.x_scale[None, :]

    def _denormalize(self, y_norm: np.ndarray) -> np.ndarray:
        return y_norm * self.y_scale[None, :] + self.y_mean[None, :]

    def _normalize(self, y: np.ndarray) -> np.ndarray:
        return (y - self.y_mean[None, :]) / self.y_scale[None, :]

    def sample(self, inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray:
        torch = _require_torch()
        x_norm = self._normalized_x(inputs)
        n_rows = len(x_norm)
        d = self.n_outputs
        out = np.empty((n_rows, n, d), dtype=float)

        for idx, row in enumerate(x_norm):
            torch.manual_seed(seed + idx)
            obs = torch.as_tensor(row, dtype=torch.float32)
            if self.output_correlation == "full":
                posterior = self.posteriors[0]
                sampled = posterior.sample((n,), x=obs)
                sample_np = np.asarray(sampled.detach().cpu().numpy(), dtype=float).reshape(n, d)
                out[idx] = self._denormalize(sample_np)
            else:
                cols = []
                for j, posterior in enumerate(self.posteriors):
                    torch.manual_seed(seed + idx * d + j)
                    sampled = posterior.sample((n,), x=obs)
                    cols.append(
                        np.asarray(sampled.detach().cpu().numpy(), dtype=float).reshape(n, -1)[:, 0]
                    )
                out[idx] = self._denormalize(np.column_stack(cols))
        return out[:, :, 0] if d == 1 else out

    def log_prob(self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray:
        torch = _require_torch()
        x_norm = self._normalized_x(inputs)
        y = np.column_stack(
            [np.asarray(outputs[name], dtype=float).reshape(-1) for name in self.output_names]
        )
        if len(y) != len(x_norm):
            raise ValueError("Output length must match number of input rows for log_prob")
        y_norm = self._normalize(y).astype(np.float32)

        # Affine correction: log p(y) = log p_norm(y_norm) - sum log y_scale_d
        affine_correction = -float(np.sum(np.log(self.y_scale)))

        logp: list[float] = []
        for idx, row in enumerate(x_norm):
            obs = torch.as_tensor(row, dtype=torch.float32)
            if self.output_correlation == "full":
                posterior = self.posteriors[0]
                # Reshape to (1, D) via numpy so torch.as_tensor gets one array,
                # not a list of arrays (which is slow and warns under -W error).
                theta = torch.as_tensor(y_norm[idx][None, :], dtype=torch.float32)
                value = posterior.log_prob(theta, x=obs)
                scalar = float(np.asarray(value.detach().cpu().numpy(), dtype=float).reshape(-1)[0])
                logp.append(scalar + affine_correction)
            else:
                running = affine_correction
                for j, posterior in enumerate(self.posteriors):
                    theta = torch.as_tensor([y_norm[idx, j]], dtype=torch.float32)
                    value = posterior.log_prob(theta, x=obs)
                    running += float(
                        np.asarray(value.detach().cpu().numpy(), dtype=float).reshape(-1)[0]
                    )
                logp.append(running)
        return np.asarray(logp, dtype=float)

    def summary(self, inputs: dict[str, np.ndarray]) -> dict:
        draws = self.sample(inputs=inputs, n=self.summary_samples, seed=0)
        if draws.ndim == 2:  # single-output squeeze form
            draws = draws[:, :, None]
        return {
            "mean": {
                name: draws[:, :, i].mean(axis=1).tolist()
                for i, name in enumerate(self.output_names)
            },
            "std": {
                name: draws[:, :, i].std(axis=1).tolist()
                for i, name in enumerate(self.output_names)
            },
            "posterior_draws": int(self.summary_samples),
            "n": int(draws.shape[0]),
            "output_correlation": self.output_correlation,
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

_ENV_LOCK = threading.Lock()


@contextmanager
def _optional_backend_import_context() -> Iterator[None]:
    cache_root = (Path("tmp") / ".cache").resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    home_root = (Path("tmp") / "home").resolve()
    home_root.mkdir(parents=True, exist_ok=True)
    mplconfig_root = (Path("tmp") / "matplotlib").resolve()
    mplconfig_root.mkdir(parents=True, exist_ok=True)

    with _ENV_LOCK:
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
            "or use `pip install 'bayesian-metamodeling[pymc]'`."
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
            "or use `pip install 'bayesian-metamodeling[sbi]'`."
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
            "or use `pip install 'bayesian-metamodeling[sbi]'`."
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


def _ensure_2d(y: np.ndarray) -> np.ndarray:
    """Promote a 1-D y vector to (N, 1) — single-output back-compat for callers."""
    if y.ndim == 1:
        return y.reshape(-1, 1)
    return y


def _resolve_output_names(output_names: list[str] | None, output_name: str | None) -> list[str]:
    """Accept either the multi-output ``output_names`` or legacy ``output_name``."""
    if output_names is not None:
        return output_names
    if output_name is not None:
        return [output_name]
    raise ValueError("Must pass either output_names=[...] or output_name=...")


def _fit_pymc_bayesian_linear(
    *,
    x: np.ndarray,
    y: np.ndarray,
    input_names: list[str],
    output_names: list[str] | None = None,
    output_name: str | None = None,
    backend_config: dict[str, Any],
    seed: int,
) -> PymcPosteriorLinearModel:
    pm = _require_pymc()
    output_names = _resolve_output_names(output_names, output_name)
    y = _ensure_2d(y)
    n_features = x.shape[1]
    d = y.shape[1]
    if d != len(output_names):
        raise ValueError(f"y has {d} columns but output_names has {len(output_names)} entries.")

    draws = int(backend_config.get("draws", 300))
    tune = int(backend_config.get("tune", 300))
    chains = int(backend_config.get("chains", 1))
    target_accept = float(backend_config.get("target_accept", 0.9))
    output_correlation = str(backend_config.get("output_correlation", "diagonal"))

    with pm.Model():
        beta = pm.Normal("beta", mu=0.0, sigma=2.0, shape=(n_features, d))
        intercept = pm.Normal("intercept", mu=0.0, sigma=2.0, shape=(d,))
        mu = intercept[None, :] + pm.math.dot(x, beta)  # (N, D)

        if output_correlation == "full" and d >= 2:
            chol, _, _ = pm.LKJCholeskyCov(
                "chol_cov",
                n=d,
                eta=2.0,
                sd_dist=pm.HalfNormal.dist(1.0),
                compute_corr=True,
            )
            # Register the cholesky factor as a deterministic so we can extract it
            # from idata.posterior regardless of PyMC version-specific naming.
            pm.Deterministic("chol_factor", chol)
            pm.MvNormal("obs", mu=mu, chol=chol, observed=y)
        else:
            sigma = pm.HalfNormal("sigma", sigma=1.0, shape=(d,))
            pm.Normal("obs", mu=mu, sigma=sigma[None, :], observed=y)

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

    posterior_weights = np.asarray(idata.posterior["beta"], dtype=float).reshape(-1, n_features, d)
    posterior_bias = np.asarray(idata.posterior["intercept"], dtype=float).reshape(-1, d)

    if output_correlation == "full" and d >= 2:
        chol_factor = np.asarray(idata.posterior["chol_factor"], dtype=float)
        # Shape: (chains, draws, D, D); flatten the chain/draw axes.
        chol_full = chol_factor.reshape(-1, d, d)
        return PymcPosteriorLinearModel(
            posterior_weights=posterior_weights,
            posterior_bias=posterior_bias,
            posterior_chol=chol_full,
            input_names=input_names,
            output_names=output_names,
            output_correlation="full",
        )

    posterior_sigma = np.asarray(idata.posterior["sigma"], dtype=float).reshape(-1, d)
    posterior_sigma = np.clip(posterior_sigma, a_min=1e-8, a_max=None)
    return PymcPosteriorLinearModel(
        posterior_weights=posterior_weights,
        posterior_bias=posterior_bias,
        posterior_sigma=posterior_sigma,
        input_names=input_names,
        output_names=output_names,
        output_correlation="diagonal",
    )


def _fit_sbi_npe(
    *,
    x: np.ndarray,
    y: np.ndarray,
    input_names: list[str],
    output_names: list[str] | None = None,
    output_name: str | None = None,
    backend_config: dict[str, Any],
    seed: int,
) -> SbiNPEPosteriorModel:
    torch = _require_torch()
    _require_sbi()
    output_names = _resolve_output_names(output_names, output_name)
    y = _ensure_2d(y)
    d = y.shape[1]
    if d != len(output_names):
        raise ValueError(f"y has {d} columns but output_names has {len(output_names)} entries.")

    output_correlation = str(backend_config.get("output_correlation", "diagonal"))
    if d == 1:
        # Single output: both modes degenerate to a single 1-D estimator.
        output_correlation = "full"

    x_mean = np.mean(x, axis=0)
    x_scale = np.std(x, axis=0)
    x_scale = np.where(x_scale < 1e-8, 1.0, x_scale)

    y_mean = np.mean(y, axis=0)
    y_scale = np.std(y, axis=0)
    y_scale = np.where(y_scale < 1e-8, 1.0, y_scale)

    x_norm = ((x - x_mean[None, :]) / x_scale[None, :]).astype(np.float32)
    y_norm = ((y - y_mean[None, :]) / y_scale[None, :]).astype(np.float32)

    torch.manual_seed(seed)
    observations = torch.as_tensor(x_norm, dtype=torch.float32)
    density_estimator_name = str(backend_config.get("density_estimator", "maf"))

    posteriors: list[Any] = []
    if output_correlation == "full":
        theta = torch.as_tensor(y_norm, dtype=torch.float32)
        inference = _build_sbi_inference(density_estimator=density_estimator_name)
        density_estimator = _train_sbi_density_estimator(
            inference=inference, theta=theta, x=observations, backend_config=backend_config
        )
        posteriors.append(inference.build_posterior(density_estimator))
    else:
        for j in range(d):
            theta_j = torch.as_tensor(y_norm[:, j : j + 1], dtype=torch.float32)
            inference_j = _build_sbi_inference(density_estimator=density_estimator_name)
            density_estimator_j = _train_sbi_density_estimator(
                inference=inference_j,
                theta=theta_j,
                x=observations,
                backend_config=backend_config,
            )
            posteriors.append(inference_j.build_posterior(density_estimator_j))

    return SbiNPEPosteriorModel(
        posteriors=posteriors,
        input_names=input_names,
        output_names=output_names,
        x_mean=np.asarray(x_mean, dtype=float),
        x_scale=np.asarray(x_scale, dtype=float),
        y_mean=np.asarray(y_mean, dtype=float),
        y_scale=np.asarray(y_scale, dtype=float),
        output_correlation=output_correlation,
        summary_samples=int(backend_config.get("summary_samples", 256)),
    )


def fit_backend_model(
    *,
    backend: str,
    x: np.ndarray,
    y: np.ndarray,
    input_names: list[str],
    output_names: list[str] | None = None,
    output_name: str | None = None,
    backend_config: dict[str, Any] | None = None,
    seed: int = 0,
):
    """Dispatch to the right backend.

    Accepts either ``output_names`` (preferred, multi-output) or ``output_name``
    (legacy, single-output) for backwards compatibility with older call sites.
    """
    if output_names is None:
        if output_name is None:
            raise ValueError("Must pass either output_names=[...] or output_name=...")
        output_names = [output_name]

    config = validate_backend_config(backend, backend_config or {})
    if backend == "pymc_gp":
        return _fit_pymc_bayesian_linear(
            x=x,
            y=y,
            input_names=input_names,
            output_names=output_names,
            backend_config=config,
            seed=seed,
        )
    if backend == "sbi_npe":
        return _fit_sbi_npe(
            x=x,
            y=y,
            input_names=input_names,
            output_names=output_names,
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
    # Security: weights_only=False is required because SBI posteriors are full Python
    # objects (not just tensors). We validate the loaded object conforms to the expected
    # posterior interface to guard against loading arbitrary objects from tampered artifacts.
    try:
        obj = torch.load(buffer, map_location="cpu", weights_only=False)
    except TypeError:
        obj = torch.load(buffer, map_location="cpu")
    if not hasattr(obj, "sample") or not hasattr(obj, "log_prob"):
        raise ValueError(
            "Deserialized torch object does not implement the expected posterior interface "
            "(sample, log_prob). Artifact may be corrupted or tampered with."
        )
    return obj


def save_backend_payload(model: SurrogateModel, payload_path: Path) -> None:
    if isinstance(model, PymcPosteriorLinearModel):
        payload: dict[str, Any] = {
            "model_type": "pymc_bayesian_linear_v2",
            "schema_version": 2,
            "posterior_weights": model.posterior_weights.tolist(),
            "posterior_bias": model.posterior_bias.tolist(),
            "input_names": model.input_names,
            "output_names": model.output_names,
            "output_correlation": model.output_correlation,
        }
        if model.output_correlation == "full":
            assert model.posterior_chol is not None
            payload["posterior_chol"] = model.posterior_chol.tolist()
        else:
            assert model.posterior_sigma is not None
            payload["posterior_sigma"] = model.posterior_sigma.tolist()
    elif isinstance(model, SbiNPEPosteriorModel):
        payload = {
            "model_type": "sbi_npe_posterior_v2",
            "schema_version": 2,
            "serialization": "torch_save_base64",
            "posterior_blobs_b64": [_serialize_torch_object(p) for p in model.posteriors],
            "input_names": model.input_names,
            "output_names": model.output_names,
            "output_correlation": model.output_correlation,
            "x_mean": model.x_mean.tolist(),
            "x_scale": model.x_scale.tolist(),
            "y_mean": model.y_mean.tolist(),
            "y_scale": model.y_scale.tolist(),
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


def _load_pymc_v1_as_v2(payload: dict) -> PymcPosteriorLinearModel:
    """Read an old single-output v1 PyMC payload as a D=1 v2 model."""
    posterior_weights = np.asarray(payload["posterior_weights"], dtype=float)
    if posterior_weights.ndim == 2:
        posterior_weights = posterior_weights[:, :, None]
    posterior_bias = np.asarray(payload["posterior_bias"], dtype=float).reshape(-1, 1)
    posterior_sigma = np.asarray(payload["posterior_sigma"], dtype=float).reshape(-1, 1)
    return PymcPosteriorLinearModel(
        posterior_weights=posterior_weights,
        posterior_bias=posterior_bias,
        posterior_sigma=posterior_sigma,
        input_names=list(payload["input_names"]),
        output_names=[str(payload["output_name"])],
        output_correlation="diagonal",
    )


def _load_sbi_v1_as_v2(payload: dict) -> SbiNPEPosteriorModel:
    """Read an old single-output v1 SBI payload as a D=1 v2 model."""
    posterior = _deserialize_torch_object(payload["posterior_blob_b64"])
    return SbiNPEPosteriorModel(
        posteriors=[posterior],
        input_names=list(payload["input_names"]),
        output_names=[str(payload["output_name"])],
        x_mean=np.asarray(payload["x_mean"], dtype=float),
        x_scale=np.asarray(payload["x_scale"], dtype=float),
        y_mean=np.asarray([float(payload["y_mean"])], dtype=float),
        y_scale=np.asarray([float(payload["y_scale"])], dtype=float),
        output_correlation="full",
        summary_samples=int(payload.get("summary_samples", 256)),
    )


def load_backend_model(
    backend: str,
    payload_path: Path,
    *,
    expected_inputs: list[str] | None = None,
    expected_output: str | None = None,
    expected_outputs: list[str] | None = None,
) -> SurrogateModel:
    payload = json.loads(payload_path.read_text())
    model_type = payload.get("model_type", "linear_gaussian")
    payload_inputs = list(payload.get("input_names", []))
    payload_outputs = (
        list(payload.get("output_names", []))
        if "output_names" in payload
        else [str(payload.get("output_name", ""))]
    )

    if expected_inputs is not None and payload_inputs != expected_inputs:
        raise ValueError(
            "Surrogate payload input order mismatch: "
            f"artifact has {payload_inputs}, spec expects {expected_inputs}."
        )
    expected_list = expected_outputs
    if expected_list is None and expected_output is not None:
        expected_list = [expected_output]
    if expected_list is not None and payload_outputs != expected_list:
        raise ValueError(
            "Surrogate payload output mismatch: "
            f"artifact has {payload_outputs}, spec expects {expected_list}."
        )

    if backend == "pymc_gp":
        if model_type == "pymc_bayesian_linear_v2":
            kwargs = dict(
                posterior_weights=np.asarray(payload["posterior_weights"], dtype=float),
                posterior_bias=np.asarray(payload["posterior_bias"], dtype=float),
                input_names=list(payload["input_names"]),
                output_names=list(payload["output_names"]),
                output_correlation=str(payload.get("output_correlation", "diagonal")),
            )
            if "posterior_chol" in payload:
                kwargs["posterior_chol"] = np.asarray(payload["posterior_chol"], dtype=float)
            if "posterior_sigma" in payload:
                kwargs["posterior_sigma"] = np.asarray(payload["posterior_sigma"], dtype=float)
            model = PymcPosteriorLinearModel(**kwargs)
        elif model_type == "pymc_bayesian_linear":
            model = _load_pymc_v1_as_v2(payload)
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
        if model_type == "sbi_npe_posterior_v2":
            _require_sbi()
            posteriors = [
                _deserialize_torch_object(blob) for blob in payload["posterior_blobs_b64"]
            ]
            model = SbiNPEPosteriorModel(
                posteriors=posteriors,
                input_names=list(payload["input_names"]),
                output_names=list(payload["output_names"]),
                x_mean=np.asarray(payload["x_mean"], dtype=float),
                x_scale=np.asarray(payload["x_scale"], dtype=float),
                y_mean=np.asarray(payload["y_mean"], dtype=float),
                y_scale=np.asarray(payload["y_scale"], dtype=float),
                output_correlation=str(payload.get("output_correlation", "full")),
                summary_samples=int(payload.get("summary_samples", 256)),
            )
        elif model_type == "sbi_npe_posterior":
            _require_sbi()
            model = _load_sbi_v1_as_v2(payload)
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
