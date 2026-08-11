"""A joint chain that never moved must say so, not report a summary.

Found while wiring a real fitted surrogate into a metamodel for the tutorials. A
`pymc_gp` fit of an exactly-linear truth has predictive sd ~1e-5, so its likelihood is
nearly a delta function. Conditioning on it puts the posterior on a thin ridge, tuning
shrinks every proposal scale to ~1e-6 to keep accepting, and the chain then explores a
~3e-5 sliver of a distribution whose real width is O(1).

The damning part: `accept_rate` was **0.29**. By the only diagnostic the sampler
reported, that run looked fine. `a`, `b` and `y` came back with standard deviations of
0.000 and would have been read as "conditioning pinned them precisely" when in fact the
sampler had gone nowhere. That is the silent-no-op shape rule 12 exists for, so mixing is
now reported per variable and the CLI warns.

Both directions matter, so both are tested: the pathological model must be flagged, and a
well-behaved one must NOT be — a warning that fires on healthy runs would be trained away
within a week.
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


class _RazorSharpSurrogate:
    """Asserts y == a + b to within `sd`, with `sd` absurdly small.

    Stands in for a linear-regression surrogate fitted to a noiseless linear truth,
    which is exactly what `pymc_gp` produces on the tutorials' toy model.
    """

    def __init__(self, sd: float = 1e-5) -> None:
        self.sd = sd

    def log_prob(self, inputs, outputs):
        a = np.asarray(inputs["a"], dtype=float).reshape(-1)
        b = np.asarray(inputs["b"], dtype=float).reshape(-1)
        y = np.asarray(outputs["y"], dtype=float).reshape(-1)
        residual = y - (a + b)
        return -0.5 * (residual / self.sd) ** 2 - np.log(self.sd)

    def sample(self, inputs, n, seed):  # pragma: no cover - unused here
        raise NotImplementedError

    def summary(self, inputs):  # pragma: no cover - unused here
        raise NotImplementedError


def _ridge_ir() -> MetamodelIR:
    return MetamodelIR(
        name="ridge",
        variables=[VariableIR(name=n) for n in ("a", "b", "y")],
        factors=[
            PriorFactorIR(variable="a", distribution={"kind": "normal", "loc": 1.0, "scale": 0.6}),
            PriorFactorIR(variable="b", distribution={"kind": "normal", "loc": 1.0, "scale": 0.6}),
            PriorFactorIR(variable="y", distribution={"kind": "normal", "loc": 0.0, "scale": 3.0}),
            SurrogateLikelihoodFactorIR(surrogate_ref="s", inputs=["a", "b"], outputs=["y"]),
        ],
    )


@pytest.mark.integration
def test_a_chain_that_barely_moved_is_reported_not_summarised():
    samples, diag = sample_joint(
        compile_metamodel(_ridge_ir()),
        draws=1500,
        tune=600,
        chains=1,
        seed=11,
        surrogates={"s": _RazorSharpSurrogate()},
    )

    assert diag["poorly_mixed"], (
        "a near-delta surrogate likelihood puts the posterior on a ridge that a "
        "coordinate-wise random walk cannot follow, and this run must be flagged. "
        f"accept_rate={diag['accept_rate']:.3f}, ess={diag['ess']}"
    )
    # The specific failure: healthy-looking accept_rate, useless chain.
    spread = float(np.asarray(samples["a"], dtype=float).std())
    assert spread < 0.1 * 0.6, (
        f"expected the stuck chain to explore far less than its prior sd of 0.6; got {spread:.4g}"
    )
    assert "a" in diag["poorly_mixed"], diag["poorly_mixed"]


@pytest.mark.integration
def test_a_well_mixed_chain_is_not_flagged():
    """The warning must stay rare, or it becomes noise people learn to ignore."""
    ir = MetamodelIR(
        name="pair",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(variable="x", distribution={"kind": "normal", "loc": 1.0, "scale": 0.5}),
            PriorFactorIR(variable="y", distribution={"kind": "normal", "loc": 0.0, "scale": 2.0}),
            CouplingFactorIR(
                coupling_type="gaussian_link",
                source="x",
                target="y",
                transform={"kind": "affine", "alpha": 1.5, "beta": -0.4},
                sigma=0.3,
            ),
        ],
    )
    _, diag = sample_joint(compile_metamodel(ir), draws=4000, tune=1500, chains=2, seed=11)
    assert not diag["poorly_mixed"], (
        f"false alarm on a chain that mixes fine: ess={diag['ess']}, "
        f"accept_rate={diag['accept_rate']:.3f}"
    )
    assert min(diag["ess"].values()) > 20.0, diag["ess"]
