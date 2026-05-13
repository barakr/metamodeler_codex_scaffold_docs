"""Tests for the cross-platform tutorial bootstrap helper."""

from __future__ import annotations

import sys
from pathlib import Path

from bayesian_metamodeling.tutorial import bootstrap, find_repo_root, run_cli


def test_bootstrap_returns_repo_root_with_marker():
    root = bootstrap()
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "bayesian_metamodeling").is_dir()


def test_run_cli_executes_help_without_shell(tmp_path):
    # Calling `bayesmm --version` via the helper should succeed and print usage text.
    result = run_cli("--version", capture=True)
    assert result.returncode == 0
    assert "bayesian-metamodeling" in result.stdout.lower()


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
