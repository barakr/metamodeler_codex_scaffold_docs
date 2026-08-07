"""Slow integration tests for the BioModels adapter.

These tests validate two behaviors:
- fetching a BioModels model by identifier
- simulating the fetched model and persisting outputs

They are marked `slow` because model fetch/simulate can take time and may
require network access.
"""

import copy
import csv
import json
from pathlib import Path
from uuid import uuid4

import pytest

import bayesian_metamodeling.storage.run_store as run_store
from bayesian_metamodeling.cli.main import main


@pytest.mark.slow
def test_biomodels_adapter_fetch_and_simulate_slow(monkeypatch, capsys, tmp_path):
    try:
        import roadrunner  # noqa: F401
    except ImportError:
        pytest.skip("libroadrunner is not installed")

    registry_path = tmp_path / "run_registry_biomodels.json"
    monkeypatch.setattr(run_store, "REGISTRY_PATH", registry_path)

    spec_path = Path("examples/biomodels/spec.prompt4.model1907260003.json")
    payload = json.loads(spec_path.read_text())
    payload = copy.deepcopy(payload)
    payload["storage"] = {"root": f"tmp/pytest_biomodels_store_{uuid4().hex}"}

    # Use the vendored SBML rather than fetching. biomodels.org returns 403 to
    # GitHub's runner IPs (it works from a normal connection), so a fetching test
    # is red in CI forever — and the alternative, letting it skip, is the same
    # green-by-skipping this suite exists to prevent. The fetch path itself
    # therefore cannot be CI-verified by anything here; what this test does verify
    # is the part that can break silently: SBML parse, simulate, adapter output
    # mapping and sweep row flattening.
    payload["model"]["artifact"]["local_sbml_path"] = "examples/biomodels/MODEL1907260003.xml"

    temp_spec = tmp_path / "biomodels_spec.json"
    temp_spec.write_text(json.dumps(payload))

    monkeypatch.setattr("sys.argv", ["mm", "run", str(temp_spec)])
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Run complete: 1 successful runs" in out
    assert registry_path.exists()

    registry = json.loads(registry_path.read_text())
    run_id = next(iter(registry.keys()))
    record = json.loads(Path(registry[run_id]).read_text())

    sweep_rows_path = Path(record["sweep_rows_path"])
    with sweep_rows_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["status"] == "success"
    row = rows[0]

    # The timeseries is flattened per-key by `flatten_outputs_for_row`, not stored
    # as one `time_series__json` blob. `_flatten_nested` only emits a whole-payload
    # column when some member could not be flattened at all; here every member can
    # be, so the data lands in `time_series__{n_points,t0,t1,columns__N,rows__json}`.
    #
    # This assertion previously looked for `time_series__json` and had therefore
    # never passed: the test needs libroadrunner (installed in no environment until
    # now) and is marked `slow`, so it was excluded from every CI run. Asserting on
    # the real schema, and on the values, so it fails if the sweep goes hollow
    # rather than merely if a column is renamed.
    assert int(row["time_series__n_points"]) > 1, "timeseries has no samples"
    assert float(row["time_series__t1"]) > float(row["time_series__t0"]), "empty time span"

    columns = [row[k] for k in sorted(row) if k.startswith("time_series__columns__")]
    assert "time" in columns, f"no time column in {columns}"

    series = json.loads(row["time_series__rows__json"])
    assert len(series) == int(row["time_series__n_points"])
    assert set(series[0]) == set(columns), "row keys disagree with declared columns"
    # A simulation that silently produced nothing would still be uniformly zero.
    assert any(v != 0.0 for k, v in series[0].items() if k != "time"), (
        "every species is zero at t0 — the SBML simulated but produced no state"
    )
