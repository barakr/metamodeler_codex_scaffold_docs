"""Local process runner."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from bayesian_metamodeling.adapters import AdapterMaterialization


@dataclass
class RunResult:
    returncode: int
    stdout_path: Path
    stderr_path: Path


class LocalProcessRunner:
    mode = "local_process"

    def __init__(self, *, timeout_sec: int | None = None) -> None:
        self.timeout_sec = timeout_sec

    def _build_command(self, materialization: AdapterMaterialization) -> list[str]:
        command = list(materialization.command)
        conda_env = materialization.execution_env.get("conda_env", "").strip()
        if conda_env:
            # Explicit "run worker in this other env" — wrap the whole command
            # so PATH/python resolve inside that env. The bare-python
            # substitution below does NOT apply here.
            return ["conda", "run", "-n", conda_env, *command]
        # Implicit "run worker in MY env": when an adapter built the command
        # with a bare `python` (e.g. `["python", str(worker_path), ...]`),
        # ALWAYS substitute `sys.executable`. Otherwise the worker subprocess
        # uses whatever PATH-`python` resolves to — typically base conda's
        # python, which usually does NOT have the optional packages
        # (libroadrunner, pymc, sbi, ...) the kernel/CLI env has installed.
        # That mismatch silently breaks every DOE point with a
        # `ModuleNotFoundError` recorded in sweep_logs.jsonl. The previous
        # `shutil.which("python") is None` guard was misguided — base
        # conda's python is on PATH almost everywhere, so the substitution
        # never fired. See Status.md "False success metric in tutorial
        # verification" post-mortem.
        if command and command[0] == "python":
            command[0] = sys.executable
        return command

    def run(self, *, materialization: AdapterMaterialization, run_dir: Path) -> RunResult:
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        command = self._build_command(materialization)

        try:
            completed = subprocess.run(
                command,
                cwd=materialization.cwd,
                text=True,
                capture_output=True,
                check=False,
                timeout=self.timeout_sec,
            )
        except subprocess.TimeoutExpired:
            stdout_path.write_text("")
            stderr_path.write_text(f"Process timed out after {self.timeout_sec} seconds")
            return RunResult(
                returncode=-1,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        stdout_path.write_text(completed.stdout)
        stderr_path.write_text(completed.stderr)
        return RunResult(
            returncode=completed.returncode,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
