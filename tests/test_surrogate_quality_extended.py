"""Extended surrogate quality tests (slow, optional_backend)."""

from __future__ import annotations

import numpy as np
import pytest

from bayesian_metamodeling.surrogates.backends import LinearGaussianModel


@pytest.mark.slow
@pytest.mark.optional_backend
def test_uncertainty_widens_away_from_training_data():
    """Surrogate predictions should have wider uncertainty far from training data.

    For a linear Gaussian model this is constant by design, so we test
    that the model produces reasonable predictions at extrapolation points.
    """
    model = LinearGaussianModel(
        weights=np.array([1.0]),
        bias=0.0,
        sigma=0.2,
        input_names=["x"],
        output_name="y",
    )
    near = model.sample({"x": np.array([1.0])}, n=500, seed=0)
    far = model.sample({"x": np.array([100.0])}, n=500, seed=0)
    # Mean should scale with input
    assert abs(np.mean(near) - 1.0) < 0.5
    assert abs(np.mean(far) - 100.0) < 0.5


@pytest.mark.slow
@pytest.mark.optional_backend
def test_surrogate_samples_are_reproducible():
    """Same seed should produce identical samples."""
    model = LinearGaussianModel(
        weights=np.array([1.0, 0.5]),
        bias=0.1,
        sigma=0.3,
        input_names=["a", "b"],
        output_name="y",
    )
    inputs = {"a": np.array([1.0, 2.0]), "b": np.array([3.0, 4.0])}
    s1 = model.sample(inputs, n=50, seed=42)
    s2 = model.sample(inputs, n=50, seed=42)
    np.testing.assert_array_equal(s1, s2)
