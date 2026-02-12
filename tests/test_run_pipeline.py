import copy
import json
from pathlib import Path
from uuid import uuid4

import metamodeler.storage.run_store as run_store
from metamodeler.cli.main import main


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_mm_run_and_runs_registry_flow(monkeypatch, capsys, tmp_path):
    registry_path = tmp_path / "run_registry.json"
    monkeypatch.setattr(run_store, "REGISTRY_PATH", registry_path)

    payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    payload = copy.deepcopy(payload)
    payload["design"] = {"strategy": "grid", "grid": {"a": [1.0], "b": [2.0]}}
    payload["storage"] = {"root": f"tmp/pytest_store_{uuid4().hex}"}

    spec_path = tmp_path / "run_spec.json"
    spec_path.write_text(json.dumps(payload))

    monkeypatch.setattr("sys.argv", ["mm", "run", str(spec_path)])
    run_code = main()
    run_out = capsys.readouterr().out

    assert run_code == 0
    assert "Run complete: 1 successful runs" in run_out
    assert registry_path.exists()

    registry = json.loads(registry_path.read_text())
    assert len(registry) == 1
    run_id = next(iter(registry.keys()))

    monkeypatch.setattr("sys.argv", ["mm", "runs", "list"])
    list_code = main()
    list_out = capsys.readouterr().out

    assert list_code == 0
    assert "Registered runs: 1" in list_out
    assert run_id in list_out

    monkeypatch.setattr("sys.argv", ["mm", "runs", "show", run_id])
    show_code = main()
    show_out = capsys.readouterr().out

    assert show_code == 0
    assert run_id in show_out
    assert '"status": "success"' in show_out
