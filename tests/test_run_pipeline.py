import copy
import csv
import json
from pathlib import Path
from uuid import uuid4

import bayesian_metamodeling.storage.run_store as run_store
from bayesian_metamodeling.cli.main import main


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _build_toy_heatmap_grids(
    rows: list[dict[str, str]],
) -> tuple[list[float], list[float], list[list[float]], list[list[float]]]:
    successful = [row for row in rows if row.get("status", "success") == "success"]
    a_values = sorted({float(row["a"]) for row in successful})
    b_values = sorted({float(row["b"]) for row in successful})
    a_index = {value: idx for idx, value in enumerate(a_values)}
    b_index = {value: idx for idx, value in enumerate(b_values)}

    sum_grid = [[float("nan") for _ in b_values] for _ in a_values]
    prod_grid = [[float("nan") for _ in b_values] for _ in a_values]

    for row in successful:
        i = a_index[float(row["a"])]
        j = b_index[float(row["b"])]
        sum_grid[i][j] = float(row["y__0"])
        prod_grid[i][j] = float(row["y__1"])
    return a_values, b_values, sum_grid, prod_grid


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

    run_record = json.loads(Path(registry[run_id]).read_text())
    sweep_rows_path = Path(run_record["sweep_rows_path"])
    assert sweep_rows_path.exists()
    rows = _load_rows(sweep_rows_path)
    assert len(rows) == 1
    assert rows[0]["a"] == "1.0"
    assert rows[0]["b"] == "2.0"
    assert rows[0]["y__0"] == "3.0"
    assert rows[0]["y__1"] == "2.0"


def test_mm_run_parallel_local_matches_serial(monkeypatch, capsys, tmp_path):
    registry_path = tmp_path / "run_registry_parallel.json"
    monkeypatch.setattr(run_store, "REGISTRY_PATH", registry_path)

    base_payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    base_payload = copy.deepcopy(base_payload)
    base_payload["design"] = {"strategy": "grid", "grid": {"a": [0.0, 1.0], "b": [0.0, 1.0]}}

    serial_payload = copy.deepcopy(base_payload)
    serial_payload["storage"] = {"root": f"tmp/pytest_serial_store_{uuid4().hex}"}
    serial_payload["runner"]["sweep_mode"] = "serial"

    serial_spec = tmp_path / "serial_spec.json"
    serial_spec.write_text(json.dumps(serial_payload))
    monkeypatch.setattr("sys.argv", ["mm", "run", str(serial_spec)])
    assert main() == 0
    capsys.readouterr()

    parallel_payload = copy.deepcopy(base_payload)
    parallel_payload["storage"] = {"root": f"tmp/pytest_parallel_store_{uuid4().hex}"}
    parallel_payload["runner"]["sweep_mode"] = "parallel_local"
    parallel_payload["runner"]["workers"] = 2

    parallel_spec = tmp_path / "parallel_spec.json"
    parallel_spec.write_text(json.dumps(parallel_payload))
    monkeypatch.setattr("sys.argv", ["mm", "run", str(parallel_spec)])
    assert main() == 0
    capsys.readouterr()

    registry = json.loads(registry_path.read_text())
    assert len(registry) == 2
    run_records = [json.loads(Path(path).read_text()) for path in registry.values()]

    serial_record = next(item for item in run_records if item["sweep_execution_mode"] == "serial")
    parallel_record = next(
        item for item in run_records if item["sweep_execution_mode"] == "parallel_local"
    )

    serial_rows = _load_rows(Path(serial_record["sweep_rows_path"]))
    parallel_rows = _load_rows(Path(parallel_record["sweep_rows_path"]))

    keep = ["point_index", "a", "b", "y__0", "y__1", "status"]
    serial_norm = [{k: row[k] for k in keep} for row in serial_rows]
    parallel_norm = [{k: row[k] for k in keep} for row in parallel_rows]
    assert serial_norm == parallel_norm

    a_values, b_values, sum_grid, prod_grid = _build_toy_heatmap_grids(serial_rows)
    assert a_values == [0.0, 1.0]
    assert b_values == [0.0, 1.0]
    assert sum_grid == [[0.0, 1.0], [1.0, 2.0]]
    assert prod_grid == [[0.0, 0.0], [0.0, 1.0]]
