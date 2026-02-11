"""Surrogate interfaces and lightweight test implementations."""

from metamodeler.surrogates.base import SurrogateModel
from metamodeler.surrogates.mock import MockGaussianConditionalSurrogate

__all__ = ["SurrogateModel", "MockGaussianConditionalSurrogate"]
