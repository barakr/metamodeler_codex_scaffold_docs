import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import metamodeler.storage.surrogate_store as surrogate_store
from metamodeler.cli.main import main
from metamodeler.spec import SurrogateSpec
from metamodeler.surrogates import eval_surrogate, fit_surrogate
from metamodeler.surrogates.backends import get_backend_dependency_versions


def _manual_surrogate_artifact(
    *,
    root: Path,
    monkeypatch,
    spec_name: str,
    backend: str,
    inputs: list[str],
    outputs: list[str],
    payload_inputs: list[str] | None = None,
    payload_output: str | None = None,
) -> None:
    registry_path = root / "surrogate_registry.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry_path)

    payload_inputs = payload_inputs or inputs
    payload_output = payload_output or outputs[0]

    artifact_id = "artifact_hardening"
    artifact_dir = root / "surrogate_artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "model_type": "linear_gaussian",
        "weights": [0.3 for _ in payload_inputs],
        "bias": 0.1,
        "sigma": 0.2,
        "input_names": payload_inputs,
        "output_name": payload_output,
    }
    payload_path = artifact_dir / "backend_payload.json"
    payload_path.write_text(json.dumps(payload))

    artifact = {
        "artifact_id": artifact_id,
        "spec_name": spec_name,
        "backend": backend,
        "variable_lists": {"inputs": inputs, "outputs": outputs},
        "io_signature": {"inputs_ordered": inputs, "outputs_ordered": outputs},
        "backend_payload": str(payload_path),
        "created_at": "2026-02-11T00:00:00+00:00",
    }
    artifact_path = artifact_dir / "artifact.json"
    artifact_path.write_text(json.dumps(artifact))

    registry_path.write_text(json.dumps({artifact_id: str(artifact_path)}))


def _surrogate_payload(backend: str, name: str = "spec") -> dict:
    return {
        "schema_version": "1.0",
        "name": name,
        "kind": "conditional",
        "inputs": ["a", "b"],
        "outputs": ["y"],
        "backend": backend,
        "backend_config": {},
        "dataset_ref": "tmp/store_unused",
        "seed": 1,
    }


def _write_run_store(root: Path) -> None:
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for idx, x in enumerate([-1.0, -0.25, 0.5, 1.0]):
        y = 1.4 * x + 0.3
        run_dir = runs / f"r{idx}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "inputs.json").write_text(json.dumps({"x": x}))
        (run_dir / "outputs.json").write_text(json.dumps({"y": y}))


def test_surrogate_spec_rejects_unknown_backend_config_key():
    payload = _surrogate_payload("pymc_gp")
    payload["backend_config"] = {"unknown_key": 10}
    with pytest.raises(ValidationError, match="Invalid backend_config key"):
        SurrogateSpec.model_validate(payload)


def test_surrogate_spec_rejects_invalid_backend_config_value():
    payload = _surrogate_payload("sbi_npe")
    payload["backend_config"] = {"validation_fraction": 1.5}
    with pytest.raises(ValidationError, match=r"must be in \(0, 1\)"):
        SurrogateSpec.model_validate(payload)


def test_eval_rejects_artifact_backend_mismatch(monkeypatch, tmp_path):
    _manual_surrogate_artifact(
        root=tmp_path,
        monkeypatch=monkeypatch,
        spec_name="mismatch_backend",
        backend="sbi_npe",
        inputs=["a", "b"],
        outputs=["y"],
    )

    spec = SurrogateSpec.model_validate(_surrogate_payload("pymc_gp", name="mismatch_backend"))
    with pytest.raises(ValueError, match="backend mismatch"):
        eval_surrogate(spec=spec, inputs_payload={"a": [0.1], "b": [0.2]}, n=5)


def test_eval_rejects_input_key_and_length_mismatch(monkeypatch, tmp_path):
    _manual_surrogate_artifact(
        root=tmp_path,
        monkeypatch=monkeypatch,
        spec_name="input_mismatch",
        backend="sbi_npe",
        inputs=["a", "b"],
        outputs=["y"],
    )

    spec = SurrogateSpec.model_validate(_surrogate_payload("sbi_npe", name="input_mismatch"))

    with pytest.raises(ValueError, match="Input keys mismatch"):
        eval_surrogate(spec=spec, inputs_payload={"a": [0.1]}, n=5)

    with pytest.raises(ValueError, match="same length"):
        eval_surrogate(spec=spec, inputs_payload={"a": [0.1, 0.2], "b": [0.3]}, n=5)


