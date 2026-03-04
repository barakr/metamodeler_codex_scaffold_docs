"""Adapter interfaces and registry."""

from bayesian_metamodeling.adapters.base import Adapter, AdapterMaterialization
from bayesian_metamodeling.adapters.biomodels_sbml import BioModelsSBMLAdapter
from bayesian_metamodeling.adapters.python_cli import PythonCLIAdapter
from bayesian_metamodeling.adapters.registry import resolve_adapter

__all__ = [
    "Adapter",
    "AdapterMaterialization",
    "BioModelsSBMLAdapter",
    "PythonCLIAdapter",
    "resolve_adapter",
]
