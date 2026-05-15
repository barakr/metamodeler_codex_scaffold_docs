"""Static check: adapter materializations don't yield ``["python", ...]``.

Belt-and-suspenders for the subprocess-env-leakage bug fixed in
`runners/local_process.py` + `adapters/biomodels_sbml.py`. Even with the
runner's substitution, an adapter that yields bare ``"python"`` is a
documentation/clarity bug — the intent at the source should be explicit.
This test catches future adapters that re-introduce the anti-pattern.

See `Status.md` "False success metric in tutorial verification" post-mortem.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bayesian_metamodeling.adapters.biomodels_sbml import BioModelsSBMLAdapter
from bayesian_metamodeling.adapters.python_cli import PythonCLIAdapter
from bayesian_metamodeling.spec import load_and_validate_modelspec


def _toy_python_cli_payload() -> dict:
    return {
        "schema_version": "1.0",
        "model": {
            "name": "toy",
            "version": "1.0",
            "artifact": {
                "type": "local",
                "entrypoint": ["python", "examples/toy_program/run.py"],
            },
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
            "input_mapping": [{"var": "a", "to": {"kind": "cli_flag", "key": "--a"}}],
            "output_mapping": [{"var": "y", "from": {"kind": "file", "path": "out/y.json"}}],
        },
        "reproducibility": {"seed": 0},
        "storage": {"root": "tmp/test"},
    }


def _toy_biomodels_payload() -> dict:
    return {
        "schema_version": "1.0",
        "model": {
            "name": "toy-bm",
            "version": "1.0",
            "artifact": {
                "type": "biomodels",
                "biomodels_id": "TEST00001",
                # Use a local SBML so the adapter doesn't try to download.
                "local_sbml_path": "tests/fixtures/sample.xml",
            },
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
            "input_mapping": [{"var": "k_on", "to": {"kind": "sbml_parameter", "key": "k_on"}}],
            "output_mapping": [{"var": "y", "from": {"kind": "generated", "key": "timeseries"}}],
        },
        "reproducibility": {"seed": 0},
        "storage": {"root": "tmp/test_bm"},
    }


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_biomodels_adapter_yields_sys_executable_not_bare_python(tmp_path, monkeypatch):
    """BioModels adapter must build commands rooted at sys.executable, not "python".

    Spec the bug at the SOURCE: even before the runner's defensive substitution,
    the adapter's intent should be explicit. Storing a fake SBML in the cache
    avoids any network call.
    """
    payload = _toy_biomodels_payload()
    # Drop the local_sbml_path (which would copy from disk); pre-populate the
    # cache directly so the adapter finds an existing file with no copy needed.
    payload["model"]["artifact"].pop("local_sbml_path", None)
    spec = load_and_validate_modelspec(payload)
    adapter = BioModelsSBMLAdapter()

    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / "tmp/test_bm/_cache/biomodels"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "TEST00001.xml").write_text("<sbml/>")

    mat = adapter.materialize_inputs(
        spec=spec,
        point={"k_on": 1.0e-4},
        run_dir=tmp_path / "run",
        repo_root=REPO_ROOT,
    )
    assert mat.command[0] == sys.executable, (
        f"BioModels adapter must use sys.executable, got {mat.command[0]!r}. "
        "Bare 'python' resolves via PATH (typically base conda) and silently "
        "breaks workers when the kernel env has libroadrunner but PATH-python "
        "doesn't. See runners/local_process.py and Status.md."
    )


def test_python_cli_adapter_command_is_user_controlled(tmp_path):
    """python_cli adapter passes through `entrypoint` from the spec verbatim.

    The spec author OWNS the entrypoint (this is a CLI-first tool where the
    user writes the spec). When the entrypoint starts with bare "python", the
    runner's substitution covers them — the adapter doesn't second-guess.

    This test pins the contract: python_cli does NOT mutate command[0].
    Future "smart" rewrites would break specs that intentionally use a
    different python (e.g., a project-specific virtualenv binary).
    """
    spec = load_and_validate_modelspec(_toy_python_cli_payload())
    adapter = PythonCLIAdapter()
    mat = adapter.materialize_inputs(
        spec=spec,
        point={"a": 1.0},
        run_dir=tmp_path / "run",
        repo_root=REPO_ROOT,
    )
    # Spec said `["python", "examples/toy_program/run.py"]`; adapter passes
    # it through unchanged (the runner handles the substitution).
    assert mat.command[0] == "python"
    assert mat.command[1].endswith("toy_program/run.py")
