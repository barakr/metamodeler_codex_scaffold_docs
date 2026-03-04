"""Adapter registry."""

from __future__ import annotations

from bayesian_metamodeling.adapters.base import Adapter
from bayesian_metamodeling.adapters.biomodels_sbml import BioModelsSBMLAdapter
from bayesian_metamodeling.adapters.python_cli import PythonCLIAdapter
from bayesian_metamodeling.spec import ModelSpec


def resolve_adapter(spec: ModelSpec) -> Adapter:
    if spec.adapter.id == "python_cli_adapter_v1":
        return PythonCLIAdapter()
    if spec.adapter.id == "biomodels_sbml_adapter_v1":
        return BioModelsSBMLAdapter()
    raise ValueError(f"Unsupported adapter id: {spec.adapter.id}")
