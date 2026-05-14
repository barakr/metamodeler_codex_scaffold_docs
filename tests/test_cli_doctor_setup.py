"""CLI tests for `bayesmm doctor` and `bayesmm setup`."""

from __future__ import annotations

import json
import sys

from bayesian_metamodeling.cli.main import main
from bayesian_metamodeling.config import setup as setup_fn


def _run_main_and_capture(monkeypatch, capsys, argv: list[str]) -> tuple[int, str]:
    monkeypatch.setattr(sys, "argv", argv)
    code = main()
    captured = capsys.readouterr()
    return code, captured.out


def test_doctor_human_report_runs(monkeypatch, capsys):
    code, out = _run_main_and_capture(monkeypatch, capsys, ["bayesmm", "doctor"])
    assert code == 0
    assert "Bayesian Metamodeling environment diagnostic" in out
    assert "Optional backends" in out


def test_doctor_json_runs_and_emits_valid_json(monkeypatch, capsys):
    code, out = _run_main_and_capture(monkeypatch, capsys, ["bayesmm", "doctor", "--json"])
    assert code == 0
    parsed = json.loads(out)
    assert "os" in parsed
    assert "python" in parsed
    assert "backends" in parsed


def test_setup_non_interactive_with_pymc_sbi(monkeypatch, capsys):
    code, out = _run_main_and_capture(
        monkeypatch,
        capsys,
        ["bayesmm", "setup", "--non-interactive", "--backend", "pymc,sbi"],
    )
    assert code == 0
    assert "Suggested install commands" in out
    assert "pip" in out


def test_setup_non_interactive_with_none_skips_install_lines(monkeypatch, capsys):
    code, out = _run_main_and_capture(
        monkeypatch,
        capsys,
        ["bayesmm", "setup", "--non-interactive", "--backend", "none"],
    )
    assert code == 0
    # When no backends selected, only the bare-pip line should be present.
    assert "pip install -e" in out


def test_setup_non_interactive_rejects_unknown_backend(monkeypatch, capsys):
    code, out = _run_main_and_capture(
        monkeypatch,
        capsys,
        ["bayesmm", "setup", "--non-interactive", "--backend", "tensorflow"],
    )
    assert code == 1
    assert "Setup failed" in out


def test_setup_is_advisory_only_and_writes_nothing(tmp_path, monkeypatch, capsys):
    """`setup` prints install commands; it must not write any files."""
    monkeypatch.chdir(tmp_path)
    result = setup_fn(interactive=False, install_backends="pymc,sbi")

    assert result["backends"] == ["pymc", "sbi"]
    assert result["install_commands"]
    # Advisory only — no state written anywhere.
    assert list(tmp_path.iterdir()) == []
    out = capsys.readouterr().out
    assert "Suggested install commands" in out
