import json
from pathlib import Path

import metamodeler.storage.surrogate_store as surrogate_store
from metamodeler.cli.main import main
from metamodeler.spec import SurrogateSpec
from metamodeler.surrogates import fit_surrogate


def _write_store(root: Path, scale: float) -> None:
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for idx, x in enumerate([-1.0, -0.5, 0.0, 0.5, 1.0]):
        y = scale * x + 0.2
        run_dir = runs / f"r{idx}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "inputs.json").write_text(json.dumps({"x": x}))
        (run_dir / "outputs.json").write_text(json.dumps({"y": y}))


def _surrogate_spec(name: str, store: Path) -> SurrogateSpec:
    return SurrogateSpec.model_validate(
        {
            "schema_version": "1.0",
            "name": name,
            "kind": "conditional",
            "inputs": ["x"],
            "outputs": ["y"],
            "backend": "sbi_npe",
            "backend_config": {},
            "dataset_ref": {"run_store_root": str(store)},
            "seed": 7,
        }
    )


def test_meta_build_and_sample_with_two_surrogates(monkeypatch, capsys, tmp_path):
    registry_path = tmp_path / "surrogate_registry.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry_path)

    store_a = tmp_path / "store_a"
    store_b = tmp_path / "store_b"
    _write_store(store_a, scale=1.0)
    _write_store(store_b, scale=2.0)

    artifact_a = fit_surrogate(_surrogate_spec("sA", store_a))
    artifact_b = fit_surrogate(_surrogate_spec("sB", store_b))

    meta_spec = {
        "schema_version": "1.0",
        "name": "meta_two_surrogates",
        "ppl_backend": "pymc",
        "surrogate_refs": [artifact_a["artifact_path"], artifact_b["artifact_path"]],
        "variables": [
            {"name": "x", "type": "scalar"},
            {"name": "y", "type": "scalar"},
            {"name": "C", "type": "scalar"},
        ],
        "couplings": [
            {
                "kind": "gaussian_link",
                "source": "y",
                "target": "C",
                "transform": {"kind": "identity"},
                "sigma": 0.1,
            }
        ],
        "priors": [{"variable": "x", "distribution": {"kind": "normal", "loc": 0.0, "scale": 1.0}}],
    }

    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(meta_spec))

    monkeypatch.setattr("sys.argv", ["mm", "meta", "build", str(meta_path)])
    build_code = main()
    build_out = capsys.readouterr().out
    assert build_code == 0
    assert "Metamodel IR artifact stored:" in build_out

    monkeypatch.setattr(
        "sys.argv",
        [
            "mm",
            "meta",
            "sample",
            str(meta_path),
            "--draws",
            "20",
            "--tune",
            "5",
            "--chains",
            "2",
            "--seed",
            "13",
        ],
    )
    sample_code = main()
    sample_out = capsys.readouterr().out

    assert sample_code == 0
    assert "Metamodel sample stored:" in sample_out
    assert Path("tmp/metamodel_samples_registry.json").exists()
