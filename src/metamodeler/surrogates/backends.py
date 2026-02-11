"""Surrogate backend implementations behind a neutral interface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from metamodeler.surrogates import SurrogateModel


@dataclass
class LinearGaussianModel:
    weights: np.ndarray
    bias: float
    sigma: float
    input_names: list[str]
    output_name: str

    def _x(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        return np.column_stack(
            [np.asarray(inputs[name], dtype=float).reshape(-1) for name in self.input_names]
        )

    def _mean(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        x = self._x(inputs)
        return x @ self.weights + self.bias

    def sample(self, inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray:
        mean = self._mean(inputs)
        rng = np.random.default_rng(seed)
        return rng.normal(loc=mean[:, None], scale=self.sigma, size=(len(mean), n))

    def log_prob(self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray:
        mean = self._mean(inputs)
        y = np.asarray(outputs[self.output_name], dtype=float).reshape(-1)
        var = self.sigma**2
        return -0.5 * (np.log(2 * np.pi * var) + ((y - mean) ** 2) / var)

    def summary(self, inputs: dict[str, np.ndarray]) -> dict:
        mean = self._mean(inputs)
        return {"mean": mean.tolist(), "sigma": self.sigma, "n": int(len(mean))}


class PymcGPSurrogateModel(LinearGaussianModel):
    """Pragmatic baseline that exposes a pymc_gp backend contract."""


class SbiNPESurrogateModel(LinearGaussianModel):
    """Pragmatic baseline that exposes an sbi_npe-like contract."""


class _ModelWrapper(SurrogateModel):
    def __init__(self, model: LinearGaussianModel) -> None:
        self.model = model

    def sample(self, inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray:
        return self.model.sample(inputs, n, seed)

    def log_prob(self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray:
        return self.model.log_prob(inputs, outputs)

    def summary(self, inputs: dict[str, np.ndarray]) -> dict:
        return self.model.summary(inputs)


def _fit_linear(
    x: np.ndarray, y: np.ndarray, input_names: list[str], output_name: str
) -> LinearGaussianModel:
    x_design = np.column_stack([x, np.ones(len(x))])
    beta, *_ = np.linalg.lstsq(x_design, y, rcond=None)
    weights = np.asarray(beta[:-1], dtype=float)
    bias = float(beta[-1])
    residual = y - (x @ weights + bias)
    sigma = float(max(np.sqrt(np.mean(residual**2)), 1e-6))
    return LinearGaussianModel(
        weights=weights,
        bias=bias,
        sigma=sigma,
        input_names=input_names,
        output_name=output_name,
    )


def fit_backend_model(
    backend: str, x: np.ndarray, y: np.ndarray, input_names: list[str], output_name: str
):
    model = _fit_linear(x=x, y=y, input_names=input_names, output_name=output_name)
    if backend == "pymc_gp":
        return PymcGPSurrogateModel(**model.__dict__)
    if backend == "sbi_npe":
        return SbiNPESurrogateModel(**model.__dict__)
    raise ValueError(f"Unsupported backend: {backend}")


def save_backend_payload(model: LinearGaussianModel, payload_path: Path) -> None:
    payload_path.write_text(
        json.dumps(
            {
                "weights": model.weights.tolist(),
                "bias": model.bias,
                "sigma": model.sigma,
                "input_names": model.input_names,
                "output_name": model.output_name,
            },
            indent=2,
            sort_keys=True,
        )
    )


def load_backend_model(backend: str, payload_path: Path):
    payload = json.loads(payload_path.read_text())
    kwargs = {
        "weights": np.asarray(payload["weights"], dtype=float),
        "bias": float(payload["bias"]),
        "sigma": float(payload["sigma"]),
        "input_names": list(payload["input_names"]),
        "output_name": str(payload["output_name"]),
    }
    if backend == "pymc_gp":
        model = PymcGPSurrogateModel(**kwargs)
    elif backend == "sbi_npe":
        model = SbiNPESurrogateModel(**kwargs)
    else:
        raise ValueError(f"Unsupported backend: {backend}")
    return _ModelWrapper(model)
