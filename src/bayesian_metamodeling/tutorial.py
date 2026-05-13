"""Tutorial-facing bootstrap and CLI runner.

Replaces the hardcoded `cd /Users/barak/Downloads/...` and `%%bash` cells
that broke on every machine but the original author's. Cross-platform:
works identically on Windows cmd, Windows PowerShell, macOS, and Linux.

Typical first cell of a tutorial notebook::

    from bayesian_metamodeling.tutorial import bootstrap, run_cli
    ROOT = bootstrap()
    run_cli("validate", "tutorials/specs/model.toy.grid.json")
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from bayesian_metamodeling.config.bootstrap import bootstrap, find_repo_root

__all__ = ["bootstrap", "find_repo_root", "run_cli"]


def run_cli(
    *args: str,
    capture: bool = False,
    check: bool = False,
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess:
    """Invoke `python -m bayesian_metamodeling.cli.main <args>` cross-platform.

    Uses `sys.executable` so the same interpreter (and any active venv/conda
    env) is used. No shell, no env-var prefix, no hardcoded paths — works
    identically on Windows / macOS / Linux.

    `capture=True` captures stdout/stderr (useful inside notebooks where
    subprocess output otherwise streams unevenly).
    """
    cwd_path = Path(cwd) if cwd is not None else find_repo_root()
    cmd = [sys.executable, "-m", "bayesian_metamodeling.cli.main", *args]
    return subprocess.run(
        cmd,
        cwd=str(cwd_path),
        check=check,
        capture_output=capture,
        text=True,
    )
