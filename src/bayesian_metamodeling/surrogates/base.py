"""Backend-neutral surrogate model interfaces."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class SurrogateModel(Protocol):
    def sample(self, inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray: ...

    def log_prob(
        self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]
    ) -> np.ndarray: ...

    def summary(self, inputs: dict[str, np.ndarray]) -> dict: ...
