"""Contract tests for surrogate model implementations."""

from __future__ import annotations

import numpy as np

from bayesian_metamodeling.surrogates.backends import LinearGaussianModel, _ModelWrapper
from bayesian_metamodeling.surrogates.mock import MockGaussianConditionalSurrogate


def _linear_model():
    return LinearGaussianModel(
        weights=np.array([1.0, 2.0]),
        bias=0.5,
        sigma=0.1,
        input_names=["a", "b"],
        output_name="y",
    )


def _inputs():
    return {"a": np.array([1.0, 2.0]), "b": np.array([3.0, 4.0])}


# --- LinearGaussianModel ---


def test_linear_gaussian_sample_shape():
    model = _linear_model()
    samples = model.sample(_inputs(), n=10, seed=42)
    assert samples.shape == (2, 10)


def test_linear_gaussian_log_prob_shape():
    model = _linear_model()
    outputs = {"y": np.array([7.5, 9.5])}
    lp = model.log_prob(_inputs(), outputs)
    assert lp.shape == (2,)


def test_linear_gaussian_log_prob_higher_at_mean():
    model = _linear_model()
    mean = model._mean(_inputs())
    lp_at_mean = model.log_prob(_inputs(), {"y": mean})
    lp_away = model.log_prob(_inputs(), {"y": mean + 10.0})
    assert np.all(lp_at_mean > lp_away)


def test_linear_gaussian_summary():
    model = _linear_model()
    result = model.summary(_inputs())
    assert "mean" in result
    assert "sigma" in result
    assert result["n"] == 2


def test_linear_gaussian_deterministic_with_zero_sigma():
    model = LinearGaussianModel(
        weights=np.array([1.0]),
        bias=0.0,
        sigma=1e-10,
        input_names=["x"],
        output_name="y",
    )
    samples = model.sample({"x": np.array([5.0])}, n=100, seed=0)
    assert np.allclose(samples, 5.0, atol=1e-6)


# --- MockGaussianConditionalSurrogate ---


def test_mock_surrogate_fit_and_sample():
    x = np.array([[1.0], [2.0], [3.0]])
    y = np.array([2.0, 4.0, 6.0])
    model = MockGaussianConditionalSurrogate.fit(x, y)
    inputs = {"x": np.array([2.5])}
    samples = model.sample(inputs, n=100, seed=0)
    assert samples.shape == (1, 100)
    assert np.abs(np.mean(samples) - 5.0) < 1.0


def test_mock_surrogate_log_prob():
    x = np.array([[1.0], [2.0], [3.0]])
    y = np.array([2.0, 4.0, 6.0])
    model = MockGaussianConditionalSurrogate.fit(x, y)
    lp = model.log_prob({"x": np.array([2.0])}, {"y": np.array([4.0])})
    assert lp.shape == (1,)
    assert np.isfinite(lp[0])


def test_mock_surrogate_summary():
    x = np.array([[1.0], [2.0], [3.0]])
    y = np.array([2.0, 4.0, 6.0])
    model = MockGaussianConditionalSurrogate.fit(x, y)
    result = model.summary({"x": np.array([2.0])})
    assert "mean" in result
    assert "n" in result


# --- _ModelWrapper ---


def test_model_wrapper_delegates():
    inner = _linear_model()
    wrapper = _ModelWrapper(inner)
    samples = wrapper.sample(_inputs(), n=5, seed=0)
    assert samples.shape == (2, 5)
    lp = wrapper.log_prob(_inputs(), {"y": np.array([7.5, 9.5])})
    assert lp.shape == (2,)
    summary = wrapper.summary(_inputs())
    assert "mean" in summary
