"""Adapter interfaces and materialization contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from metamodeler.spec import ModelSpec


@dataclass
class AdapterMaterialization:
    command: list[str]
    cwd: Path
    execution_env: dict[str, str]


class Adapter(Protocol):
    id: str

    def materialize_inputs(
        self, *, spec: ModelSpec, point: dict[str, float], run_dir: Path, repo_root: Path
    ) -> AdapterMaterialization: ...

    def parse_outputs(self, *, spec: ModelSpec, run_dir: Path) -> dict: ...
