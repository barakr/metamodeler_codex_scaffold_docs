"""Surrogate backend implementations behind a neutral interface.

`pymc_gp` is NOT a Gaussian process
-----------------------------------
The name is historical and it misleads. ``_fit_pymc_bayesian_linear`` builds

    beta      ~ Normal(0, 2)          # (n_features, D)
    intercept ~ Normal(0, 2)          # (D,)
    mu        = intercept + x @ beta

i.e. **Bayesian linear regression**. There is no kernel, no covariance function and
no ``pm.gp`` anywhere in this package.

This matters because GP intuition is exactly wrong here. A GP reverts toward its
prior mean away from the training data, with predictive width growing as you leave
it. This model does the opposite — trained on ``a, b in [0, 2]`` predicting ``a + b``
it returns:

    (1, 1)       -> mean 2.000    sd 0.00000
    (5, 5)       -> mean 10.000   sd 0.00000
    (20, 20)     -> mean 40.000   sd 0.00000
    (100, 100)   -> mean 200.000  sd 0.00000

Perfect confident extrapolation, fifty times outside the training box. That is the
right answer for a genuinely linear function, and it is a trap for anything else: on
a nonlinear system this surrogate will be confidently wrong with near-zero error
bars, which is more dangerous than a GP that widens and warns you. Judge fit quality
from held-out error, never from the predictive width alone.

Renaming the backend would break every existing spec (`SurrogateSpec.backend` is a
``Literal``) and every stored artifact, so the name stays and the docs carry the
correction. `numpyro_gp` is likewise a name, not a promise.

Multi-output design
-------------------
All posterior models store outputs as ``(N, D)`` where ``D = len(output_names)``.
Single-output is the special case ``D == 1``. ``backend_config["output_correlation"]``
selects between ``"diagonal"`` (independent outputs, default — fast) and
``"full"`` (joint covariance — captures cross-output correlation).

Payload schema is versioned and every older version stays loadable:

- ``pymc_gp`` writes ``pymc_bayesian_linear_v2``; v1 (single-output) loads as ``D == 1``.
- ``sbi_npe`` writes ``sbi_npe_posterior_v3``, which stores the density estimator's
  ``state_dict`` (tensors only) plus the recipe to rebuild the architecture, and loads with
  ``weights_only=True``. Nothing in such a file can execute.
- ``sbi_npe_posterior_v2`` is the **legacy pickled** format. It still loads so that work
  fitted before the change does not break, but it warns that the artifact is executable, and
  ``MM_STRICT_ARTIFACTS=1`` turns that into an error — which is how CI proves this repository
  never depends on the unsafe path.

Why this module is still large (D2)
-----------------------------------
The model classes and the small shape/name helpers now live in ``_models.py`` and
``_helpers.py``. What remains is one entangled cluster, and the entanglement is worth
recording rather than fighting.

Nine names here are monkeypatched by the test suite: the three
``_require_pymc``/``_require_torch``/``_require_sbi`` guards, the sbi version shims, both fit
functions, and the serialisers. Python's ``from x import f`` copies a reference, so a caller
living in a *different* module keeps its own binding and a patch applied to this module
silently stops taking effect — the test then passes for the wrong reason, which is exactly the
defect class this package was reviewed for.

A patched name and its callers therefore have to share a module. That ties the guards to the
fit functions, the fit functions to the shims, and the serialisers to the save/load dispatch —
which is everything left here. Splitting further means replacing module-level patching with
dependency injection in the tests: a genuine improvement, and a separate piece of work.
"""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from bayesian_metamodeling.surrogate_config import validate_backend_config
from bayesian_metamodeling.surrogates import SurrogateModel
from bayesian_metamodeling.surrogates.backends._helpers import (  # noqa: F401  (re-export)
    _ensure_2d,
    _named_or_squeezed,
    _package_version,
    _resolve_output_names,
    get_backend_dependency_versions,
)
from bayesian_metamodeling.surrogates.backends._models import (  # noqa: F401  (re-export)
    LinearGaussianModel,
    PymcGPSurrogateModel,
    PymcPosteriorLinearModel,
    SbiNPEPosteriorModel,
    SbiNPESurrogateModel,
    _ModelWrapper,
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


class _TrackerCompatWriter:
    """Adapter so a `tensorboard.SummaryWriter` works as an sbi 0.26+ tracker.

    sbi 0.26 changed the training-logger interface: instead of calling
    `summary_writer.add_scalar(name, value, step)` it now calls
    `tracker.log_metric(name, value, step=...)`. The tensorboard
    `SummaryWriter` does not expose `log_metric`, so the new sbi internals
    crash with `AttributeError` even when constructed with the new `tracker`
    kwarg. This wrapper translates `log_metric(...)` -> `add_scalar(...)`
    and forwards everything else (including `add_scalar` itself, `close`,
    `flush`, etc.) to the inner writer untouched, so the same writer object
    works under both sbi <0.26 and sbi >=0.26.

    The pre-existing `_NoOpSummaryWriter` is already 0.26-safe via its
    blanket `__getattr__` no-op; this wrapper is only needed for the real
    tensorboard writer.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def log_metric(self, name: str, value: Any, step: int | None = None) -> None:
        self._inner.add_scalar(name, value, step or 0)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@contextmanager
def _sbi_warnings_filtered() -> Iterator[None]:
    """Suppress `UserWarning`s sbi raises for valid-but-noisy usage patterns.

    sbi's training/inference loop emits advisory warnings for several patterns
    we use deliberately (1D output, posterior-only training without an
    explicit prior). Under `pytest.ini`'s `filterwarnings = error`, those
    warnings would otherwise elevate to test failures. These filters cover
    sbi 0.22..0.26+ — when sbi <0.26 doesn't emit a given message the filter
    is a no-op.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="In one-dimensional output space, this flow is limited to Gaussians",
            category=UserWarning,
        )
        # sbi 0.26+: when `prior=None` (posterior-only training), sbi
        # auto-derives the support from the simulated `theta` and warns
        # about the missing `.support` attribute.
        warnings.filterwarnings(
            "ignore",
            message="The passed prior has no support property",
            category=UserWarning,
        )
        yield


