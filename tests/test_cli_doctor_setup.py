"""CLI tests for `mm doctor` and `mm setup`."""

from __future__ import annotations

import json
import sys

from metamodeler.cli.main import main


def _run_main_and_capture(monkeypatch, capsys, argv: list[str]) -> tuple[int, str]:
    monkeypatch.setattr(sys, "argv", argv)
    code = main()
    captured = capsys.readouterr()
    return code, captured.out


def test_doctor_human_report_runs(monkeypatch, capsys):
    code, out = _run_main_and_capture(monkeypatch, capsys, ["mm", "doctor"])
    assert code == 0
    assert "Metamodeler environment diagnostic" in out
    assert "Optional backends" in out


def test_doctor_json_runs_and_emits_valid_json(monkeypatch, capsys):
    code, out = _run_main_and_capture(monkeypatch, capsys, ["mm", "doctor", "--json"])
    assert code == 0
    parsed = json.loads(out)
    assert "os" in parsed
    assert "python" in parsed
    assert "backends" in parsed


def test_setup_non_interactive_with_pymc_sbi(monkeypatch, capsys):
    code, out = _run_main_and_capture(
        monkeypatch,
        capsys,
        ["mm", "setup", "--non-interactive", "--backend", "pymc,sbi", "--no-write-config"],
    )
    assert code == 0
    assert "Suggested install commands" in out
    assert "pip" in out


def test_setup_non_interactive_with_none_skips_install_lines(monkeypatch, capsys):
    code, out = _run_main_and_capture(
        monkeypatch,
        capsys,
        ["mm", "setup", "--non-interactive", "--backend", "none", "--no-write-config"],
    )
    assert code == 0
    # When no backends selected, only the bare-pip line should be present.
    assert "pip install -e" in out


def test_setup_non_interactive_rejects_unknown_backend(monkeypatch, capsys):
    code, out = _run_main_and_capture(
        monkeypatch,
        capsys,
        ["mm", "setup", "--non-interactive", "--backend", "tensorflow", "--no-write-config"],
    )
    assert code == 1
    assert "Setup failed" in out


def test_setup_writes_config_into_repo_root(monkeypatch, capsys, tmp_path):
    from metamodeler.config import setup as setup_fn

    result = setup_fn(
        interactive=False,
        install_backends="pymc",
        write_config=True,
        repo_root=tmp_path,
    )
    config_path = tmp_path / "metamodeler.config.json"
    assert config_path.exists()
    payload = json.loads(config_path.read_text())
    assert "defaults" in payload
    assert payload["selected_backends"] == ["pymc"]
    assert result["config_path"] == str(config_path)
