"""The gradient path must sample the SAME density as the random walk, only better.

`sample_nuts` exists because `pymc_gp` is Bayesian linear regression, so its predictive
density — a mixture of Gaussians over the surrogate's posterior draws — can be written as
a PyTensor graph instead of being called as a black box. That buys gradients, and with
them r-hat, divergence counts, and on the TCR metamodel a worst-case effective sample size
of 58% against 0.7%.

The risk it introduces is subtle and is what these tests are for: a second implementation
of the same model can *drift*. If the PyTensor graph and `evaluate_log_prob` ever encode
different densities, both samplers keep running and both keep producing plausible numbers.
So the graph is checked against a closed-form answer, and against the sampler it is meant
to replace, on the same model.
"""

from __future__ import annotations

import numpy as np
import pytest

from bayesian_metamodeling.meta.compiler import compile_metamodel
from bayesian_metamodeling.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    SurrogateLikelihoodFactorIR,
    VariableIR,
)
from bayesian_metamodeling.meta.joint_sampling import sample_joint
from bayesian_metamodeling.meta.nuts_sampling import nuts_supported, sample_nuts
from tests.backend_support import _has_pymc, _has_sbi, is_pymc_runtime_constraint

pytestmark = [pytest.mark.optional_backend, pytest.mark.slow]

PARAMS = dict(mx=1.0, sx=0.5, my=0.0, sy=2.0, alpha=1.5, beta=-0.4, sigma=0.3)


def _pair_ir(observed=None, **p):
    return MetamodelIR(
        name="pair",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(
                variable="x", distribution={"kind": "normal", "loc": p["mx"], "scale": p["sx"]}
            ),
            PriorFactorIR(
                variable="y", distribution={"kind": "normal", "loc": p["my"], "scale": p["sy"]}
            ),
            CouplingFactorIR(
                coupling_type="gaussian_link",
                source="x",
                target="y",
                transform={"kind": "affine", "alpha": p["alpha"], "beta": p["beta"]},
                sigma=p["sigma"],
            ),
        ],
        observed=observed or {},
    )


def _closed_form(*, mx, sx, my, sy, alpha, beta, sigma):
    lam = np.array(
        [
            [1.0 / sx**2 + alpha**2 / sigma**2, -alpha / sigma**2],
            [-alpha / sigma**2, 1.0 / sy**2 + 1.0 / sigma**2],
        ]
    )
    h = np.array([mx / sx**2 - alpha * beta / sigma**2, my / sy**2 + beta / sigma**2])
    cov = np.linalg.inv(lam)
    return cov @ h, np.sqrt(np.diag(cov))


def _skip_without_pymc():
    if not _has_pymc():
        pytest.skip("needs pymc")


def test_nuts_recovers_the_closed_form_joint():
    _skip_without_pymc()
    exact_mean, exact_sd = _closed_form(**PARAMS)
    try:
        samples, diag = sample_nuts(
            compile_metamodel(_pair_ir(**PARAMS)), draws=3000, tune=1000, chains=2, seed=11
        )
    except Exception as exc:  # noqa: BLE001
        if is_pymc_runtime_constraint(exc):
            pytest.skip(f"pymc toolchain constraint, not a regression: {exc}")
        raise

    got_mean = np.array([samples["x"].mean(), samples["y"].mean()])
    got_sd = np.array([samples["x"].std(ddof=1), samples["y"].std(ddof=1)])
    assert np.allclose(got_mean, exact_mean, atol=0.05), f"{got_mean} != {exact_mean}"
    assert np.allclose(got_sd, exact_sd, rtol=0.05), f"{got_sd} != {exact_sd}"
    assert diag["method"] == "nuts"
    assert diag["divergences"] == 0
    assert max(diag["r_hat"].values()) < 1.05, diag["r_hat"]


def test_nuts_and_the_random_walk_agree_on_the_same_model():
    """The guard against two implementations of one density drifting apart."""
    _skip_without_pymc()
    try:
        nuts, _ = sample_nuts(
            compile_metamodel(_pair_ir(**PARAMS)), draws=3000, tune=1000, chains=2, seed=11
        )
    except Exception as exc:  # noqa: BLE001
        if is_pymc_runtime_constraint(exc):
            pytest.skip(f"pymc toolchain constraint: {exc}")
        raise
    rw, _ = sample_joint(
        compile_metamodel(_pair_ir(**PARAMS)), draws=9000, tune=2500, chains=2, seed=11
    )
    for name in ("x", "y"):
        assert abs(nuts[name].mean() - rw[name].mean()) < 0.06, (
            f"{name}: nuts mean {nuts[name].mean():.4f} vs random walk {rw[name].mean():.4f} — "
            "the two paths no longer encode the same density"
        )
        assert abs(nuts[name].std() - rw[name].std()) < 0.08 * rw[name].std(), (
            f"{name}: nuts sd {nuts[name].std():.4f} vs random walk {rw[name].std():.4f}"
        )


