"""Regression tests for `LocalProcessRunner._build_command`.

The bug these tests guard against: a subprocess-env-leakage classic.
Adapters historically built worker commands as ``["python", str(worker), ...]``
with a bare ``"python"``. The runner had a misguided guard that only
substituted ``sys.executable`` when ``shutil.which("python") is None`` — i.e.
when there was NO ``python`` on ``PATH``. With base conda's ``python`` on
PATH almost everywhere, the substitution never fired, so the worker
subprocess ran in a different env than the kernel/CLI that spawned it.
The visible symptom was 11/11 BioModels DOE points failing with
``ModuleNotFoundError: No module named 'roadrunner'`` recorded only in
``sweep_logs.jsonl`` (and "0 successful runs" in the cell output, which the
verification harness never read).

See `Status.md` "False success metric in tutorial verification" post-mortem.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bayesian_metamodeling.adapters import AdapterMaterialization
from bayesian_metamodeling.runners.local_process import LocalProcessRunner


def _runner() -> LocalProcessRunner:
    return LocalProcessRunner()


def test_substitutes_sys_executable_for_bare_python_no_conda_env(tmp_path: Path) -> None:
    """Bare ``"python"`` at command[0] => substituted with ``sys.executable``.

    This is the regression for the BioModels-worker-runs-in-wrong-env bug:
    we need the worker subprocess to inherit the env that built the command,
    not whatever PATH-`python` resolves to.
    """
    runner = _runner()
    mat = AdapterMaterialization(
        command=["python", "-c", "print('ok')"],
        cwd=tmp_path,
        execution_env={},
    )
    built = runner._build_command(mat)
    assert built[0] == sys.executable, (
        f"Expected sys.executable={sys.executable!r}, got {built[0]!r}. "
        "The runner must substitute sys.executable for bare 'python' so "
        "worker subprocesses inherit the kernel/CLI's env."
    )
    # The rest of the command must be passed through unchanged.
    assert built[1:] == ["-c", "print('ok')"]


def test_substitution_actually_runs_in_correct_env(tmp_path: Path) -> None:
    """End-to-end smoke: invoke a worker that prints its own sys.executable.

    Catches a regression where _build_command does the substitution but the
    runner fails to use the substituted command (e.g. caller passes the
    wrong list, future refactor breaks the contract).
    """
    runner = _runner()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mat = AdapterMaterialization(
        command=["python", "-c", "import sys; print(sys.executable)"],
        cwd=tmp_path,
        execution_env={},
    )
    result = runner.run(materialization=mat, run_dir=run_dir)
    assert result.returncode == 0, result.stderr_path.read_text()
    captured = result.stdout_path.read_text().strip()
    assert captured == sys.executable, (
        f"Worker subprocess ran with python={captured!r} but the runner's "
        f"env is {sys.executable!r}. The worker must inherit the kernel/CLI's env."
    )


def test_does_not_alter_first_arg_when_not_python(tmp_path: Path) -> None:
    """Only bare ``"python"`` is substituted — not other entrypoints.

    A spec with ``entrypoint: ["bash", "myscript.sh"]`` (or any non-python
    command) must be passed through unchanged. The substitution is targeted
    at the ``python`` typo, not a blanket "rewrite first arg".
    """
    runner = _runner()
    for original in (["bash", "myscript.sh"], ["./bin/my-tool", "--flag"]):
        mat = AdapterMaterialization(
            command=list(original),
            cwd=tmp_path,
            execution_env={},
        )
        built = runner._build_command(mat)
        assert built == original, (
            f"Runner should pass through non-python entrypoints unchanged. "
            f"Got {built!r} for input {original!r}."
        )


def test_conda_env_wrapping_takes_precedence_over_substitution(tmp_path: Path) -> None:
    """When ``execution_env.conda_env`` is set, the runner wraps the WHOLE
    command (including bare ``"python"``) in ``["conda", "run", "-n", env, ...]``.
    The bare-python substitution does NOT fire — the user explicitly asked
    for a different env, and ``conda run`` will resolve ``python`` inside
    that env's PATH.
    """
    runner = _runner()
    mat = AdapterMaterialization(
        command=["python", "-c", "print('ok')"],
        cwd=tmp_path,
        execution_env={"conda_env": "py312_some_other_env"},
    )
    built = runner._build_command(mat)
    assert built == [
        "conda",
        "run",
        "-n",
        "py312_some_other_env",
        "python",
        "-c",
        "print('ok')",
    ], (
        f"Conda-env wrapping should take precedence and leave bare 'python' "
        f"in the wrapped command (resolved by conda's env activation). "
        f"Got: {built!r}"
    )
