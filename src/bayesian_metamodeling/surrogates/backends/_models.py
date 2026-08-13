"""Surrogate model classes — the objects a fitted backend hands back.

Split out of the former single-file `backends.py` (D2). These are pure numpy/scipy: they
hold fitted parameters and implement the `SurrogateModel` contract (`sample`, `log_prob`,
`summary`). Nothing here imports pymc, sbi or torch, which is why it separates cleanly —
see the package docstring for what could *not* be separated, and why.

`pymc_gp` is Bayesian linear regression rather than a Gaussian process, and
`PymcPosteriorLinearModel` is where you can read that off the code directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.special import logsumexp
from scipy.stats import multivariate_normal

from bayesian_metamodeling.surrogates import SurrogateModel
from bayesian_metamodeling.surrogates.backends._helpers import _named_or_squeezed


def _runtime():
    """Resolve the runtime helpers through the package, at call time.

    `SbiNPEPosteriorModel` needs `_require_torch` and `_sbi_warnings_filtered`, which live in
    the package's runtime module. Importing them at module scope with `from ... import` would
    copy the reference — and the test suite monkeypatches `backends._require_torch` twelve
    times over. A copied reference means the patch silently stops applying and the test passes
    for the wrong reason, which is the exact defect class this package was reviewed for.

    Looking the names up on the package at call time keeps patching working. The import is
    inside the function on purpose: at module-import time the package is still initialising.
    """
    from bayesian_metamodeling.surrogates import backends

    return backends


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
        Fully vectorized — no per-row/per-sample Python loop.
        """
        mu = self._predictive_mu(inputs)  # (N, S, D)
        n_rows, n_draws, d = mu.shape
        rng = np.random.default_rng(seed)

        draw_idx = rng.integers(0, n_draws, size=(n_rows, n))  # (N, n)
        selected_mu = np.take_along_axis(mu, draw_idx[:, :, None], axis=1)  # (N, n, D)

        if self.output_correlation == "full":
            if self.posterior_chol is None:
                raise ValueError("output_correlation='full' requires posterior_chol")
            selected_chol = self.posterior_chol[draw_idx]  # (N, n, D, D)
            z = rng.normal(size=(n_rows, n, d))  # (N, n, D)
            # out = mu + chol @ z, batched over (N, n).
            out = selected_mu + np.einsum("nkij,nkj->nki", selected_chol, z)
        else:
            if self.posterior_sigma is None:
                raise ValueError("output_correlation='diagonal' requires posterior_sigma")
            selected_sigma = self.posterior_sigma[draw_idx]  # (N, n, D)
            out = rng.normal(loc=selected_mu, scale=selected_sigma)

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
            if chol is None:
                raise ValueError("output_correlation='full' requires posterior_chol")
            covs = np.einsum("sij,skj->sik", chol, chol)  # (S, D, D)
            logp_per_draw = np.empty((n_rows, n_draws), dtype=float)
            for s in range(n_draws):
                rv = multivariate_normal(mean=np.zeros(d), cov=covs[s], allow_singular=True)
                logp_per_draw[:, s] = rv.logpdf(y - mu[:, s, :])
        else:
            sigma = self.posterior_sigma  # (S, D)
            if sigma is None:
                raise ValueError("output_correlation='diagonal' requires posterior_sigma")
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
            if chol is None:
                raise ValueError("output_correlation='full' requires posterior_chol")
            covs = np.einsum("sij,skj->sik", chol, chol)  # (S, D, D)
            mean_diag_var = np.mean(np.diagonal(covs, axis1=1, axis2=2), axis=0)  # (D,)
            predictive_std = np.sqrt(np.var(mu, axis=1) + mean_diag_var[None, :])
        else:
            sigma = self.posterior_sigma
            if sigma is None:
                raise ValueError("output_correlation='diagonal' requires posterior_sigma")
            mean_var = np.mean(sigma**2, axis=0)  # (D,)
            predictive_std = np.sqrt(np.var(mu, axis=1) + mean_var[None, :])

        return {
            "mean": _named_or_squeezed(point_mean, self.output_names),
            "std": _named_or_squeezed(predictive_std, self.output_names),
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
        density_estimator: str = "maf",
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
        # Recorded so the artifact can be rebuilt from weights alone rather than pickled.
        # `posterior_nn(model=<this>)` plus the state dict and the two dimensions is the
        # whole recipe — see `_rebuild_sbi_posterior`.
        self.density_estimator = density_estimator

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
        torch = _runtime()._require_torch()
        x_norm = self._normalized_x(inputs)
        n_rows = len(x_norm)
        d = self.n_outputs
        out = np.empty((n_rows, n, d), dtype=float)

        # sbi posterior `.sample()` may surface the same advisory warnings as
        # training (1D output, prior support inference); suppress them here too
        # so eval doesn't fail under `filterwarnings = error`.
        with _runtime()._sbi_warnings_filtered():
            for idx, row in enumerate(x_norm):
                torch.manual_seed(seed + idx)
                obs = torch.as_tensor(row, dtype=torch.float32)
                if self.output_correlation == "full":
                    posterior = self.posteriors[0]
                    sampled = posterior.sample((n,), x=obs)
                    sample_np = np.asarray(sampled.detach().cpu().numpy(), dtype=float).reshape(
                        n, d
                    )
                    out[idx] = self._denormalize(sample_np)
                else:
                    cols = []
                    for j, posterior in enumerate(self.posteriors):
                        torch.manual_seed(seed + idx * d + j)
                        sampled = posterior.sample((n,), x=obs)
                        cols.append(
                            np.asarray(sampled.detach().cpu().numpy(), dtype=float).reshape(n, -1)[
                                :, 0
                            ]
                        )
                    out[idx] = self._denormalize(np.column_stack(cols))
        return out[:, :, 0] if d == 1 else out

    def log_prob(self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray:
        torch = _runtime()._require_torch()
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
        # Same suppression as `sample`: sbi posterior `.log_prob()` can emit
        # the prior-support advisory in 0.26+.
        with _runtime()._sbi_warnings_filtered():
            for idx, row in enumerate(x_norm):
                obs = torch.as_tensor(row, dtype=torch.float32)
                if self.output_correlation == "full":
                    posterior = self.posteriors[0]
                    # Reshape to (1, D) via numpy so torch.as_tensor gets one array,
                    # not a list of arrays (which is slow and warns under -W error).
                    theta = torch.as_tensor(y_norm[idx][None, :], dtype=torch.float32)
                    value = posterior.log_prob(theta, x=obs)
                    scalar = float(
                        np.asarray(value.detach().cpu().numpy(), dtype=float).reshape(-1)[0]
                    )
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
        mean_2d = draws.mean(axis=1)  # (N, D)
        std_2d = draws.std(axis=1)  # (N, D)
        return {
            "mean": _named_or_squeezed(mean_2d, self.output_names),
            "std": _named_or_squeezed(std_2d, self.output_names),
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
