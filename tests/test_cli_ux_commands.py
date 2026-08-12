import json
from pathlib import Path
from unittest.mock import patch

import pytest

import bayesian_metamodeling.storage.surrogate_store as surrogate_store
from bayesian_metamodeling.cli.main import main
from bayesian_metamodeling.execution import execute_design_point
from bayesian_metamodeling.spec import SurrogateSpec
from bayesian_metamodeling.surrogates import fit_surrogate
from tests.backend_support import available_fit_backend


def _write_store(root: Path) -> None:
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for i, x in enumerate([0.0, 1.0, 2.0]):
        run = runs / f"r{i}"
        run.mkdir(parents=True, exist_ok=True)
        (run / "inputs.json").write_text(json.dumps({"a": x, "b": x + 1.0}))
        (run / "outputs.json").write_text(json.dumps({"y": x + (x + 1.0)}))


def _spec(store: Path) -> SurrogateSpec:
    backend, backend_config = available_fit_backend()
    return SurrogateSpec.model_validate(
        {
            "schema_version": "1.0",
            "name": "ux_spec",
            "kind": "conditional",
            "inputs": ["a", "b"],
            "outputs": ["y"],
            "backend": backend,
            "backend_config": backend_config,
            "dataset_ref": {"run_store_root": str(store)},
            "seed": 1,
        }
    )


def test_mm_tutorial_prints_guided_flow(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["mm", "tutorial"])
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Bayesian Metamodeling tutorial flow:" in out
    assert "bayesmm validate" in out


def test_mm_surrogate_list_and_meta_list(monkeypatch, capsys, tmp_path):
    registry_path = tmp_path / "ux_surrogate_registry.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry_path)

    store = tmp_path / "store"
    _write_store(store)
    artifact = fit_surrogate(_spec(store))

    monkeypatch.setattr("sys.argv", ["mm", "surrogate", "list"])
    code_s = main()
    out_s = capsys.readouterr().out
    assert code_s == 0
    assert "Surrogate artifacts:" in out_s
    assert artifact["artifact_id"] in out_s

    monkeypatch.setattr("sys.argv", ["mm", "meta", "list"])
    code_m = main()
    out_m = capsys.readouterr().out
    assert code_m == 0
    assert "Metamodel IR artifacts:" in out_m


def test_artifact_metadata_contains_repro_fields(monkeypatch, tmp_path):
    registry_path = tmp_path / "ux_registry_meta.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry_path)

    store = tmp_path / "store_meta"
    _write_store(store)
    artifact = fit_surrogate(_spec(store))

    payload = json.loads(Path(artifact["artifact_path"]).read_text())
    assert "spec_digest" in payload
    assert "dataset_digest" in payload
    assert "dependency_versions" in payload
    assert "seed" in payload


def _make_test_spec():
    from bayesian_metamodeling.spec import load_and_validate_modelspec

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
            "storage": {"root": "tmp/test_store"},
        }
    )


def test_specific_exceptions_caught_in_execute_design_point():
    """Specific exception types (ValueError, FileNotFoundError, etc.) are caught
    and recorded as failed runs rather than crashing."""
    spec = _make_test_spec()

    class _FailAdapter:
        def materialize_inputs(self, **kw):
            raise ValueError("bad input")

    with patch(
        "bayesian_metamodeling.execution.sweep.resolve_adapter",
        return_value=_FailAdapter(),
    ):
        result = execute_design_point(
            spec=spec,
            point_index=0,
            point={"a": 1.0},
            run_token="test",
        )
    assert result["status"] == "failed"
    assert "bad input" in result["error"]


def test_unexpected_exceptions_propagate_from_execute_design_point():
    """Unexpected exception types (e.g. RuntimeError) propagate rather than
    being silently caught."""
    spec = _make_test_spec()

    class _FailAdapter:
        def materialize_inputs(self, **kw):
            raise RuntimeError("unexpected")

    with patch(
        "bayesian_metamodeling.execution.sweep.resolve_adapter",
        return_value=_FailAdapter(),
    ):
        with pytest.raises(RuntimeError, match="unexpected"):
            execute_design_point(
                spec=spec,
                point_index=0,
                point={"a": 1.0},
                run_token="test",
            )