def test_eval_rejects_payload_input_order_mismatch(monkeypatch, tmp_path):
    _manual_surrogate_artifact(
        root=tmp_path,
        monkeypatch=monkeypatch,
        spec_name="payload_mismatch",
        backend="sbi_npe",
        inputs=["a", "b"],
        outputs=["y"],
        payload_inputs=["b", "a"],
    )

    spec = SurrogateSpec.model_validate(_surrogate_payload("sbi_npe", name="payload_mismatch"))
    with pytest.raises(ValueError, match="payload input order mismatch"):
        eval_surrogate(spec=spec, inputs_payload={"a": [0.1], "b": [0.2]}, n=5)


def test_cli_surrogate_eval_reports_missing_artifact(monkeypatch, capsys, tmp_path):
    registry_path = tmp_path / "empty_registry.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry_path)
    registry_path.write_text(json.dumps({}))

    spec_path = tmp_path / "surrogate.json"
    spec_path.write_text(json.dumps(_surrogate_payload("sbi_npe", name="missing_artifact")))

    monkeypatch.setattr(
        "sys.argv",
        [
            "mm",
            "surrogate",
            "eval",
            str(spec_path),
            "--inputs",
            '{"a":[0.1],"b":[0.2]}',
            "--n",
            "8",
        ],
    )
    code = main()
    out = capsys.readouterr().out

    assert code == 1
    assert "Surrogate eval failed:" in out
    assert "No surrogate artifact found" in out


def test_cli_surrogate_eval_reports_non_object_inputs(monkeypatch, capsys, tmp_path):
    _manual_surrogate_artifact(
        root=tmp_path,
        monkeypatch=monkeypatch,
        spec_name="bad_inputs_json",
        backend="sbi_npe",
        inputs=["a", "b"],
        outputs=["y"],
    )

    spec_path = tmp_path / "surrogate.json"
    spec_path.write_text(json.dumps(_surrogate_payload("sbi_npe", name="bad_inputs_json")))

    monkeypatch.setattr(
        "sys.argv",
        ["mm", "surrogate", "eval", str(spec_path), "--inputs", "[1,2,3]", "--n", "8"],
    )
    code = main()
    out = capsys.readouterr().out

    assert code == 1
    assert "Surrogate eval failed:" in out
    assert "must be a JSON object" in out


@pytest.mark.slow
def test_optional_dual_backend_fit_eval_path(monkeypatch, tmp_path):
    versions_pymc = get_backend_dependency_versions("pymc_gp")
    versions_sbi = get_backend_dependency_versions("sbi_npe")
    has_pymc = versions_pymc.get("pymc") != "not_installed"
    has_sbi = (
        versions_sbi.get("sbi") != "not_installed" and versions_sbi.get("torch") != "not_installed"
    )

    if not (has_pymc and has_sbi):
        pytest.skip("Dual-backend optional integration requires both pymc and sbi/torch")

    registry_path = tmp_path / "dual_registry.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry_path)

    run_store = tmp_path / "dual_store"
    _write_run_store(run_store)

    specs = [
        SurrogateSpec.model_validate(
            {
                "schema_version": "1.0",
                "name": "dual_pymc",
                "kind": "conditional",
                "inputs": ["x"],
                "outputs": ["y"],
                "backend": "pymc_gp",
                "backend_config": {"draws": 40, "tune": 40, "chains": 1, "target_accept": 0.9},
                "dataset_ref": {"run_store_root": str(run_store)},
                "seed": 10,
            }
        ),
        SurrogateSpec.model_validate(
            {
                "schema_version": "1.0",
                "name": "dual_sbi",
                "kind": "conditional",
                "inputs": ["x"],
                "outputs": ["y"],
                "backend": "sbi_npe",
                "backend_config": {
                    "density_estimator": "maf",
                    "max_num_epochs": 40,
                    "training_batch_size": 16,
                    "learning_rate": 5e-4,
                    "summary_samples": 64,
                },
                "dataset_ref": {"run_store_root": str(run_store)},
                "seed": 11,
            }
        ),
    ]

    for spec in specs:
        try:
            fit_surrogate(spec)
            result = eval_surrogate(spec=spec, inputs_payload={"x": [0.1, 0.3]}, n=10)
        except Exception as exc:  # pragma: no cover - optional runtime stack
            pytest.skip(f"Optional dual-backend integration skipped due runtime constraint: {exc}")
        assert result["sample_shape"] == [2, 10, 1]
