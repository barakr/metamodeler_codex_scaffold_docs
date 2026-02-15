"""Generic Python CLI adapter implementation."""

from __future__ import annotations

import json
from pathlib import Path

from metamodeler.adapters.base import AdapterMaterialization
from metamodeler.spec import ModelSpec


class PythonCLIAdapter:
    id = "python_cli_adapter_v1"

    def materialize_inputs(
        self, *, spec: ModelSpec, point: dict[str, float], run_dir: Path, repo_root: Path
    ) -> AdapterMaterialization:
        if spec.model.artifact.entrypoint is None:
            raise ValueError("model.artifact.entrypoint is required for python_cli_adapter_v1")

        command = list(spec.model.artifact.entrypoint)
        for mapping in spec.adapter.input_mapping:
            if mapping.to is None:
                continue
            if mapping.to.kind != "cli_arg" or mapping.to.key is None:
                continue
            if mapping.var not in point:
                raise ValueError(f"Missing input variable '{mapping.var}' in design point")
            command.extend([mapping.to.key, str(point[mapping.var])])

        command.extend(["--run-dir", str(run_dir)])
        return AdapterMaterialization(
            command=command,
            cwd=repo_root,
            execution_env=dict(spec.runner.execution_env),
        )

    def parse_outputs(self, *, spec: ModelSpec, run_dir: Path) -> dict:
        outputs: dict = {}
        for mapping in spec.adapter.output_mapping:
            endpoint = mapping.from_
            if endpoint is None:
                continue
            if endpoint.kind != "file" or endpoint.path is None:
                raise ValueError("python_cli_adapter_v1 expects file-based output mappings")
            output_path = run_dir / endpoint.path
            outputs[mapping.var] = json.loads(output_path.read_text())
        return outputs
