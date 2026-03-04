import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bayesian_metamodeling.cli.main import main
from bayesian_metamodeling.spec import load_and_validate_modelspec


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_load_and_validate_modelspec_accepts_toy_example():
    spec_path = Path("examples/toy_program/spec.toy_program.json")
    payload = _read_json(spec_path)

    spec = load_and_validate_modelspec(payload)

    assert spec.model.name == "toy_program"
    assert spec.design.strategy == "grid"
    assert spec.reproducibility.seed == 123


def test_load_and_validate_modelspec_rejects_missing_grid_for_grid_strategy():
    spec_path = Path("examples/toy_program/spec.toy_program.json")
    payload = _read_json(spec_path)
    payload["design"] = {"strategy": "grid"}

    try:
        load_and_validate_modelspec(payload)
    except ValidationError as exc:
        message = str(exc)
        assert "design.grid" in message or "design" in message
    else:
        raise AssertionError("validation should have failed")


def test_mm_validate_reports_actionable_error_for_invalid_spec(monkeypatch, capsys, tmp_path):
    invalid_spec = {
        "schema_version": "1.0",
        "model": {
            "name": "x",
            "version": "0.1.0",
            "artifact": {"type": "local"},
        },
        "runner": {
            "mode": "local_process",
            "resources": {"cpus": 1, "mem_gb": 1, "walltime_min": 1},
        },
        "io_schema": {
            "inputs": [{"name": "a", "type": "float", "units": "u", "support": [1.0, 0.0]}],
            "outputs": [{"name": "y", "type": "array", "dims": ["i"], "units": "u"}],
        },
        "design": {"strategy": "grid", "grid": {"a": [0.0, 1.0]}},
        "adapter": {"id": "adapter", "input_mapping": [], "output_mapping": []},
        "reproducibility": {"seed": 1},
        "storage": {"root": "store"},
    }
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid_spec))

    monkeypatch.setattr("sys.argv", ["mm", "validate", str(path)])
    code = main()
    out = capsys.readouterr().out

    assert code == 1
    assert "Spec validation failed:" in out
    assert "model.artifact" in out or "io_schema.inputs.0.support" in out


def test_mm_validate_passes_for_toy_spec(monkeypatch, capsys):
    spec_path = Path("examples/toy_program/spec.toy_program.json")

    monkeypatch.setattr("sys.argv", ["mm", "validate", str(spec_path)])
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Spec validation passed:" in out


def test_modelspec_schema_artifact_exists():
    schema_path = Path("src/bayesian_metamodeling/spec/modelspec.schema.json")
    payload = json.loads(schema_path.read_text())

    assert payload["title"] == "ModelSpec"
    assert "$defs" in payload
    runner_props = payload["$defs"]["RunnerSpec"]["properties"]
    assert "sweep_mode" in runner_props
    assert "workers" in runner_props


def test_runner_execution_env_defaults_to_empty():
    payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    spec = load_and_validate_modelspec(payload)
    assert spec.runner.execution_env == {}


def test_runner_execution_env_rejects_unsupported_keys():
    payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    payload["runner"]["execution_env"] = {"python_path": "python", "conda_env": "x"}
    with pytest.raises(ValidationError, match="unsupported keys"):
        load_and_validate_modelspec(payload)


def test_runner_execution_env_normalizes_conda_env_whitespace():
    payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    payload["runner"]["execution_env"] = {"conda_env": "  py312_metamodeling_pymc  "}
    spec = load_and_validate_modelspec(payload)
    assert spec.runner.execution_env["conda_env"] == "py312_metamodeling_pymc"


def test_runner_sweep_mode_defaults_to_serial():
    payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    spec = load_and_validate_modelspec(payload)
    assert spec.runner.sweep_mode == "serial"


def test_runner_parallel_local_autofills_workers_from_cpus():
    payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    payload["runner"]["resources"]["cpus"] = 3
    payload["runner"]["sweep_mode"] = "parallel_local"
    spec = load_and_validate_modelspec(payload)
    assert spec.runner.workers == 3


def test_runner_workers_rejected_for_non_parallel_mode():
    payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    payload["runner"]["sweep_mode"] = "serial"
    payload["runner"]["workers"] = 2
    with pytest.raises(ValidationError, match="runner.workers is supported only"):
        load_and_validate_modelspec(payload)
