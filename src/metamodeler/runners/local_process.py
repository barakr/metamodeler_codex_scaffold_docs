"""Local process runner."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from metamodeler.adapters import AdapterMaterialization


@dataclass
class RunResult:
    returncode: int
    stdout_path: Path
    stderr_path: Path


class LocalProcessRunner:
    mode = "local_process"

    def _build_command(self, materialization: AdapterMaterialization) -> list[str]:
        command = list(materialization.command)
        conda_env = materialization.execution_env.get("conda_env", "").strip()
        if conda_env:
            return ["conda", "run", "-n", conda_env, *command]
        if command and command[0] == "python" and shutil.which("python") is None:
            command[0] = sys.executable
        return command

    def run(self, *, materialization: AdapterMaterialization, run_dir: Path) -> RunResult:
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        command = self._build_command(materialization)

        completed = subprocess.run(
            command,
            cwd=materialization.cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        stdout_path.write_text(completed.stdout)
        stderr_path.write_text(completed.stderr)
        return RunResult(
            returncode=completed.returncode,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