def _make_sbi_summary_writer() -> Any:
    log_root = Path("tmp") / "sbi-logs"
    log_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat().replace(":", "_")
    log_dir = log_root / f"npe_{timestamp}"
    try:
        from torch.utils.tensorboard import SummaryWriter  # type: ignore[import-not-found]

        # Wrap so the writer satisfies BOTH the legacy `add_scalar` interface
        # (sbi <0.26) and the new `log_metric` interface (sbi >=0.26). See
        # `_TrackerCompatWriter` for the rationale.
        return _TrackerCompatWriter(SummaryWriter(log_dir=str(log_dir)))
    except Exception:
        # Keep runtime robust even when tensorboard writer extras are unavailable.
        # `_NoOpSummaryWriter`'s blanket `__getattr__` already covers both
        # `add_scalar` and `log_metric`, so no wrapping is needed.
        return _NoOpSummaryWriter(log_dir=str(log_dir))


def _build_sbi_inference(density_estimator: str):
    _require_sbi()
    writer = _make_sbi_summary_writer()
    with _optional_backend_import_context():
        try:
            from sbi.inference import NPE as _Inference  # type: ignore[import-not-found]

            base_kwargs: dict[str, Any] = {"density_estimator": density_estimator}
        except ImportError:
            from sbi.inference import SNPE as _Inference  # type: ignore[import-not-found]

            base_kwargs = {"prior": None, "density_estimator": density_estimator}

        # sbi renamed the training-logger kwarg `summary_writer` -> `tracker` in
        # 0.26. Try the new name first, then the legacy name, then construct
        # without a logger at all — so the code works across sbi 0.22..0.26+.
        for log_kwarg in ("tracker", "summary_writer", None):
            kwargs = dict(base_kwargs)
            if log_kwarg is not None:
                kwargs[log_kwarg] = writer
            try:
                return _Inference(**kwargs)
            except TypeError:
                continue
        return _Inference(**base_kwargs)


