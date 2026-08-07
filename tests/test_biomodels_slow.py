"""Slow integration tests for the BioModels adapter.

Two behaviours, split into two tests because only one of them can run everywhere:

- `test_biomodels_adapter_simulate_slow` uses the vendored SBML, so it runs
  anywhere libroadrunner is installed and deterministically covers the part that
  can break silently: SBML parse, simulate, adapter output mapping, sweep row
  flattening.
- `test_biomodels_adapter_fetch_slow` performs the real download. biomodels.org
  returns 403 to GitHub's runner IP ranges while serving ordinary connections
  fine, so this one skips in CI — with an explicit reason — and covers the fetch
  path on a developer machine, which is the only place it can be covered at all.

Keeping them separate matters: folding the fetch into the simulate test made the
download untested *everywhere*, not just in CI.
"""

import copy
import csv
import json
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

import bayesian_metamodeling.storage.run_store as run_store
from bayesian_metamodeling.cli.main import main

SPEC_PATH = Path("examples/biomodels/spec.prompt4.model1907260003.json")
VENDORED_SBML = "examples/biomodels/MODEL1907260003.xml"


def _require_roadrunner() -> None:
    try:
        import roadrunner  # noqa: F401
    except ImportError:
        pytest.skip("libroadrunner is not installed")


@pytest.mark.slow
def test_biomodels_adapter_fetch_slow(tmp_path):
    """The real download, exercised wherever the service will actually serve us.

    Deliberately does NOT go through a sweep — a failed fetch there surfaces as
    "N/N DOE points failed" with the cause buried in sweep_logs.jsonl. Calling
    the adapter directly makes the HTTP failure the test failure.
    """
    _require_roadrunner()

    from bayesian_metamodeling.adapters.biomodels_sbml import BioModelsSBMLAdapter
    from bayesian_metamodeling.spec import ModelSpec

    payload = copy.deepcopy(json.loads(SPEC_PATH.read_text()))
    source_url = payload["model"]["artifact"]["source_url"]

    # Probe first so a blocked network is a clear skip rather than an opaque
    # failure. 403 specifically is what GitHub's runners get.
    try:
        with urllib.request.urlopen(source_url, timeout=30) as resp:
            if resp.status != 200:
                pytest.skip(f"BioModels returned HTTP {resp.status} for {source_url}")
    except urllib.error.HTTPError as exc:
        pytest.skip(
            f"BioModels refused the download (HTTP {exc.code}). Expected on hosted CI: "
            f"biomodels.org blocks cloud IP ranges. The simulate path is covered by "
            f"test_biomodels_adapter_simulate_slow using the vendored SBML."
        )
    except Exception as exc:  # noqa: BLE001 - any transport failure means "cannot fetch"
        pytest.skip(f"BioModels unreachable ({type(exc).__name__}: {exc}) — no network?")

    # No local_sbml_path: force the adapter down the download path.
    payload["model"]["artifact"].pop("local_sbml_path", None)
    spec = ModelSpec.model_validate(payload)

    cache_dir = tmp_path / "_cache" / "biomodels"
    sbml_path = BioModelsSBMLAdapter()._download_if_missing(
        spec=spec, cache_dir=cache_dir, repo_root=Path.cwd()
    )

    assert sbml_path.exists(), "adapter reported success but wrote no file"
    text = sbml_path.read_text(encoding="utf-8", errors="replace")
    # An HTML error page is the classic silent failure here — it downloads fine,
    # caches fine, and then every DOE point dies inside libroadrunner.
    assert "<sbml" in text, f"downloaded file is not SBML (starts: {text[:80]!r})"
    assert payload["model"]["artifact"]["biomodels_id"] in sbml_path.name


@pytest.mark.slow
def test_biomodels_adapter_simulate_slow(monkeypatch, capsys, tmp_path):
    _require_roadrunner()

    registry_path = tmp_path / "run_registry_biomodels.json"
    monkeypatch.setattr(run_store, "REGISTRY_PATH", registry_path)

    payload = copy.deepcopy(json.loads(SPEC_PATH.read_text()))
    payload["storage"] = {"root": f"tmp/pytest_biomodels_store_{uuid4().hex}"}

    # Vendored SBML, so this runs identically everywhere and isolates the
    # simulate pipeline from network availability. The download is covered
    # separately by test_biomodels_adapter_fetch_slow, which skips where the
    # service refuses to serve — keeping them apart is what stops the fetch from
    # becoming untested everywhere.
    payload["model"]["artifact"]["local_sbml_path"] = VENDORED_SBML

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
