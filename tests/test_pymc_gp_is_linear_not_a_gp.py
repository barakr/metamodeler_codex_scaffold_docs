"""`pymc_gp` is Bayesian linear regression, and the tutorials depend on that being true.

The backend name says "gp". The model is `mu = intercept + x @ beta` with normal priors —
no kernel, no covariance function. That gap is not cosmetic: it produced a family of
wrong statements across Tutorials 5, 6 and 9, all reasoning from Gaussian-process
behaviour the code does not have ("predictions revert toward the prior mean far from the
data", "error bars widen as you leave the training region"). A GP does that. This does the
opposite — it extrapolates a linear trend confidently and forever.

Those tutorials now teach the real behaviour, including why it is the more dangerous one:
a linear surrogate on a nonlinear system is confidently wrong with near-zero error bars,
whereas a GP widens and warns you.

This test pins the behaviour the prose now describes. If someone later swaps in an actual
GP — a reasonable thing to want — this fails, which is the signal to go rewrite the
tutorial passages rather than let them quietly become wrong again in the other direction.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.backend_support import _has_pymc, is_pymc_runtime_constraint

pytestmark = [pytest.mark.optional_backend, pytest.mark.slow]


def _fit_linear_truth():
    """Train on a,b in [0,2] with y = a + b — the tutorials' toy model and range."""
    from bayesian_metamodeling.surrogates.backends import fit_backend_model

    rng = np.random.default_rng(0)
    a = rng.uniform(0.0, 2.0, size=60)
    b = rng.uniform(0.0, 2.0, size=60)
    x = np.column_stack([a, b])
    y = (a + b).reshape(-1, 1)
    return fit_backend_model(
        backend="pymc_gp",
        x=x,
        y=y,
        input_names=["a", "b"],
        output_names=["y"],
        backend_config={"draws": 300, "tune": 300, "chains": 1, "target_accept": 0.9},
        seed=0,
    )


def _predict(model, a, b, n=400, seed=1):
    draws = np.asarray(
        model.sample(inputs={"a": np.array([a]), "b": np.array([b])}, n=n, seed=seed)
    ).reshape(-1)
    return float(draws.mean()), float(draws.std())


@pytest.mark.parametrize("point", [(5.0, 5.0), (20.0, 20.0), (100.0, 100.0)])
def test_extrapolates_confidently_far_outside_the_training_box(point):
    """No reversion to the prior mean, and no widening — the opposite of a GP."""
    if not _has_pymc():
        pytest.skip("needs pymc")
    try:
        model = _fit_linear_truth()
    except Exception as exc:  # noqa: BLE001
        if is_pymc_runtime_constraint(exc):
            pytest.skip(f"pymc toolchain constraint, not a regression: {exc}")
        raise

    a, b = point
    mean, sd = _predict(model, a, b)
    truth = a + b

    # It tracks the linear truth even 50x outside the training range. A GP's mean would
    # have collapsed toward its prior long before (100, 100).
    assert abs(mean - truth) < 0.05 * truth, (
        f"at {point} the mean is {mean:.3f}, not the linear extrapolation {truth:.3f}. "
        "If this backend has become a real GP, Tutorials 5/6/9 need their extrapolation "
        "passages rewritten — they now teach confident linear extrapolation."
    )
    # And it does not hedge. A GP's predictive sd grows without bound away from the data.
    assert sd < 0.05, (
        f"at {point} the predictive sd is {sd:.4f}. The tutorials tell students this "
        "backend does NOT widen away from the training region, and that reading the "
        "predictive width as a distance-from-data signal is a mistake here."
    )


def test_no_gaussian_process_machinery_in_the_backend():
    """Cheap structural guard on the claim the docstrings now make."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "bayesian_metamodeling"
    offenders = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in ("pm.gp.", "pymc.gp.", "ExpQuad", "Matern52", "Matern32"):
            if marker in text:
                offenders.append(f"{path.relative_to(src)}: {marker}")
    assert not offenders, (
        "Gaussian-process machinery appeared in the package: "
        f"{offenders}. The `pymc_gp` backend has always been Bayesian linear regression, "
        "and Tutorials 5/6/9 teach that explicitly. If a real GP is being added, update "
        "those passages in the same change."
    )
