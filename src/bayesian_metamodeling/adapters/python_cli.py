"""Generic Python CLI adapter implementation."""

from __future__ import annotations

import json
from pathlib import Path

from bayesian_metamodeling.adapters.base import AdapterMaterialization
from bayesian_metamodeling.spec import ModelSpec


class PythonCLIAdapter:
    id = "python_cli_adapter_v1"

    def materialize_inputs(
        self, *, spec: ModelSpec, point: dict[str, float], run_dir: Path, repo_root: Path
    ) -> AdapterMaterialization:
        if spec.model.artifact.entrypoint is None:
            raise ValueError("model.artifact.entrypoint is required for python_cli_adapter_v1")

        command = list(spec.model.artifact.entrypoint)
        # This is a USABILITY check, not a security boundary. It catches "I pointed at
        # the wrong directory", which is a real and common mistake. It does not — and
        # cannot — contain a spec: `entrypoint` names the command to execute, so running
        # a spec is running its author's code, by design. That is how this tool composes
        # heterogeneous models (see README, "Specs are trusted input").
        #
        # Do not read the check below as a sandbox. It inspects path-like arguments only;
        # the interpreter in `command[0]` is unconstrained, and any argument could name a
        # script. It was previously commented as a security control, which was misleading.
        repo_root_resolved = repo_root.resolve()
        for argument in command[1:]:
            # Normalise `\` to `/` before deciding anything. Specs are portable JSON and
            # get shared between machines, so a path written on Windows must be judged
            # the same way on POSIX — where `..\..\x.py` is otherwise just a *filename*
            # containing backslashes, resolves happily inside the repo, and slips the
            # check entirely. The previous version tested only "/", so every
            # Windows-style path skipped it. `spec/modelspec.py` already normalises both
            # separators for `storage.root`; that knowledge had not reached here.
            normalized = argument.replace("\\", "/")
            if "/" not in normalized:
                continue
            candidate = Path(normalized)
            # Resolve relative arguments against the repo root, not this process's cwd:
            # the subprocess runs with `cwd=repo_root` (see AdapterMaterialization
            # below), so the repo root is the base that actually applies.
            if not candidate.is_absolute():
                candidate = repo_root / candidate
            if not candidate.resolve().is_relative_to(repo_root_resolved):
                raise ValueError(
                    f"Entrypoint path points outside the repository: {argument!r}. "
                    "This is a typo check, not a security boundary — if you meant it, "
                    "move the script into the repo."
                )
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
            output_path = (run_dir / endpoint.path).resolve()
            if not output_path.is_relative_to(run_dir.resolve()):
                raise ValueError(f"Path traversal detected in output mapping: {endpoint.path}")
            outputs[mapping.var] = json.loads(output_path.read_text(encoding="utf-8"))
        return outputs
