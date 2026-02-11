"""Adapter interfaces and registry."""

from metamodeler.adapters.base import Adapter, AdapterMaterialization
from metamodeler.adapters.registry import resolve_adapter

__all__ = ["Adapter", "AdapterMaterialization", "resolve_adapter"]
