"""Adapter interfaces and registry."""

from metamodeler.adapters.base import Adapter, AdapterMaterialization
from metamodeler.adapters.biomodels_sbml import BioModelsSBMLAdapter
from metamodeler.adapters.python_cli import PythonCLIAdapter
from metamodeler.adapters.registry import resolve_adapter

__all__ = [
    "Adapter",
    "AdapterMaterialization",
    "BioModelsSBMLAdapter",
    "PythonCLIAdapter",
    "resolve_adapter",
]
