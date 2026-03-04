"""CLI error path tests: invalid specs, failing models, bad inputs, --version, tutorial."""

from __future__ import annotations

import json

from bayesian_metamodeling.cli.main import main


def test_version_flag(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["mm", "--version"])
    code = main()
    out = capsys.readouterr().out
    assert code == 0
    assert "bayesian-metamodeling" in out


def test_tutorial_command(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["mm", "tutorial"])
    code = main()
    out = capsys.readouterr().out
    assert code == 0
    assert "tutorial" in out.lower()


def test_validate_with_missing_file(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("sys.argv", ["mm", "validate", str(tmp_path / "nope.json")])
    code = main()
    out = capsys.readouterr().out
    assert code == 1
    assert "not found" in out


def test_validate_with_invalid_json(monkeypatch, capsys, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{invalid json")
    monkeypatch.setattr("sys.argv", ["mm", "validate", str(bad)])
    code = main()
    out = capsys.readouterr().out
    assert code == 1
    assert "Invalid JSON" in out


def test_validate_with_invalid_spec(monkeypatch, capsys, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"schema_version": "1.0"}))
    monkeypatch.setattr("sys.argv", ["mm", "validate", str(spec)])
    code = main()
    out = capsys.readouterr().out
    assert code == 1
    assert "validation failed" in out.lower()


def test_plan_with_invalid_spec(monkeypatch, capsys, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"schema_version": "1.0"}))
    monkeypatch.setattr("sys.argv", ["mm", "plan", str(spec)])
    code = main()
    assert code == 1


def test_run_with_invalid_spec(monkeypatch, capsys, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"schema_version": "1.0"}))
    monkeypatch.setattr("sys.argv", ["mm", "run", str(spec)])
    code = main()
    assert code == 1


def test_surrogate_fit_with_invalid_spec(monkeypatch, capsys, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"bad": True}))
    monkeypatch.setattr("sys.argv", ["mm", "surrogate", "fit", str(spec)])
    code = main()
    capsys.readouterr()  # consume output
    assert code == 1


def test_surrogate_eval_with_bad_inputs_json(monkeypatch, capsys, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"bad": True}))
    monkeypatch.setattr(
        "sys.argv",
        ["mm", "surrogate", "eval", str(spec), "--inputs", "not json", "--n", "5"],
    )
    code = main()
    assert code == 1


def test_meta_build_with_invalid_spec(monkeypatch, capsys, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"bad": True}))
    monkeypatch.setattr("sys.argv", ["mm", "meta", "build", str(spec)])
    code = main()
    assert code == 1


def test_meta_sample_with_invalid_spec(monkeypatch, capsys, tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"bad": True}))
    monkeypatch.setattr(
        "sys.argv",
        ["mm", "meta", "sample", str(spec), "--draws", "10"],
    )
    code = main()
    assert code == 1


def test_no_command_prints_help(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["mm"])
    code = main()
    assert code == 0
