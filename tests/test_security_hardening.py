"""Security hardening tests for path traversal, input validation, and deserialization guards."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from bayesian_metamodeling.adapters.python_cli import PythonCLIAdapter
from bayesian_metamodeling.spec import load_and_validate_modelspec
from bayesian_metamodeling.surrogates.dataset import _resolve_dataset_root


def _minimal_spec_payload(**overrides) -> dict:
    base = {
        "schema_version": "1.0",
        "model": {
            "name": "test",
            "version": "0.1.0",
            "artifact": {"type": "local", "entrypoint": ["python", "run.py"]},
        },
        "runner": {
            "mode": "local_process",
            "resources": {"cpus": 1, "mem_gb": 1, "walltime_min": 1},
        },
        "io_schema": {
            "inputs": [{"name": "x", "type": "float", "units": "m", "support": [0.0, 1.0]}],
            "outputs": [{"name": "y", "type": "float", "units": "m"}],
        },
        "design": {"strategy": "grid", "grid": {"x": [0.0, 0.5, 1.0]}},
        "adapter": {
            "id": "python_cli_adapter_v1",
            "input_mapping": [{"var": "x", "to": {"kind": "cli_arg", "key": "--x"}}],
            "output_mapping": [{"var": "y", "from": {"kind": "file", "path": "out.json"}}],
        },
        "reproducibility": {"seed": 42},
        "storage": {"root": "tmp/test_store"},
    }
    for key, val in overrides.items():
        keys = key.split(".")
        target = base
        for k in keys[:-1]:
            target = target[k]
        target[keys[-1]] = val
    return base


# --- Path traversal in output mapping (H2) ---


class TestOutputPathTraversal:
    def test_rejects_path_traversal_in_output_mapping(self, tmp_path):
        adapter = PythonCLIAdapter()
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        spec_payload = _minimal_spec_payload()
        spec_payload["adapter"]["output_mapping"] = [
            {"var": "y", "from": {"kind": "file", "path": "../../etc/passwd"}}
        ]
        spec = load_and_validate_modelspec(spec_payload)

        with pytest.raises(ValueError, match="Path traversal detected"):
            adapter.parse_outputs(spec=spec, run_dir=run_dir)

    def test_accepts_normal_output_path(self, tmp_path):
        adapter = PythonCLIAdapter()
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        out_file = run_dir / "out.json"
        out_file.write_text(json.dumps({"value": 1.0}))

        spec_payload = _minimal_spec_payload()
        spec = load_and_validate_modelspec(spec_payload)
        result = adapter.parse_outputs(spec=spec, run_dir=run_dir)
        assert "y" in result


# --- Entrypoint validation (H1) ---


class TestEntrypointValidation:
    def test_rejects_entrypoint_outside_repo(self, tmp_path):
        adapter = PythonCLIAdapter()
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        spec_payload = _minimal_spec_payload()
        spec_payload["model"]["artifact"]["entrypoint"] = [
            "python",
            "/etc/evil_script.py",
        ]
        spec = load_and_validate_modelspec(spec_payload)

        with pytest.raises(ValueError, match="Entrypoint path must be within repo root"):
            adapter.materialize_inputs(
                spec=spec, point={"x": 0.5}, run_dir=run_dir, repo_root=repo_root
            )

    def test_accepts_relative_entrypoint(self, tmp_path):
        adapter = PythonCLIAdapter()
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        spec_payload = _minimal_spec_payload()
        spec = load_and_validate_modelspec(spec_payload)
        result = adapter.materialize_inputs(
            spec=spec, point={"x": 0.5}, run_dir=run_dir, repo_root=repo_root
        )
        assert "run.py" in result.command


# --- conda_env validation (H4) ---


class TestCondaEnvValidation:
    @pytest.mark.parametrize(
        "bad_name",
        [
            "; rm -rf /",
            "env && evil",
            "../escape",
            "",
            " ",
            "-startswithdash",
        ],
    )
    def test_rejects_invalid_conda_env_names(self, bad_name):
        payload = _minimal_spec_payload()
        payload["runner"]["execution_env"] = {"conda_env": bad_name}
        with pytest.raises(ValidationError):
            load_and_validate_modelspec(payload)

    @pytest.mark.parametrize(
        "good_name",
        [
            "py314_bayesmm",
            "my.env",
            "env-name",
            "env_name",
        ],
    )
    def test_accepts_valid_conda_env_names(self, good_name):
        payload = _minimal_spec_payload()
        payload["runner"]["execution_env"] = {"conda_env": good_name}
        spec = load_and_validate_modelspec(payload)
        assert spec.runner.execution_env["conda_env"] == good_name


# --- storage.root traversal guard (L1) ---


class TestStorageRootTraversal:
    def test_rejects_storage_root_with_traversal(self):
        payload = _minimal_spec_payload()
        payload["storage"]["root"] = "../outside_project/data"
        with pytest.raises(ValidationError, match="traversal"):
            load_and_validate_modelspec(payload)

    def test_rejects_absolute_storage_root(self):
        payload = _minimal_spec_payload()
        payload["storage"]["root"] = "/tmp/absolute"
        with pytest.raises(ValidationError, match="project-relative"):
            load_and_validate_modelspec(payload)

    def test_accepts_normal_storage_root(self):
        payload = _minimal_spec_payload()
        payload["storage"]["root"] = "tmp/test_store"
        spec = load_and_validate_modelspec(payload)
        assert spec.storage.root == "tmp/test_store"


# --- Dataset path validation (M1) ---


class TestDatasetPathValidation:
    def test_rejects_traversal_in_dataset_path(self):
        with pytest.raises(ValueError, match="traversal"):
            _resolve_dataset_root("../outside/data")

    def test_rejects_traversal_in_dataset_dict(self):
        with pytest.raises(ValueError, match="traversal"):
            _resolve_dataset_root({"run_store_root": "../escape"})

    def test_accepts_normal_dataset_path(self):
        result = _resolve_dataset_root("tmp/test_store")
        assert result == Path("tmp/test_store")

    def test_accepts_absolute_dataset_path(self):
        result = _resolve_dataset_root("/tmp/test_store")
        assert result == Path("/tmp/test_store")


# --- torch deserialization type check (C1) ---


class TestTorchDeserializationTypeCheck:
    def test_rejects_object_without_posterior_interface(self, monkeypatch):
        import bayesian_metamodeling.surrogates.backends as backends_mod

        fake_torch = MagicMock()
        fake_torch.load.return_value = {"not": "a posterior"}
        monkeypatch.setattr(backends_mod, "_require_torch", lambda: fake_torch)

        import base64
        import io

        buffer = io.BytesIO(b"fake_data")
        serialized = base64.b64encode(buffer.getvalue()).decode("ascii")

        with pytest.raises(ValueError, match="does not implement the expected posterior"):
            backends_mod._deserialize_torch_object(serialized)

    def test_accepts_object_with_posterior_interface(self, monkeypatch):
        import bayesian_metamodeling.surrogates.backends as backends_mod

        mock_posterior = MagicMock()
        mock_posterior.sample = MagicMock()
        mock_posterior.log_prob = MagicMock()

        fake_torch = MagicMock()
        fake_torch.load.return_value = mock_posterior
        monkeypatch.setattr(backends_mod, "_require_torch", lambda: fake_torch)

        import base64
        import io

        buffer = io.BytesIO(b"fake_data")
        serialized = base64.b64encode(buffer.getvalue()).decode("ascii")

        result = backends_mod._deserialize_torch_object(serialized)
        assert result is mock_posterior
