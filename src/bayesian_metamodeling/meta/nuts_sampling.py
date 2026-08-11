"""Gradient-based sampling of the coupled joint, for metamodels PyMC can express.

`sample_joint` treats every surrogate as a black box: it calls `log_prob` on a dict of
floats and can therefore only do a gradient-free random walk. That is the right default —
it works for *any* backend — but it is inefficient, and on the geometry that conditioning
creates it can fail to explore at all.

It does not have to be a black box for `pymc_gp`. Despite the name that backend is
Bayesian **linear** regression (see `surrogates/backends.py`), so its predictive density is

    mu[s, d] = x @ W[s, :, d] + bias[s, d]
    log p(y | x) = logsumexp_s( sum_d Normal_logpdf(y[d]; mu[s, d], sigma[s, d]) ) - log S

— an equally weighted mixture over the S posterior draws, and every operation in it is
differentiable. Written as a PyTensor graph it gives NUTS gradients, and with them r-hat,
divergence counts and roughly 6x the effective samples per draw on the conditioning query
that motivated this.

**Scope, deliberately narrow.** This path activates only when every surrogate in the model
is a diagonal `PymcPosteriorLinearModel`. `sbi_npe` is a torch normalizing flow: its
gradients exist but reaching them from PyTensor needs a custom `Op`, which is not written.
Anything this module cannot express falls back to `sample_joint`, which stays the
backend-neutral default and the thing verified against a closed-form Gaussian.

The two paths must agree where both apply. `tests/test_nuts_sampling.py` pins that against
the same closed form, and against `sample_joint` on a shared model.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from bayesian_metamodeling.meta.compiler import CompiledMetaModel
from bayesian_metamodeling.meta.ir import (
    DEFAULT_COUPLING_SIGMA,
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    SurrogateLikelihoodFactorIR,
)
from bayesian_metamodeling.meta.joint_sampling import derived_variables
from bayesian_metamodeling.surrogates.base import SurrogateModel

__all__ = ["nuts_supported", "sample_nuts"]

# Only used when r-hat is unavailable (single chain). Deliberately low: this is a "this
# chain told you nothing" alarm, matching `joint_sampling._MIN_ESS`, not a convergence bar.
_MIN_ESS_SINGLE_CHAIN = 20.0


def _linear_payload(model: Any) -> Any | None:
    """Return the underlying linear posterior model, or None if this is not one.

    Surrogates arrive wrapped (`_ModelWrapper`), so unwrap one level before checking.
    """
    from bayesian_metamodeling.surrogates.backends import PymcPosteriorLinearModel

    inner = getattr(model, "model", model)
    if not isinstance(inner, PymcPosteriorLinearModel):
        return None
    if inner.output_correlation != "diagonal" or inner.posterior_sigma is None:
        # `full` correlation stores a Cholesky factor and needs an MvNormal mixture.
        # Expressible, but not written — say so rather than sample the wrong density.
        return None
    return inner


def nuts_supported(
    ir: MetamodelIR, surrogates: dict[str, SurrogateModel] | None
) -> tuple[bool, str]:
    """Can this model be written as a PyTensor graph? Returns `(ok, reason_if_not)`.

    The reason is user-facing: a refusal that does not say what to do is a dead end, and
    the fallback is silent otherwise.
    """
    try:
        import pymc  # noqa: F401
    except ImportError:
        return False, "PyMC is not installed (pip install -e '.[pymc]')"

    for factor in ir.factors:
        if isinstance(factor, PriorFactorIR):
            kind = factor.distribution.get("kind", "normal")
            if kind != "normal":
                return False, f"prior on {factor.variable!r} is {kind!r}; only 'normal' is built"
        elif isinstance(factor, CouplingFactorIR):
            transform = factor.transform.get("kind", "identity")
            if transform not in {"identity", "affine"}:
                return False, f"coupling transform {transform!r} is not expressible here"
        elif isinstance(factor, SurrogateLikelihoodFactorIR):
            model = (surrogates or {}).get(factor.surrogate_ref)
            if model is None:
                return False, f"surrogate {factor.surrogate_ref!r} is not loaded"
            if _linear_payload(model) is None:
                return False, (
                    f"surrogate {factor.surrogate_ref!r} is not a diagonal pymc_gp "
                    "(linear) model; only those have a symbolic log-density today"
                )
    return True, ""


def _transform_of(factor: CouplingFactorIR) -> tuple[float, float]:
    if factor.transform.get("kind") == "affine":
        return float(factor.transform.get("alpha", 1.0)), float(factor.transform.get("beta", 0.0))
    return 1.0, 0.0


def sample_nuts(
    compiled: CompiledMetaModel,
    *,
    draws: int,
    tune: int,
    chains: int,
    seed: int,
    surrogates: dict[str, SurrogateModel] | None = None,
    target_accept: float = 0.9,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Sample the same joint density as `sample_joint`, with gradients.

    Returns `(samples, diagnostics)` in exactly the shape `sample_joint` returns, so
    callers and stored artifacts do not need to know which sampler ran — only the
    recorded `method` distinguishes them.
    """
    import arviz as az
    import pymc as pm
    import pytensor.tensor as pt

    ir = compiled.ir
    surrogates = surrogates or {}
    ok, reason = nuts_supported(ir, surrogates)
    if not ok:
        raise ValueError(f"this metamodel cannot be sampled with NUTS: {reason}")

    derived = derived_variables(ir)
    observed = {k: float(v) for k, v in (ir.observed or {}).items()}
    names = sorted(var.name for var in ir.variables)
    free = [n for n in names if n not in derived and n not in observed]

    priors: dict[str, tuple[float, float]] = {n: (0.0, 1.0) for n in names}
    for factor in ir.factors:
        if isinstance(factor, PriorFactorIR):
            priors[factor.variable] = (
                float(factor.distribution.get("loc", 0.0)),
                float(factor.distribution.get("scale", 1.0)),
            )

    with pm.Model():
        rv: dict[str, Any] = {}
        for name in free:
            loc, scale = priors[name]
            rv[name] = pm.Normal(name, mu=loc, sigma=scale)
        for name, value in observed.items():
            rv[name] = pt.constant(value, dtype="float64")

        # Deterministic targets are computed, never sampled — same rule as the
        # random-walk path. Loop until nothing new resolves so a chain of links
        # (a -> b -> c) settles regardless of factor order.
        remaining = dict(derived)
        for _ in range(len(remaining) + 1):
            if not remaining:
                break
            progressed = False
            for target, factor in list(remaining.items()):
                if factor.source not in rv:
                    continue
                alpha, beta = _transform_of(factor)
                rv[target] = pm.Deterministic(target, alpha * rv[factor.source] + beta)
                del remaining[target]
                progressed = True
            if not progressed:
                break
        if remaining:
            raise ValueError(
                f"deterministic couplings could not be ordered: {sorted(remaining)} "
                "(is there a cycle, or a source that is neither sampled nor observed?)"
            )

        missing = [n for n in names if n not in rv]
        if missing:
            raise ValueError(f"variables never defined in the PyMC model: {missing}")

        for i, factor in enumerate(ir.factors):
            if isinstance(factor, CouplingFactorIR):
                if factor.coupling_type == "deterministic_transform":
                    continue  # already enforced exactly, by construction
                alpha, beta = _transform_of(factor)
                sigma = float(factor.sigma or DEFAULT_COUPLING_SIGMA)
                residual = rv[factor.target] - (alpha * rv[factor.source] + beta)
                pm.Potential(
                    f"coupling_{i}",
                    -0.5 * (pt.log(2 * np.pi * sigma**2) + (residual**2) / sigma**2),
                )
            elif isinstance(factor, SurrogateLikelihoodFactorIR):
                inner = _linear_payload(surrogates[factor.surrogate_ref])
                # (S, F, D), (S, D), (S, D) — the surrogate's own parameter posterior,
                # carried into the metamodel rather than collapsed to a point estimate.
                weights = np.asarray(inner.posterior_weights, dtype=float)
                bias = np.asarray(inner.posterior_bias, dtype=float)
                sigma = np.clip(np.asarray(inner.posterior_sigma, dtype=float), 1e-8, None)
                n_draws = weights.shape[0]

                x = pt.stack([rv[name] for name in factor.inputs])  # (F,)
                y = pt.stack([rv[name] for name in factor.outputs])  # (D,)
                # mu[s, d] = sum_f x[f] * W[s, f, d] + bias[s, d]
                mu = pt.tensordot(x, pt.constant(weights), axes=[[0], [1]]) + pt.constant(bias)
                var = pt.constant(sigma**2)
                per_dim = -0.5 * (pt.log(2 * np.pi * var) + ((y[None, :] - mu) ** 2) / var)
                pm.Potential(
                    f"surrogate_{i}",
                    pt.logsumexp(per_dim.sum(axis=1)) - np.log(n_draws),
                )

        idata = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            random_seed=seed,
            target_accept=target_accept,
            progressbar=False,
            compute_convergence_checks=False,
        )

    posterior = idata.posterior
    out: dict[str, np.ndarray] = {}
    for name in names:
        if name in observed:
            out[name] = np.full((chains, draws), observed[name], dtype=float)
        else:
            out[name] = np.asarray(posterior[name].values, dtype=float)

    ess = {n: float(az.ess(idata, var_names=[n]).to_array().values.ravel()[0]) for n in free}
    diverging = int(np.asarray(idata.sample_stats["diverging"].values).sum())

    # r-hat compares chains, so it is undefined for one chain — arviz returns NaN.
    # Reporting that NaN would be worse than reporting nothing: `nan > 1.01` is False, so
    # a single-chain run would silently pass every mixing check and look impeccable. When
    # r-hat is unavailable, fall back to the same ESS floor the random-walk path uses.
    rhat: dict[str, float] | None = None
    if chains >= 2:
        rhat = {n: float(az.rhat(idata, var_names=[n]).to_array().values.ravel()[0]) for n in free}

    if rhat is not None:
        poorly_mixed = sorted(n for n, v in rhat.items() if not np.isfinite(v) or v > 1.01)
    else:
        poorly_mixed = sorted(n for n, v in ess.items() if v < _MIN_ESS_SINGLE_CHAIN)

    diagnostics = {
        "method": "nuts",
        # Kept for interface parity with `sample_joint`; NUTS reports its own acceptance.
        "accept_rate": float(np.asarray(idata.sample_stats["acceptance_rate"].values).mean())
        if "acceptance_rate" in idata.sample_stats
        else float("nan"),
        "free_variables": free,
        "derived_variables": sorted(derived),
        "surrogates_loaded": sorted(surrogates),
        "observed": dict(observed),
        "ess": ess,
        # None with a single chain, where r-hat is undefined rather than good.
        "r_hat": rhat,
        "divergences": diverging,
        "poorly_mixed": poorly_mixed,
    }
    return out, diagnostics