def _train_sbi_density_estimator(
    inference: Any, theta: Any, x: Any, backend_config: dict[str, Any]
) -> Any:
    train_kwargs = {
        "max_num_epochs": int(backend_config.get("max_num_epochs", 120)),
        "training_batch_size": int(backend_config.get("training_batch_size", 32)),
        "learning_rate": float(backend_config.get("learning_rate", 5e-4)),
        "validation_fraction": float(backend_config.get("validation_fraction", 0.1)),
        "stop_after_epochs": int(backend_config.get("stop_after_epochs", 20)),
        "show_train_summary": bool(backend_config.get("show_train_summary", False)),
    }

    # `_sbi_warnings_filtered()` covers BOTH the legacy 1D-flow advisory AND
    # the sbi 0.26+ "no prior support" advisory. `append_simulations` is
    # inside the block because sbi 0.26 does its prior processing there.
    with _sbi_warnings_filtered():
        trainer = inference.append_simulations(theta, x)
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
    output_names: list[str] | None = None,
    output_name: str | None = None,
    backend_config: dict[str, Any],
    seed: int,
) -> PymcPosteriorLinearModel:
    """Fit Bayesian linear regression with PyMC — this is what `pymc_gp` actually is.

    Despite the backend name there is no Gaussian process here: the mean is linear in
    the inputs and the posterior is over ``beta``/``intercept``/``sigma``. See this
    module's docstring for why the distinction changes how you should read the
    predictive width.
    """
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

    # `inference.build_posterior(...)` triggers sbi 0.26's prior-support
    # advisory (the prior is auto-derived from the trained density estimator
    # when no explicit prior was passed). Wrap with the same suppressor used
    # in `_train_sbi_density_estimator` so both call sites are consistent.
    posteriors: list[Any] = []
    with _sbi_warnings_filtered():
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
        density_estimator=density_estimator_name,
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


STRICT_ARTIFACTS_ENV_VAR = "MM_STRICT_ARTIFACTS"


class LegacyPickleArtifactWarning(UserWarning):
    """A surrogate artifact is in the pre-v3 pickled format.

    Loading it executes code from the file. Kept loadable so that work fitted before the
    format changed does not simply break — but never silently, and `MM_STRICT_ARTIFACTS=1`
    turns this into an error so CI can prove the repository itself never depends on it.
    """


