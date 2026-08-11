"""Conditioning: `observed` clamps a variable so the rest can be inferred from it.

Before this, the metamodel layer could only draw the *whole* joint. There was nowhere in
`MetaModelSpec` or the IR to say "I measured this one", so the question people actually
bring to a metamodel — *given what I measured, what does that imply about everything
else?* — was not expressible. The only workaround was to fake an observation with a very
tight prior, which is both undocumented and actively bad: it concentrates the posterior on
a thin ridge, and a coordinate-wise random walk cannot follow a ridge.

The decisive test here is `test_conditioning_recovers_the_closed_form_posterior`. For
normal priors and a linear-Gaussian coupling, clamping one variable leaves a posterior
that is available on paper, so the sampler is checked against the right answer rather than
against itself.
"""

from __future__ import annotations

import numpy as np
import pytest

from bayesian_metamodeling.meta.builder import build_ir_from_metamodel_spec
from bayesian_metamodeling.meta.compiler import compile_metamodel
from bayesian_metamodeling.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    VariableIR,
)
from bayesian_metamodeling.meta.joint_sampling import sample_joint
from bayesian_metamodeling.spec import MetaModelSpec


def _pair_ir(*, mx, sx, my, sy, alpha, beta, sigma, observed=None):
    return MetamodelIR(
        name="conditioned_pair",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(variable="x", distribution={"kind": "normal", "loc": mx, "scale": sx}),
            PriorFactorIR(variable="y", distribution={"kind": "normal", "loc": my, "scale": sy}),
            CouplingFactorIR(
                coupling_type="gaussian_link",
                source="x",
                target="y",
                transform={"kind": "affine", "alpha": alpha, "beta": beta},
                sigma=sigma,
            ),
        ],
        observed=observed or {},
    )


@pytest.mark.integration
def test_conditioning_recovers_the_closed_form_posterior():
    """Observe y; the posterior over x is Gaussian and known exactly."""
    mx, sx, alpha, beta, sigma = 1.0, 0.6, 1.5, -0.4, 0.3
    y_obs = 3.0

    # p(x | y) ∝ Normal(x; mx, sx) · Normal(y; alpha*x + beta, sigma).
    # Collecting the quadratic form in x:
    prec = 1.0 / sx**2 + alpha**2 / sigma**2
    mean = (mx / sx**2 + alpha * (y_obs - beta) / sigma**2) / prec
    sd = 1.0 / np.sqrt(prec)

    ir = _pair_ir(
        mx=mx, sx=sx, my=0.0, sy=5.0, alpha=alpha, beta=beta, sigma=sigma, observed={"y": y_obs}
    )
    samples, diag = sample_joint(compile_metamodel(ir), draws=8000, tune=2000, chains=2, seed=3)

    x = samples["x"].ravel()
    assert abs(x.mean() - mean) < 0.05, (
        f"conditioned mean {x.mean():.4f} != closed form {mean:.4f} "
        f"(accept_rate={diag['accept_rate']:.2f})"
    )
    assert abs(x.std(ddof=1) - sd) < 0.05 * sd, (
        f"conditioned sd {x.std(ddof=1):.4f} != closed form {sd:.4f}"
    )
    # The observed variable is not sampled: it is held exactly where it was measured.
    assert np.all(samples["y"] == y_obs)
    assert diag["observed"] == {"y": y_obs}
    assert "y" not in diag["free_variables"]


@pytest.mark.integration
def test_conditioning_is_not_the_same_as_the_unconditioned_joint():
    """Guard against `observed` being silently ignored.

    If the clamp were dropped, this would still run and still produce plausible numbers —
    which is exactly the failure mode worth a test.
    """
    params = dict(mx=1.0, sx=0.6, my=0.0, sy=5.0, alpha=1.5, beta=-0.4, sigma=0.3)
    free, _ = sample_joint(
        compile_metamodel(_pair_ir(**params)), draws=6000, tune=1500, chains=2, seed=3
    )
    cond, _ = sample_joint(
        compile_metamodel(_pair_ir(**params, observed={"y": 3.0})),
        draws=6000,
        tune=1500,
        chains=2,
        seed=3,
    )
    assert abs(free["x"].mean() - cond["x"].mean()) > 0.15, (
        "conditioning on y did not move x at all; `observed` is being ignored"
    )
    assert cond["x"].std() < free["x"].std(), (
        "conditioning should tighten x, not leave it at its unconditioned spread"
    )


@pytest.mark.contract
def test_observing_a_deterministic_target_is_refused():
    """A deterministic target is computed from its source; observing it is a contradiction.

    Silently letting one win would hand back healthy-looking draws for a model that cannot
    be satisfied, so the builder refuses and says which variable and what to do instead.
    """
    spec = MetaModelSpec.model_validate(
        {
            "schema_version": "1.0",
            "name": "bad_observation",
            "ppl_backend": "pymc",
            "surrogate_refs": ["examples/coupled/artifacts/surrogate_A.artifact.json"],
            "variables": [{"name": "x"}, {"name": "y"}],
            "couplings": [
                {
                    "kind": "deterministic",
                    "source": "x",
                    "target": "y",
                    "transform": {"kind": "affine", "alpha": 2.0, "beta": 0.0},
                }
            ],
            "priors": [
                {"variable": "x", "distribution": {"kind": "normal", "loc": 0.0, "scale": 1.0}}
            ],
            "observed": {"y": 4.0},
        }
    )
    with pytest.raises(ValueError, match="deterministic coupling"):
        build_ir_from_metamodel_spec(spec)


@pytest.mark.contract
def test_specs_without_observed_still_load():
    """`observed` is additive: every spec and stored IR written before it must still work."""
    spec = MetaModelSpec.model_validate(
        {
            "schema_version": "1.0",
            "name": "no_observations",
            "ppl_backend": "pymc",
            "surrogate_refs": ["examples/coupled/artifacts/surrogate_A.artifact.json"],
            "variables": [{"name": "x"}, {"name": "y"}],
            "couplings": [],
            "priors": [
                {"variable": "x", "distribution": {"kind": "normal", "loc": 0.0, "scale": 1.0}}
            ],
        }
    )
    assert spec.observed == {}
    ir = build_ir_from_metamodel_spec(spec)
    assert ir.observed == {}
    # And an IR JSON payload predating the field must round-trip.
    from bayesian_metamodeling.meta.ir import ir_from_json_dict, ir_to_json_dict

    payload = ir_to_json_dict(ir)
    payload.pop("observed", None)
    assert ir_from_json_dict(payload).observed == {}
