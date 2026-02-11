"""Local process runner."""

from __future__ import annotations

import subprocess
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

    def run(self, *, materialization: AdapterMaterialization, run_dir: Path) -> RunResult:
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"

        completed = subprocess.run(
            materialization.command,
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