def _strict_artifacts() -> bool:
    return os.environ.get(STRICT_ARTIFACTS_ENV_VAR, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


#: Schemas that predate the multi-output ``_v2`` payloads. Still loadable — deleting them
#: would break artifacts fitted before the change, which is the same reason the legacy sbi
#: pickle stayed loadable — but no longer silent.
LEGACY_SCHEMA_MODEL_TYPES = {
    "linear_gaussian": "the original single-output linear+Gaussian payload",
    "pymc_bayesian_linear": "the pre-v2 single-output pymc_gp payload",
    "sbi_npe_posterior": "the pre-v2 single-output sbi_npe payload",
}


class LegacyArtifactSchemaWarning(UserWarning):
    """A surrogate artifact uses a schema older than the current one.

    Not a security matter (unlike `LegacyPickleArtifactWarning`) — these payloads are plain
    numbers. It is a *maintenance* matter: every old schema is a branch that has to keep
    working, and one nobody can retire while its use is invisible. Warning makes the
    population visible; `MM_STRICT_ARTIFACTS=1` makes it an error, which is how CI proves the
    repository itself no longer depends on any of them.
    """


def _warn_if_legacy_schema(model_type: str, payload_path: Path) -> None:
    description = LEGACY_SCHEMA_MODEL_TYPES.get(model_type)
    if description is None:
        return
    message = (
        f"Surrogate artifact at {payload_path} uses the legacy schema '{model_type}' "
        f"({description}). It still loads, and the numbers are unchanged. Re-run "
        f"`bayesmm surrogate fit` to rewrite it in the current schema; set "
        f"{STRICT_ARTIFACTS_ENV_VAR}=1 to make this an error instead of a warning."
    )
    if _strict_artifacts():
        raise ValueError(f"Refusing to load a legacy-schema surrogate artifact. {message}")
    warnings.warn(message, LegacyArtifactSchemaWarning, stacklevel=3)


def _serialize_state_dict(state_dict: Any) -> str:
    """Base64 a tensor-only `state_dict`. Contains no code, by construction."""
    torch = _require_torch()
    buffer = io.BytesIO()
    torch.save(state_dict, buffer)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _deserialize_state_dict(serialized: str) -> Any:
    """Load a tensor-only `state_dict` with unpickling **disabled**.

    `weights_only=True` is the whole point of the v3 format: `torch.load` refuses anything
    that is not a plain tensor container, so a tampered artifact cannot execute code on the
    way in. Contrast `_deserialize_torch_object` below, which is the legacy path.
    """
    torch = _require_torch()
    buffer = io.BytesIO(base64.b64decode(serialized.encode("ascii")))
    return torch.load(buffer, map_location="cpu", weights_only=True)


def _rebuild_sbi_posterior(
    *, state_dict: Any, density_estimator: str, theta_dim: int, x_dim: int
) -> Any:
    """Reconstruct a `DirectPosterior` from weights, with no pickled objects involved.

    The recipe is: ask sbi for the same architecture (`posterior_nn(model=...)` is a
    *builder* that infers layer shapes from example batches), load the saved weights into
    it, and wrap it in a posterior.

    **On the prior.** `_fit_sbi_npe` passes none, so sbi derives an `ImproperEmpirical` one
    from the training targets. Measured on sbi 0.26.1: that prior's `log_prob` is `0.0`
    everywhere — it is improper and flat — and neither `log_prob` nor `sample` changes when
    it is rebuilt from *wildly different* moments. Only its dimension matters, and a
    degenerate (zero-variance) placeholder is rejected by sbi's transform check. So a fixed
    non-degenerate placeholder of the right width reproduces the original exactly, and no
    training data has to be carried in the artifact to achieve it.
    """
    torch = _require_torch()
    _require_sbi()
    from sbi.inference.posteriors import DirectPosterior
    from sbi.neural_nets import posterior_nn
    from sbi.utils.sbiutils import ImproperEmpirical

    # Deterministic, non-degenerate example batches. Only their *shapes* select the
    # architecture; every learned value, including the z-scoring buffers, is overwritten by
    # `load_state_dict` below.
    rows = 16
    example_theta = torch.linspace(-1.0, 1.0, rows * theta_dim).reshape(rows, theta_dim)
    example_x = torch.linspace(-1.0, 1.0, rows * x_dim).reshape(rows, x_dim)

    with _sbi_warnings_filtered():
        estimator = posterior_nn(model=density_estimator)(example_theta, example_x)
        estimator.load_state_dict(state_dict)
        estimator.eval()
        placeholder_prior = ImproperEmpirical(example_theta)
        return DirectPosterior(posterior_estimator=estimator, prior=placeholder_prior)


def _deserialize_torch_object(serialized: str) -> Any:
    """Load a pickled SBI posterior. **This executes code from the artifact.**

    `weights_only=False` means pickle, and pickle runs code *during* deserialisation —
    inside the `torch.load` call below, before any check here can look at the result.
    The `hasattr` test that follows is therefore a **corruption check, not a security
    control**: it catches a truncated or wrong-type payload, and cannot catch a
    malicious one, because by the time it runs the payload has already had its way.

    An earlier version of this function claimed the opposite ("guard against loading
    arbitrary objects from tampered artifacts"), which was worse than saying nothing —
    it invited exactly the behaviour it could not defend.

    **So: only load `sbi_npe` artifacts you fitted yourself.** No artifact tracked in
    this repository takes this path (all are `pymc_gp`, which serialises as plain JSON
    numbers). Replacing this with a `state_dict` + `weights_only=True` load is item S1a
    in REVIEW_AND_UPGRADE_PLAN.md.
    """
    torch = _require_torch()

    message = (
        "This surrogate artifact uses the legacy pickled format (`sbi_npe_v2`). Loading it "
        "runs code contained in the file, so only load artifacts you fitted yourself. "
        "Re-run `bayesmm surrogate fit` to rewrite it in the v3 format, which stores weights "
        f"only and loads with unpickling disabled. Set {STRICT_ARTIFACTS_ENV_VAR}=1 to make "
        "this an error instead of a warning."
    )
    if _strict_artifacts():
        raise ValueError(
            f"Refusing to load a legacy pickled surrogate artifact "
            f"({STRICT_ARTIFACTS_ENV_VAR}=1). {message}"
        )
    warnings.warn(message, LegacyPickleArtifactWarning, stacklevel=3)

    buffer = io.BytesIO(base64.b64decode(serialized.encode("ascii")))
    try:
        obj = torch.load(buffer, map_location="cpu", weights_only=False)
    except TypeError:
        obj = torch.load(buffer, map_location="cpu")
    if not hasattr(obj, "sample") or not hasattr(obj, "log_prob"):
        raise ValueError(
            "Deserialized torch object does not implement the expected posterior interface "
            "(sample, log_prob). Artifact is corrupted or is not an sbi posterior."
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
            "model_type": "sbi_npe_posterior_v3",
            "schema_version": 2,
            "serialization": "state_dict_base64",
            "density_estimator": model.density_estimator,
            "theta_dim": len(model.output_names) if model.output_correlation == "full" else 1,
            "x_dim": len(model.input_names),
            "state_dicts_b64": [
                _serialize_state_dict(p.posterior_estimator.state_dict()) for p in model.posteriors
            ],
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
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if "model_type" not in payload:
        # A payload with no `model_type` used to become a v1 `linear_gaussian` silently.
        # That is a guess, not a default: it is equally likely to be a truncated file. Say so.
        warnings.warn(
            f"Surrogate payload at {payload_path} declares no `model_type`; assuming the "
            "pre-v2 'linear_gaussian' schema. If this artifact is truncated or was written by "
            "something else, that guess is wrong. Re-run `bayesmm surrogate fit` to rewrite it "
            "with an explicit schema.",
            LegacyArtifactSchemaWarning,
            stacklevel=2,
        )
    model_type = payload.get("model_type", "linear_gaussian")
    _warn_if_legacy_schema(model_type, payload_path)
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
        if model_type == "sbi_npe_posterior_v3":
            # Weights only. `_deserialize_state_dict` loads with unpickling disabled, and
            # the posterior is rebuilt from the recorded architecture — no object in this
            # artifact can execute anything.
            _require_sbi()
            density_estimator = str(payload.get("density_estimator", "maf"))
            theta_dim = int(payload["theta_dim"])
            x_dim = int(payload["x_dim"])
            posteriors = [
                _rebuild_sbi_posterior(
                    state_dict=_deserialize_state_dict(blob),
                    density_estimator=density_estimator,
                    theta_dim=theta_dim,
                    x_dim=x_dim,
                )
                for blob in payload["state_dicts_b64"]
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
                density_estimator=density_estimator,
            )
        elif model_type == "sbi_npe_posterior_v2":
            # Legacy pickled format. Still loadable so pre-v3 work does not break, but
            # `_deserialize_torch_object` warns loudly and refuses under MM_STRICT_ARTIFACTS.
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