def test_nuts_honours_conditioning():
    _skip_without_pymc()
    mx, sx, alpha, beta, sigma = PARAMS["mx"], PARAMS["sx"], 1.5, -0.4, 0.3
    y_obs = 3.0
    prec = 1.0 / sx**2 + alpha**2 / sigma**2
    mean = (mx / sx**2 + alpha * (y_obs - beta) / sigma**2) / prec
    sd = 1.0 / np.sqrt(prec)
    try:
        samples, diag = sample_nuts(
            compile_metamodel(_pair_ir(observed={"y": y_obs}, **PARAMS)),
            draws=3000,
            tune=1000,
            chains=2,
            seed=3,
        )
    except Exception as exc:  # noqa: BLE001
        if is_pymc_runtime_constraint(exc):
            pytest.skip(f"pymc toolchain constraint: {exc}")
        raise
    assert np.all(samples["y"] == y_obs), "observed variable was sampled instead of clamped"
    assert abs(samples["x"].mean() - mean) < 0.05, f"{samples['x'].mean():.4f} != {mean:.4f}"
    assert abs(samples["x"].std(ddof=1) - sd) < 0.05 * sd
    assert diag["observed"] == {"y": y_obs}
    assert "y" not in diag["free_variables"]


def test_single_chain_reports_no_rhat_rather_than_a_nan_that_passes():
    """A NaN r-hat would silently satisfy every mixing check.

    `nan > 1.01` is False, so a one-chain run would look impeccable by a check written the
    obvious way. r-hat is undefined for a single chain, so it is reported as None and the
    ESS floor takes over.
    """
    _skip_without_pymc()
    try:
        _, diag = sample_nuts(
            compile_metamodel(_pair_ir(**PARAMS)), draws=800, tune=400, chains=1, seed=2
        )
    except Exception as exc:  # noqa: BLE001
        if is_pymc_runtime_constraint(exc):
            pytest.skip(f"pymc toolchain constraint: {exc}")
        raise
    assert diag["r_hat"] is None, "r-hat is undefined for one chain and must not be reported"
    assert all(np.isfinite(v) for v in diag["ess"].values())


def test_refuses_models_it_cannot_express_and_says_why():
    """The fallback must be explained, or a performance flag silently becomes a lie."""
    _skip_without_pymc()
    ir = MetamodelIR(
        name="npe",
        variables=[VariableIR(name="a"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(variable="a", distribution={"kind": "normal", "loc": 0.0, "scale": 1.0}),
            PriorFactorIR(variable="y", distribution={"kind": "normal", "loc": 0.0, "scale": 1.0}),
            SurrogateLikelihoodFactorIR(surrogate_ref="opaque", inputs=["a"], outputs=["y"]),
        ],
    )

    class _Opaque:
        def log_prob(self, inputs, outputs):  # pragma: no cover - never called
            raise NotImplementedError

    ok, reason = nuts_supported(ir, {"opaque": _Opaque()})
    assert not ok
    assert "pymc_gp" in reason, reason
    with pytest.raises(ValueError, match="cannot be sampled with NUTS"):
        sample_nuts(
            compile_metamodel(ir),
            draws=10,
            tune=10,
            chains=1,
            seed=0,
            surrogates={"opaque": _Opaque()},
        )


def test_an_sbi_surrogate_falls_back_rather_than_being_mis_sampled():
    """Real backend check: an NPE flow has no symbolic log-density here."""
    if not _has_sbi():
        pytest.skip("needs sbi")
    from bayesian_metamodeling.surrogates.backends import fit_backend_model

    rng = np.random.default_rng(0)
    a = rng.uniform(-2, 2, 120)
    x = a.reshape(-1, 1)
    y = (1.7 * a + 0.2 + rng.normal(0, 0.05, 120)).reshape(-1, 1)
    model = fit_backend_model(
        backend="sbi_npe",
        x=x,
        y=y,
        input_names=["a"],
        output_names=["y"],
        backend_config={
            "density_estimator": "maf",
            "max_num_epochs": 60,
            "training_batch_size": 32,
            "summary_samples": 64,
        },
        seed=0,
    )
    ir = MetamodelIR(
        name="npe",
        variables=[VariableIR(name="a"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(variable="a", distribution={"kind": "normal", "loc": 0.0, "scale": 1.0}),
            PriorFactorIR(variable="y", distribution={"kind": "normal", "loc": 0.0, "scale": 1.0}),
            SurrogateLikelihoodFactorIR(surrogate_ref="npe", inputs=["a"], outputs=["y"]),
        ],
    )
    ok, reason = nuts_supported(ir, {"npe": model})
    # The refusal itself is the contract, and it holds in every environment.
    assert not ok, "an sbi_npe flow must not be claimed as NUTS-expressible"
    # The *reason* legitimately differs by environment, and asserting only the
    # surrogate-specific wording made this fail in CI's sbi-only job: `nuts_supported`
    # checks for PyMC first and returns "PyMC is not installed" before ever inspecting
    # the surrogate. Both are correct refusals; which one you get depends on the env.
    if _has_pymc():
        assert "pymc_gp" in reason, reason
    else:
        assert "PyMC is not installed" in reason, reason
