"""Regression tests for the BioModels adapter's offline-mode behavior.

These cover three orthogonal contracts:

1. `MM_BIOMODELS_OFFLINE=1` blocks any HTTP attempt and returns an actionable
   `RuntimeError` mentioning the missing cache path and a `curl` recipe.
2. With `MM_BIOMODELS_OFFLINE=1` set but the cache pre-populated, materialize
   succeeds without any network call.
3. With `model.artifact.local_sbml_path` set on the spec, the adapter copies
   the local file into the cache instead of downloading — independent of the
   offline env var.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bayesian_metamodeling.adapters.biomodels_sbml import BioModelsSBMLAdapter
from bayesian_metamodeling.spec import load_and_validate_modelspec


def _spec_payload(storage_root: str, *, local_sbml_path: str | None = None) -> dict:
    artifact: dict = {"type": "biomodels", "biomodels_id": "TESTMODEL00001"}
    if local_sbml_path is not None:
        artifact["local_sbml_path"] = local_sbml_path
    return {
        "schema_version": "1.0",
        "model": {
            "name": "biomodels-offline-test",
            "version": "1.0",
            "artifact": artifact,
        },
        "runner": {
            "mode": "local_process",
            "resources": {"cpus": 1, "mem_gb": 1, "walltime_min": 1},
        },
        "io_schema": {
            "inputs": [{"name": "k_on", "type": "float", "units": "1/s"}],
            "outputs": [{"name": "y", "type": "array", "units": "M", "dims": ["time"]}],
        },
        "design": {"strategy": "grid", "grid": {"k_on": [1.0e-4]}},
        "adapter": {
            "id": "biomodels_sbml_adapter_v1",
            "input_mapping": [
                {
                    "var": "k_on",
                    "to": {"kind": "sbml_parameter", "key": "k_on"},
                }
            ],
            "output_mapping": [
                {
                    "var": "y",
                    "from": {"kind": "generated", "key": "timeseries"},
                }
            ],
        },
        "reproducibility": {"seed": 0},
        "storage": {"root": storage_root},
    }


def _no_network(*_args, **_kwargs):
    raise AssertionError(
        "requests.get should not be called when offline mode or local_sbml_path is in use"
    )


def test_offline_env_var_blocks_download(monkeypatch, tmp_path):
    """`MM_BIOMODELS_OFFLINE=1` and no cache => actionable RuntimeError, no HTTP."""
    monkeypatch.setenv("MM_BIOMODELS_OFFLINE", "1")
    monkeypatch.setattr("bayesian_metamodeling.adapters.biomodels_sbml.requests.get", _no_network)
    storage_root = "tmp/biomodels_offline_test"
    spec = load_and_validate_modelspec(_spec_payload(storage_root))
    monkeypatch.chdir(tmp_path)
    adapter = BioModelsSBMLAdapter()

    with pytest.raises(RuntimeError) as excinfo:
        adapter.materialize_inputs(
            spec=spec,
            point={"k_on": 1.0e-4},
            run_dir=tmp_path / "run",
            repo_root=tmp_path,
        )
    msg = str(excinfo.value)
    # Must mention the env var name and the missing cache path so users can act.
    assert "MM_BIOMODELS_OFFLINE" in msg
    assert "TESTMODEL00001.xml" in msg
    assert "curl" in msg.lower()


def test_offline_uses_existing_cache(monkeypatch, tmp_path):
    """`MM_BIOMODELS_OFFLINE=1` with the cache pre-populated => succeeds, no HTTP."""
    monkeypatch.setenv("MM_BIOMODELS_OFFLINE", "1")
    monkeypatch.setattr("bayesian_metamodeling.adapters.biomodels_sbml.requests.get", _no_network)
    monkeypatch.chdir(tmp_path)

    storage_root = "tmp/biomodels_offline_test_cached"
    cache_dir = Path(storage_root) / "_cache" / "biomodels"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_path = cache_dir / "TESTMODEL00001.xml"
    cached_path.write_text("<sbml>fake-cached</sbml>")

    spec = load_and_validate_modelspec(_spec_payload(storage_root))
    adapter = BioModelsSBMLAdapter()
    mat = adapter.materialize_inputs(
        spec=spec,
        point={"k_on": 1.0e-4},
        run_dir=tmp_path / "run",
        repo_root=tmp_path,
    )
    # The materialize-inputs command should reference the cached SBML path.
    sbml_arg = mat.command[mat.command.index("--sbml-path") + 1]
    assert Path(sbml_arg).resolve() == cached_path.resolve()


def test_local_sbml_path_seeds_cache(monkeypatch, tmp_path):
    """`local_sbml_path` set => adapter copies into cache, no HTTP, no env var needed."""
    # Explicitly NOT setting MM_BIOMODELS_OFFLINE — local_sbml_path is enough.
    monkeypatch.delenv("MM_BIOMODELS_OFFLINE", raising=False)
    monkeypatch.setattr("bayesian_metamodeling.adapters.biomodels_sbml.requests.get", _no_network)
    monkeypatch.chdir(tmp_path)

    sample_sbml = tmp_path / "samples" / "fake.xml"
    sample_sbml.parent.mkdir(parents=True, exist_ok=True)
    sample_sbml.write_text("<sbml>shipped-with-tutorial</sbml>")

    storage_root = "tmp/biomodels_local_path_test"
    spec = load_and_validate_modelspec(
        _spec_payload(storage_root, local_sbml_path="samples/fake.xml")
    )
    adapter = BioModelsSBMLAdapter()
    mat = adapter.materialize_inputs(
        spec=spec,
        point={"k_on": 1.0e-4},
        run_dir=tmp_path / "run",
        repo_root=tmp_path,
    )

    cached_path = tmp_path / storage_root / "_cache" / "biomodels" / "TESTMODEL00001.xml"
    assert cached_path.exists()
    assert cached_path.read_text() == "<sbml>shipped-with-tutorial</sbml>"
    sbml_arg = mat.command[mat.command.index("--sbml-path") + 1]
    assert Path(sbml_arg).resolve() == cached_path.resolve()


def test_local_sbml_path_missing_file_errors(monkeypatch, tmp_path):
    """`local_sbml_path` pointing at a non-existent file => clear FileNotFoundError."""
    monkeypatch.delenv("MM_BIOMODELS_OFFLINE", raising=False)
    monkeypatch.setattr("bayesian_metamodeling.adapters.biomodels_sbml.requests.get", _no_network)
    monkeypatch.chdir(tmp_path)

    storage_root = "tmp/biomodels_missing_local_test"
    spec = load_and_validate_modelspec(
        _spec_payload(storage_root, local_sbml_path="does/not/exist.xml")
    )
    adapter = BioModelsSBMLAdapter()
    with pytest.raises(FileNotFoundError, match="local_sbml_path"):
        adapter.materialize_inputs(
            spec=spec,
            point={"k_on": 1.0e-4},
            run_dir=tmp_path / "run",
            repo_root=tmp_path,
        )


# Sanity check — the existing example spec without local_sbml_path still validates.
def test_example_spec_without_local_sbml_path_validates():
    payload = json.loads(Path("examples/biomodels/spec.model1907260003.json").read_text())
    spec = load_and_validate_modelspec(payload)
    assert spec.model.artifact.local_sbml_path is None
