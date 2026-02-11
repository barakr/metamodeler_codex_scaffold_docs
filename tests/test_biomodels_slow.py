import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest

import metamodeler.storage.run_store as run_store
from metamodeler.cli.main import main


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

    outputs_path = Path(record["outputs_path"])
    outputs = json.loads(outputs_path.read_text())
    assert "time_series" in outputs
    assert "rows" in outputs["time_series"]
