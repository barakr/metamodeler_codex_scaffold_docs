import csv
import json

from metamodeler.storage.sweep_store import flatten_outputs_for_row, write_sweep_rows_csv


def test_flatten_outputs_for_row_unwraps_toy_envelope():
    outputs = {"y": {"inputs": {"a": 1.0, "b": 2.0}, "y": [3.0, 2.0]}}
    flat = flatten_outputs_for_row(outputs)
    assert flat["y__0"] == 3.0
    assert flat["y__1"] == 2.0


def test_flatten_outputs_for_row_keeps_nested_payload_as_json():
    outputs = {"time_series": {"rows": [[0.0, 1.0]], "columns": ["time", "A"]}}
    flat = flatten_outputs_for_row(outputs)
    assert "time_series__rows__json" in flat
    parsed_rows = json.loads(flat["time_series__rows__json"])
    assert parsed_rows[0][1] == 1.0


def test_write_sweep_rows_csv_sorts_by_point_index(tmp_path):
    path = tmp_path / "sweep_rows.csv"
    rows = [
        {"point_index": 2, "a": 2.0, "b": 1.0, "y__0": 3.0, "status": "success"},
        {"point_index": 0, "a": 0.0, "b": 0.0, "y__0": 0.0, "status": "success"},
        {"point_index": 1, "a": 1.0, "b": 1.0, "y__0": 2.0, "status": "success"},
    ]
    write_sweep_rows_csv(rows, path=path, input_names=["a", "b"])

    with path.open(newline="", encoding="utf-8") as handle:
        loaded = list(csv.DictReader(handle))
    assert [int(item["point_index"]) for item in loaded] == [0, 1, 2]
