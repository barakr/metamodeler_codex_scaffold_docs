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
        y = scale * x + 0.1
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
            "backend": "pymc_gp",
            "backend_config": {},
            "dataset_ref": {"run_store_root": str(store)},
            "seed": 9,
        }
    )


def test_meta_sample_numpyro_backend(monkeypatch, capsys, tmp_path):
    registry_path = tmp_path / "surrogate_registry_np.json"
    monkeypatch.setattr(surrogate_store, "SURROGATE_REGISTRY_PATH", registry_path)

    store_a = tmp_path / "store_a"
    store_b = tmp_path / "store_b"
    _write_store(store_a, scale=1.0)
    _write_store(store_b, scale=1.3)

    artifact_a = fit_surrogate(_surrogate_spec("np_sA", store_a))
    artifact_b = fit_surrogate(_surrogate_spec("np_sB", store_b))

    spec = {
        "schema_version": "1.0",
        "name": "meta_numpyro",
        "ppl_backend": "numpyro",
        "surrogate_refs": [artifact_a["artifact_path"], artifact_b["artifact_path"]],
        "variables": [{"name": "x", "type": "scalar"}, {"name": "y", "type": "scalar"}],
        "couplings": [
            {
                "kind": "equality_soft",
                "source": "x",
                "target": "y",
                "transform": {"kind": "identity"},
                "sigma": 0.2,
            }
        ],
        "priors": [{"variable": "x", "distribution": {"kind": "normal", "loc": 0.0, "scale": 1.0}}],
    }

    spec_path = tmp_path / "meta_numpyro.json"
    spec_path.write_text(json.dumps(spec))

    monkeypatch.setattr(
        "sys.argv",
        [
            "mm",
            "meta",
            "sample",
            str(spec_path),
            "--draws",
            "10",
            "--tune",
            "5",
            "--chains",
            "2",
            "--seed",
            "5",
        ],
    )
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Metamodel sample stored:" in out
    registry = json.loads(Path("tmp/metamodel_samples_registry.json").read_text())
    assert any(entry["backend"] == "numpyro" for entry in registry.values())
