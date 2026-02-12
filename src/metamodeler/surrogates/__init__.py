"""Surrogate interfaces, backend models, and services."""

from metamodeler.surrogates.base import SurrogateModel
from metamodeler.surrogates.mock import MockGaussianConditionalSurrogate
from metamodeler.surrogates.service import eval_surrogate, fit_surrogate

__all__ = [
    "SurrogateModel",
    "MockGaussianConditionalSurrogate",
    "eval_surrogate",
    "fit_surrogate",
]
