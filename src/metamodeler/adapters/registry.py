"""Adapter registry."""

from __future__ import annotations

from metamodeler.adapters.base import Adapter
from metamodeler.adapters.python_cli import PythonCLIAdapter
from metamodeler.spec import ModelSpec


def resolve_adapter(spec: ModelSpec) -> Adapter:
    if spec.adapter.id == "python_cli_adapter_v1":
        return PythonCLIAdapter()
    raise ValueError(f"Unsupported adapter id: {spec.adapter.id}")
