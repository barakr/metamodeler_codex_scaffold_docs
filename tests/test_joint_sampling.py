"""Sampling the coupled joint — the step the metamodel layer was missing.

`bayesmm meta sample` draws each variable from its prior and then overwrites
coupled targets with `transform(source)`. That is forward propagation: declaring a
Gaussian coupling between two models' variables changes what the targets look like,
but nothing is ever *inferred*, and the source's distribution is untouched by the
coupling. Asking "how do I sample after defining a Gaussian coupling?" had no answer.

The decisive test here is `test_gaussian_link_matches_closed_form`. For normal
priors and a linear-Gaussian coupling the joint is Gaussian with a mean and
covariance available in closed form, so the sampler can be checked against the
right answer rather than against itself. The remaining tests pin the properties a
user would rely on: a coupling must actually constrain (posterior narrower than
prior), and a deterministic coupling must hold exactly in every draw.
"""

from __future__ import annotations

import numpy as np
import pytest

from bayesian_metamodeling.meta.compiler import compile_metamodel
from bayesian_metamodeling.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    VariableIR,
)
from bayesian_metamodeling.meta.joint_sampling import sample_joint


def _two_variable_ir(*, mx, sx, my, sy, alpha, beta, sigma, coupling="gaussian_link"):
    return MetamodelIR(
        name="pair",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(variable="x", distribution={"kind": "normal", "loc": mx, "scale": sx}),
            PriorFactorIR(variable="y", distribution={"kind": "normal", "loc": my, "scale": sy}),
            CouplingFactorIR(
                coupling_type=coupling,
                source="x",
                target="y",
                transform={"kind": "affine", "alpha": alpha, "beta": beta},
                sigma=sigma,
            ),
        ],
    )


def _closed_form(*, mx, sx, my, sy, alpha, beta, sigma):
    """Exact mean/covariance of  N(x|mx,sx) N(y|my,sy) N(y|alpha*x+beta, sigma).

    Collecting the quadratic form in (x, y) gives precision Lambda and linear term h,
    so mean = Lambda^-1 h and cov = Lambda^-1.
    """
    lam = np.array(
        [
            [1.0 / sx**2 + alpha**2 / sigma**2, -alpha / sigma**2],
            [-alpha / sigma**2, 1.0 / sy**2 + 1.0 / sigma**2],
        ]
    )
    h = np.array([mx / sx**2 - alpha * beta / sigma**2, my / sy**2 + beta / sigma**2])
    cov = np.linalg.inv(lam)
    return cov @ h, cov


@pytest.mark.integration
def test_gaussian_link_matches_closed_form():
    """The chain must recover the analytic joint, not merely produce numbers."""
    params = dict(mx=1.0, sx=0.5, my=0.0, sy=2.0, alpha=1.5, beta=-0.4, sigma=0.3)
    ir = _two_variable_ir(**params)
    exact_mean, exact_cov = _closed_form(**params)

    samples, diag = sample_joint(compile_metamodel(ir), draws=8000, tune=2000, chains=2, seed=11)
    x = samples["x"].ravel()
    y = samples["y"].ravel()

    got_mean = np.array([x.mean(), y.mean()])
    got_sd = np.array([x.std(ddof=1), y.std(ddof=1)])
    exact_sd = np.sqrt(np.diag(exact_cov))

    # Loose enough for random-walk Metropolis at this length, tight enough that a
    # sampler targeting the wrong density (e.g. the priors) fails: the prior mean of
    # y is 0.0 against a joint mean near 1.1, and the prior sd is 2.0 against ~0.5.
    assert np.allclose(got_mean, exact_mean, atol=0.08), (
        f"mean {got_mean} != closed form {exact_mean} (accept_rate={diag['accept_rate']:.2f})"
    )
    assert np.allclose(got_sd, exact_sd, rtol=0.12), f"sd {got_sd} != closed form {exact_sd}"

    got_corr = float(np.corrcoef(x, y)[0, 1])
    exact_corr = exact_cov[0, 1] / (exact_sd[0] * exact_sd[1])
    assert abs(got_corr - exact_corr) < 0.06, f"corr {got_corr:.3f} != {exact_corr:.3f}"


@pytest.mark.integration
def test_coupling_actually_constrains_the_source():
    """A coupling must inform BOTH variables — the asymmetry forward propagation has.

    Prior propagation leaves the source exactly at its prior: it only ever rewrites
    the target. Joint sampling tightens the source too, because the coupling is
    evidence about the pair.
    """
    params = dict(mx=0.0, sx=3.0, my=5.0, sy=0.2, alpha=1.0, beta=0.0, sigma=0.2)
    samples, _ = sample_joint(
        compile_metamodel(_two_variable_ir(**params)), draws=6000, tune=1500, chains=2, seed=5
    )
    x = samples["x"].ravel()
    # y is pinned near 5 by a tight prior, and x is tied to y by a tight coupling, so
    # x must move from its own prior N(0, 3) toward 5 and narrow sharply.
    assert x.std(ddof=1) < 0.5 * params["sx"], (
        f"source sd {x.std(ddof=1):.3f} is not tighter than its prior {params['sx']} — "
        "the coupling did not propagate information backwards"
    )
    assert abs(x.mean() - 5.0) < 0.5, f"source mean {x.mean():.3f} was not pulled toward y"


@pytest.mark.integration
def test_deterministic_coupling_holds_exactly_in_every_draw():
    params = dict(mx=2.0, sx=0.7, my=0.0, sy=1.0, alpha=3.0, beta=1.0, sigma=0.1)
    ir = _two_variable_ir(**params, coupling="deterministic_transform")
    samples, diag = sample_joint(compile_metamodel(ir), draws=1500, tune=500, chains=1, seed=3)

    x = samples["x"].ravel()
    y = samples["y"].ravel()
    assert np.allclose(y, params["alpha"] * x + params["beta"], atol=1e-12), (
        "a deterministic coupling must hold exactly; it is computed, not sampled"
    )
    # And it must be reported as derived rather than silently sampled.
    assert diag["derived_variables"] == ["y"], diag


@pytest.mark.integration
def test_reports_a_misspecified_model_instead_of_returning_junk():
    """-inf at the start is a modelling error, and must say so rather than sample on."""
    ir = MetamodelIR(
        name="bad",
        variables=[VariableIR(name="x")],
        factors=[
            PriorFactorIR(variable="x", distribution={"kind": "normal", "loc": 0.0, "scale": 0.0})
        ],
    )
    with pytest.raises((ValueError, ZeroDivisionError, FloatingPointError)):
        sample_joint(compile_metamodel(ir), draws=10, tune=10, chains=1, seed=0)
