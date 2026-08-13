"""Tests for run failure handling: nonexistent entrypoints, partial failures."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from bayesian_metamodeling.execution import execute_design_point
from bayesian_metamodeling.spec import load_and_validate_modelspec


def _make_spec():
    return load_and_validate_modelspec(
        {
            "schema_version": "1.0",
            "model": {
                "name": "test",
                "version": "1.0",
                "artifact": {"type": "local", "entrypoint": ["python", "nope.py"]},
            },
            "runner": {
                "mode": "local_process",
                "resources": {"cpus": 1, "mem_gb": 1, "walltime_min": 1},
            },
            "io_schema": {
                "inputs": [{"name": "a", "type": "float", "units": "m"}],
                "outputs": [{"name": "y", "type": "float", "units": "m"}],
            },
            "design": {"strategy": "grid", "grid": {"a": [1.0]}},
            "adapter": {"id": "python_cli_adapter_v1"},
            "reproducibility": {"seed": 0},
            "storage": {"root": "tmp/run_fail_test"},
        }
    )


def test_nonexistent_entrypoint_records_failure():
    """A subprocess that fails (e.g. nonexistent script) records as failed."""
    spec = _make_spec()

    def _fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="No such file")

    with patch("subprocess.run", _fake_run):
        result = execute_design_point(
            spec=spec,
            point_index=0,
            point={"a": 1.0},
            run_token="failtest",
        )
    assert result["status"] == "failed"
    assert result["returncode"] == 1


def test_partial_failures_in_batch():
    """Multiple design points can have mixed success/failure."""
    spec = _make_spec()
    call_count = {"n": 0}

    def _alternating_run(command, **kwargs):
        call_count["n"] += 1
        if call_count["n"] % 2 == 0:
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="error")

    results = []
    with patch("subprocess.run", _alternating_run):
        for i in range(4):
            r = execute_design_point(
                spec=spec,
                point_index=i,
                point={"a": float(i)},
                run_token="batchtest",
            )
            results.append(r)

    statuses = [r["status"] for r in results]
    assert "failed" in statuses


def test_output_parse_failure_records_as_failed():
    """If subprocess succeeds but output parsing fails, result is 'failed'."""
    spec = load_and_validate_modelspec(
        {
            "schema_version": "1.0",
            "model": {
                "name": "test",
                "version": "1.0",
                "artifact": {"type": "local", "entrypoint": ["python", "nope.py"]},
            },
            "runner": {
                "mode": "local_process",
                "resources": {"cpus": 1, "mem_gb": 1, "walltime_min": 1},
            },
            "io_schema": {
                "inputs": [{"name": "a", "type": "float", "units": "m"}],
                "outputs": [{"name": "y", "type": "float", "units": "m"}],
            },
            "design": {"strategy": "grid", "grid": {"a": [1.0]}},
            "adapter": {
                "id": "python_cli_adapter_v1",
                "output_mapping": [{"var": "y", "from": {"kind": "file", "path": "results.json"}}],
            },
            "reproducibility": {"seed": 0},
            "storage": {"root": "tmp/run_fail_test"},
        }
    )

    def _success_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    with patch("subprocess.run", _success_run):
        result = execute_design_point(
            spec=spec,
            point_index=0,
            point={"a": 1.0},
            run_token="parsefail",
        )
    # parse_outputs will fail because results.json doesn't exist
    assert result["status"] == "failed"
    assert "Output parsing failed" in result["error"]
