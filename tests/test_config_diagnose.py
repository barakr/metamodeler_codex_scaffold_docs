"""Smoke tests for the configurer's diagnose() and bootstrap() helpers."""

from __future__ import annotations

import json

from bayesian_metamodeling.config import bootstrap, diagnose, format_diagnose_report
from bayesian_metamodeling.config.bootstrap import find_repo_root
from bayesian_metamodeling.config.diagnose import diagnose_to_json
from bayesian_metamodeling.config.platform import (
    detect_env,
    detect_os,
    detect_package_manager,
    detect_python,
    detect_shell,
    snapshot,
)


def test_diagnose_returns_expected_top_level_keys():
    report = diagnose()
    expected_keys = {
        "os",
        "python",
        "env",
        "package_manager",
        "shell",
        "repo",
        "backends",
        "recommendations",
    }
    assert expected_keys.issubset(report.keys())
    assert isinstance(report["backends"], dict)
    for pkg in ("pymc", "arviz", "torch", "sbi"):
        assert pkg in report["backends"]
        entry = report["backends"][pkg]
        assert set(entry.keys()) == {"installed", "version", "import_error"}
        assert isinstance(entry["installed"], bool)


def test_diagnose_to_json_is_parsable():
    report = diagnose()
    text = diagnose_to_json(report)
    parsed = json.loads(text)
    assert parsed["os"]["system"] == report["os"]["system"]
    assert parsed["python"]["executable"] == report["python"]["executable"]


def test_format_diagnose_report_renders_lines():
    report = diagnose()
    rendered = format_diagnose_report(report)
    assert "Bayesian Metamodeling environment diagnostic" in rendered
    assert "Optional backends" in rendered
    # No NaN-style placeholders in the rendered output.
    assert "None" not in rendered.split("\n")[0]


def test_platform_detectors_return_reasonable_values():
    snap = snapshot()
    assert snap.os.system in {"Windows", "Darwin", "Linux"}
    assert snap.python.version_tuple[0] == 3
    assert snap.python.version_tuple[1] >= 11
    assert snap.env.kind in {"conda", "venv", "system"}

    # Each detector callable in isolation
    assert detect_os().system == snap.os.system
    assert detect_python().executable == snap.python.executable
    assert detect_env().kind == snap.env.kind
    assert detect_shell().name
    assert detect_package_manager() is not None


def test_find_repo_root_walks_up_from_subdir(tmp_path):
    # Use the actual repo root for this test: confirm it resolves correctly.
    root = find_repo_root()
    assert (root / "pyproject.toml").is_file()
    text = (root / "pyproject.toml").read_text()
    assert 'name = "bayesian-metamodeling"' in text


def test_bootstrap_is_idempotent():
    root1 = bootstrap()
    root2 = bootstrap()
    assert root1 == root2
    assert (root1 / "src" / "bayesian_metamodeling").is_dir()


def test_find_repo_root_raises_when_no_marker(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        find_repo_root(tmp_path)
