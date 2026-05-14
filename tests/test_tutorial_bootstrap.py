"""Tests for the cross-platform tutorial bootstrap + runner helpers."""

from __future__ import annotations

import sys
from pathlib import Path

from bayesian_metamodeling.tutorial import bootstrap, find_repo_root, run_mm_cli, run_tool


def test_bootstrap_returns_repo_root_with_marker():
    root = bootstrap()
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "bayesian_metamodeling").is_dir()


def test_run_mm_cli_executes_version_in_process():
    # Calling `bayesmm --version` in-process should succeed and print the name.
    exit_code = run_mm_cli("--version")
    assert exit_code == 0


def test_run_mm_cli_check_false_swallows_nonzero_exit():
    # A bad subcommand returns non-zero; check=False must not raise.
    exit_code = run_mm_cli("validate", "does/not/exist.json", check=False)
    assert exit_code != 0


def test_run_tool_runs_pytest_collect_only():
    # run_tool routes pytest/ruff through `python -m`; a trivial collect-only
    # invocation must succeed cross-platform.
    exit_code = run_tool("pytest", "--collect-only", "-q", "tests/test_tutorial_bootstrap.py")
    assert exit_code == 0


def test_bootstrap_chdir_changes_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Even from a tmp_path that's NOT inside the repo, we can pass an explicit
    # notebook_file pointer; bootstrap from the repo's own pyproject path.
    repo_root = find_repo_root(Path(__file__).parent)
    bootstrap(notebook_file=str(Path(__file__)))
    assert Path.cwd().resolve() == repo_root.resolve()


def test_bootstrap_idempotent():
    a = bootstrap()
    src = str((a / "src").resolve())
    count_before = sys.path.count(src)
    b = bootstrap()
    count_after = sys.path.count(src)
    assert a == b
    # bootstrap must not append the same path twice on repeated calls
    assert count_after == count_before
    assert count_after >= 1
