from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from bayesian_metamodeling.adapters.base import AdapterMaterialization
from bayesian_metamodeling.runners.local_process import LocalProcessRunner


def test_local_process_runner_uses_current_environment_by_default(monkeypatch, tmp_path):
    seen: dict[str, list[str]] = {}

    def _fake_run(command, **kwargs):
        seen["command"] = list(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    runner = LocalProcessRunner()
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    materialization = AdapterMaterialization(
        command=["python", "-c", "print('x')"],
        cwd=Path("."),
        execution_env={},
    )
    result = runner.run(materialization=materialization, run_dir=run_dir)

    expected_prefix = "python" if shutil.which("python") else sys.executable
    assert seen["command"] == [expected_prefix, "-c", "print('x')"]
    assert result.returncode == 0
    assert result.stdout_path.exists()
    assert result.stderr_path.exists()


def test_local_process_runner_can_prefix_conda_environment(monkeypatch, tmp_path):
    seen: dict[str, list[str]] = {}

    def _fake_run(command, **kwargs):
        seen["command"] = list(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    runner = LocalProcessRunner()
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    materialization = AdapterMaterialization(
        command=["python", "-c", "print('x')"],
        cwd=Path("."),
        execution_env={"conda_env": "py312_metamodeling_pymc"},
    )
    runner.run(materialization=materialization, run_dir=run_dir)

    assert seen["command"][:4] == ["conda", "run", "-n", "py312_metamodeling_pymc"]
    assert seen["command"][4:] == ["python", "-c", "print('x')"]


def test_local_process_runner_passes_timeout_to_subprocess(monkeypatch, tmp_path):
    captured_kwargs: dict = {}

    def _fake_run(command, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    runner = LocalProcessRunner(timeout_sec=120)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    materialization = AdapterMaterialization(
        command=["python", "-c", "print('x')"],
        cwd=Path("."),
        execution_env={},
    )
    runner.run(materialization=materialization, run_dir=run_dir)
    assert captured_kwargs["timeout"] == 120


def test_local_process_runner_handles_timeout_expired(monkeypatch, tmp_path):
    def _fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 1))

    monkeypatch.setattr(subprocess, "run", _fake_run)

    runner = LocalProcessRunner(timeout_sec=1)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    materialization = AdapterMaterialization(
        command=["python", "-c", "import time; time.sleep(999)"],
        cwd=Path("."),
        execution_env={},
    )
    result = runner.run(materialization=materialization, run_dir=run_dir)
    assert result.returncode == -1
    assert "timed out" in result.stderr_path.read_text()
