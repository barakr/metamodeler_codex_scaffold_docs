"""Simple learned surrogate used by fast tests."""

from __future__ import annotations

import numpy as np


class MockGaussianConditionalSurrogate:
    """Linear mean + Gaussian noise conditional model.

    This is a backend-neutral test surrogate implementation used for smoke and quality tests.
    """

    def __init__(self, weights: np.ndarray, bias: float, sigma: float) -> None:
        self.weights = weights
        self.bias = float(bias)
        self.sigma = float(max(sigma, 1e-6))

    @classmethod
    def fit(cls, x: np.ndarray, y: np.ndarray) -> "MockGaussianConditionalSurrogate":
        x2 = np.asarray(x, dtype=float)
        y2 = np.asarray(y, dtype=float).reshape(-1)
        x_design = np.column_stack([x2, np.ones(len(x2))])
        beta, *_ = np.linalg.lstsq(x_design, y2, rcond=None)
        weights = beta[:-1]
        bias = beta[-1]
        mean = x2 @ weights + bias
        sigma = float(np.sqrt(np.mean((y2 - mean) ** 2)))
        return cls(weights=weights, bias=bias, sigma=sigma)

    def _mean(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        ordered_keys = sorted(inputs.keys())
        x = np.column_stack([np.asarray(inputs[k], dtype=float).reshape(-1) for k in ordered_keys])
        return x @ self.weights + self.bias

    def sample(self, inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray:
        mean = self._mean(inputs)
        rng = np.random.default_rng(seed)
        draws = rng.normal(loc=mean[:, None], scale=self.sigma, size=(len(mean), n))
        return draws

    def log_prob(self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray:
        y = np.asarray(outputs[sorted(outputs.keys())[0]], dtype=float).reshape(-1)
        mean = self._mean(inputs)
        var = self.sigma**2
        return -0.5 * (np.log(2 * np.pi * var) + ((y - mean) ** 2) / var)

    def summary(self, inputs: dict[str, np.ndarray]) -> dict:
        mean = self._mean(inputs)
        return {
            "mean": mean.tolist(),
            "sigma": self.sigma,
            "n": int(len(mean)),
        }
