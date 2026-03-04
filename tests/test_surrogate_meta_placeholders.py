import copy
import json
from pathlib import Path

import bayesian_metamodeling.storage.surrogate_store as surrogate_store
from bayesian_metamodeling.cli.main import main
from tests.backend_support import available_fit_backend


def _write_tiny_run_store(root: Path) -> None:
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for idx, (a, b) in enumerate([(0.0, 0.0), (1.0, 2.0), (2.0, 1.0), (3.0, 1.0)]):
        run_dir = runs / f"r{idx}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "inputs.json").write_text(json.dumps({"a": a, "b": b}))
        (run_dir / "outputs.json").write_text(json.dumps({"y": a + b}))


def _surrogate_spec_payload(
    run_store_root: Path, *, backend: str | None = None, backend_config: dict | None = None
) -> dict:
    if backend is None:
        backend, backend_config = available_fit_backend()
    cfg = backend_config or {}
    return {
        "schema_version": "1.0",
        "name": "tiny_cli_surrogate",
        "kind": "conditional",
        "inputs": ["a", "b"],
        "outputs": ["y"],
        "backend": backend,
        "backend_config": cfg,
        "dataset_ref": {"run_store_root": str(run_store_root)},
        "seed": 11,
    }


def test_mm_surrogate_fit_and_eval_cli(monkeypatch, capsys, tmp_path):
    registry = tmp_path / "surrogate_registry.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry)

    run_store = tmp_path / "store"
    _write_tiny_run_store(run_store)

    spec_path = tmp_path / "surrogate.json"
    spec_path.write_text(json.dumps(_surrogate_spec_payload(run_store)))

    monkeypatch.setattr("sys.argv", ["mm", "surrogate", "fit", str(spec_path)])
    fit_code = main()
    fit_out = capsys.readouterr().out
    assert fit_code == 0
    assert "Surrogate artifact stored:" in fit_out
    assert registry.exists()

    eval_inputs = json.dumps({"a": [0.5, 1.5], "b": [0.5, 1.0]})
    monkeypatch.setattr(
        "sys.argv",
        ["mm", "surrogate", "eval", str(spec_path), "--inputs", eval_inputs, "--n", "16"],
    )
    eval_code = main()
    eval_out = capsys.readouterr().out
    assert eval_code == 0
    assert '"sample_shape": [' in eval_out


def test_mm_meta_build_placeholder(monkeypatch, capsys):
    spec_path = Path("examples/coupled/spec.three_model_coupling.json")

    monkeypatch.setattr("sys.argv", ["mm", "meta", "build", str(spec_path)])
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Metamodel IR artifact stored:" in out


def test_mm_surrogate_fit_invalid_spec_fails(monkeypatch, capsys, tmp_path):
    payload = _surrogate_spec_payload(tmp_path / "store", backend="sbi_npe", backend_config={})
    bad_payload = copy.deepcopy(payload)
    del bad_payload["name"]

    bad_path = tmp_path / "bad_surrogate.json"
    bad_path.write_text(json.dumps(bad_payload))

    monkeypatch.setattr("sys.argv", ["mm", "surrogate", "fit", str(bad_path)])
    code = main()
    out = capsys.readouterr().out

    assert code == 1
    assert "Spec validation failed:" in out
