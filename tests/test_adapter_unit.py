"""Unit tests for adapter protocol implementations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bayesian_metamodeling.adapters import (
    BioModelsSBMLAdapter,
    PythonCLIAdapter,
    resolve_adapter,
)
from bayesian_metamodeling.spec import load_and_validate_modelspec


def _base_payload(**overrides) -> dict:
    base = {
        "schema_version": "1.0",
        "model": {
            "name": "test",
            "version": "1.0",
            "artifact": {"type": "local", "entrypoint": ["python", "model.py"]},
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
        "storage": {"root": "tmp/test"},
    }
    base.update(overrides)
    return base


# --- PythonCLIAdapter ---


def test_python_cli_adapter_builds_command_with_mappings(tmp_path):
    payload = _base_payload()
    payload["adapter"]["input_mapping"] = [
        {"var": "a", "to": {"kind": "cli_arg", "key": "--alpha"}}
    ]
    spec = load_and_validate_modelspec(payload)
    adapter = PythonCLIAdapter()
    mat = adapter.materialize_inputs(
        spec=spec,
        point={"a": 3.14},
        run_dir=tmp_path,
        repo_root=Path.cwd(),
    )
    assert "--alpha" in mat.command
    assert "3.14" in mat.command
    assert "--run-dir" in mat.command


def test_python_cli_adapter_raises_on_missing_entrypoint():
    payload = _base_payload()
    payload["model"]["artifact"] = {"type": "biomodels", "biomodels_id": "MODEL123"}
    payload["adapter"]["id"] = "python_cli_adapter_v1"
    spec = load_and_validate_modelspec(payload)
    adapter = PythonCLIAdapter()
    with pytest.raises(ValueError, match="entrypoint is required"):
        adapter.materialize_inputs(
            spec=spec,
            point={"a": 1.0},
            run_dir=Path("/tmp/run"),
            repo_root=Path.cwd(),
        )


def test_python_cli_adapter_parses_file_outputs(tmp_path):
    payload = _base_payload()
    payload["adapter"]["output_mapping"] = [
        {"var": "y", "from": {"kind": "file", "path": "results.json"}}
    ]
    spec = load_and_validate_modelspec(payload)
    adapter = PythonCLIAdapter()

    (tmp_path / "results.json").write_text(json.dumps({"value": 42}))
    outputs = adapter.parse_outputs(spec=spec, run_dir=tmp_path)
    assert outputs["y"] == {"value": 42}


def test_python_cli_adapter_rejects_path_traversal_in_output(tmp_path):
    payload = _base_payload()
    payload["adapter"]["output_mapping"] = [
        {"var": "y", "from": {"kind": "file", "path": "../../etc/passwd"}}
    ]
    spec = load_and_validate_modelspec(payload)
    adapter = PythonCLIAdapter()
    with pytest.raises(ValueError, match="traversal"):
        adapter.parse_outputs(spec=spec, run_dir=tmp_path)


# --- BioModelsSBMLAdapter ---


def test_biomodels_adapter_requires_biomodels_id():
    payload = _base_payload()
    payload["model"]["artifact"] = {"type": "local", "entrypoint": ["python", "x.py"]}
    payload["adapter"]["id"] = "biomodels_sbml_adapter_v1"
    spec = load_and_validate_modelspec(payload)
    adapter = BioModelsSBMLAdapter()
    with pytest.raises(ValueError, match="biomodels_id"):
        adapter.materialize_inputs(
            spec=spec,
            point={"a": 1.0},
            run_dir=Path("/tmp/run"),
            repo_root=Path.cwd(),
        )


# --- Registry ---


def test_resolve_adapter_returns_python_cli():
    spec = load_and_validate_modelspec(_base_payload())
    adapter = resolve_adapter(spec)
    assert isinstance(adapter, PythonCLIAdapter)


def test_resolve_adapter_returns_biomodels():
    payload = _base_payload()
    payload["model"]["artifact"] = {"type": "biomodels", "biomodels_id": "MODEL123"}
    payload["adapter"]["id"] = "biomodels_sbml_adapter_v1"
    spec = load_and_validate_modelspec(payload)
    adapter = resolve_adapter(spec)
    assert isinstance(adapter, BioModelsSBMLAdapter)


def test_resolve_adapter_raises_on_unknown_id():
    payload = _base_payload()
    payload["adapter"]["id"] = "unknown_adapter_v99"
    spec = load_and_validate_modelspec(payload)
    with pytest.raises(ValueError, match="Unsupported adapter"):
        resolve_adapter(spec)
