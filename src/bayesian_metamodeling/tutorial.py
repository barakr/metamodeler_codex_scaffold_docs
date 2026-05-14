"""Tutorial-facing helpers: repo bootstrap + in-process CLI / tool runners.

Every tutorial notebook's first cell does a tiny path bootstrap (find the repo
root, put ``src/`` on ``sys.path``) and then imports these helpers — so the
bootstrap boilerplate lives here once instead of being copy-pasted into every
notebook. Cross-platform: no shell cells, no ``PYTHONPATH=`` prefix, no
hardcoded paths — works identically on Windows cmd, Windows PowerShell, macOS,
and Linux.

Typical first cell of a tutorial notebook::

    import sys
    from pathlib import Path

    _root = Path.cwd().resolve()
    while not (_root / "src" / "bayesian_metamodeling").is_dir() and _root != _root.parent:
        _root = _root.parent
    if str(_root / "src") not in sys.path:
        sys.path.insert(0, str(_root / "src"))

    from bayesian_metamodeling.tutorial import bootstrap, run_mm_cli, run_tool

    root = bootstrap()
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path

from bayesian_metamodeling.config.bootstrap import bootstrap, find_repo_root

__all__ = ["bootstrap", "find_repo_root", "run_mm_cli", "run_tool"]


@contextmanager
def _in_repo_root():
    """Temporarily chdir to the repo root, restoring the previous CWD on exit."""
    root = find_repo_root()
    previous = Path.cwd()
    os.chdir(root)
    try:
        yield root
    finally:
        os.chdir(previous)


def run_mm_cli(*args: str, check: bool = True) -> int:
    """Run ``bayesmm <args>`` in-process from the repo root.

    Cross-platform — no shell, no env-var prefix. Captures and re-prints
    stdout/stderr so notebook output stays stable. Raises ``RuntimeError`` on a
    non-zero exit unless ``check=False``.
    """
    from bayesian_metamodeling.cli.main import main as mm_main

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    previous_argv = sys.argv[:]
    try:
        sys.argv = ["bayesmm", *args]
        with _in_repo_root(), redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exit_code = mm_main()
    finally:
        sys.argv = previous_argv

    print("$ bayesmm", " ".join(args))
    out = stdout_buf.getvalue().strip()
    err = stderr_buf.getvalue().strip()
    if out:
        print(out)
    if err:
        print(err)
    if check and exit_code != 0:
        raise RuntimeError(f"CLI command failed ({exit_code}): bayesmm {' '.join(args)}")
    return exit_code


def run_tool(*args: str, check: bool = True) -> int:
    """Run an auxiliary tool (``pytest``, ``ruff``, ``python``) from the repo root.

    Routes the tool through ``sys.executable -m <tool>`` so it always uses the
    active interpreter and works without a shell on every platform — never
    relying on a bare ``python``/``pytest``/``ruff`` being on ``PATH`` (which is
    unreliable in conda envs on Windows). Raises ``RuntimeError`` on a non-zero
    exit unless ``check=False``.
    """
    cmd = list(args)
    if cmd and cmd[0] in {"pytest", "ruff"}:
        cmd = [sys.executable, "-m", *cmd]
    elif cmd and cmd[0] == "python":
        cmd = [sys.executable, *cmd[1:]]
    print("$", " ".join(args))
    with _in_repo_root():
        result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    if check and result.returncode != 0:
        raise RuntimeError(f"Tool failed ({result.returncode}): {' '.join(args)}")
    return result.returncode
