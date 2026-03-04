"""Unit tests for LocalProcessRunner including build_command variants."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from bayesian_metamodeling.adapters.base import AdapterMaterialization
from bayesian_metamodeling.runners.local_process import LocalProcessRunner


def test_build_command_no_conda(monkeypatch):
    runner = LocalProcessRunner()
    mat = AdapterMaterialization(
        command=["python", "-c", "print(1)"],
        cwd=Path("."),
        execution_env={},
    )
    cmd = runner._build_command(mat)
    expected = "python" if shutil.which("python") else sys.executable
    assert cmd[0] == expected
    assert cmd[1:] == ["-c", "print(1)"]


def test_build_command_with_conda():
    runner = LocalProcessRunner()
    mat = AdapterMaterialization(
        command=["python", "train.py"],
        cwd=Path("."),
        execution_env={"conda_env": "myenv"},
    )
    cmd = runner._build_command(mat)
    assert cmd[:4] == ["conda", "run", "-n", "myenv"]
    assert cmd[4:] == ["python", "train.py"]


def test_build_command_non_python():
    runner = LocalProcessRunner()
    mat = AdapterMaterialization(
        command=["./run.sh", "--arg", "val"],
        cwd=Path("."),
        execution_env={},
    )
    cmd = runner._build_command(mat)
    assert cmd == ["./run.sh", "--arg", "val"]


def test_runner_captures_stdout_and_stderr(monkeypatch, tmp_path):
    def _fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="hello", stderr="warn")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    runner = LocalProcessRunner()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mat = AdapterMaterialization(command=["echo"], cwd=Path("."), execution_env={})
    result = runner.run(materialization=mat, run_dir=run_dir)
    assert result.returncode == 0
    assert result.stdout_path.read_text() == "hello"
    assert result.stderr_path.read_text() == "warn"


def test_runner_returns_nonzero_returncode(monkeypatch, tmp_path):
    def _fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="error")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    runner = LocalProcessRunner()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mat = AdapterMaterialization(command=["false"], cwd=Path("."), execution_env={})
    result = runner.run(materialization=mat, run_dir=run_dir)
    assert result.returncode == 1


def test_runner_default_timeout_is_none():
    runner = LocalProcessRunner()
    assert runner.timeout_sec is None


def test_runner_timeout_is_configurable():
    runner = LocalProcessRunner(timeout_sec=300)
    assert runner.timeout_sec == 300
