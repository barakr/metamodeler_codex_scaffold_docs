"""No file may be named `setup.py` inside the package (false dependency manifests).

GitHub's dependency graph reads *any* file called `setup.py` as a pip manifest and scrapes
package names out of it. `src/bayesian_metamodeling/config/setup.py` was not a packaging
script at all — it was the module behind `bayesmm setup`, which prints install advice and
therefore mentions `pymc`, `sbi`, `arviz` and `jupyter` in its help strings. Those got picked
up as dependencies, and the graph job was literally titled
`Graph Update: pip in /., /src/bayesian_metamodeling/config`.

Why that is worth a test rather than a shrug: the dependency graph is the channel this
repository now relies on for vulnerability alerts (`REPRODUCIBILITY.md`). Phantom entries in
it are noise in exactly the place where noise is expensive — and Dependabot may eventually
try to "update" a dependency in a file that declares none, producing a pull request nobody can
act on. A signal you have been trained to distrust is worse than no signal.

The module is now `config/install_advice.py`. `from bayesian_metamodeling.config import setup`
still works: only the file moved, not the public name.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"


def test_no_setup_py_inside_the_package():
    offenders = [p.relative_to(REPO_ROOT) for p in SRC.rglob("setup.py")]
    assert not offenders, (
        f"{offenders} will be read by GitHub's dependency graph as a pip manifest, and any "
        "package name mentioned inside becomes a phantom dependency. Packaging here is done "
        "entirely by pyproject.toml, so a setup.py in src/ is never a real manifest. Rename "
        "the module (see config/install_advice.py, which had exactly this problem)."
    )


def test_packaging_really_is_pyproject_only():
    """The premise of the test above: there is no legitimate setup.py to confuse it with."""
    assert (REPO_ROOT / "pyproject.toml").exists()
    assert not (REPO_ROOT / "setup.py").exists(), (
        "a root setup.py appeared; if packaging genuinely moved off pyproject.toml, the test "
        "above needs to learn the difference between the real manifest and a false one"
    )


def test_the_public_setup_name_survived_the_rename():
    """Renaming the file must not move the API — `bayesmm setup` and its tests use this."""
    from bayesian_metamodeling.config import format_install_commands, setup

    assert callable(setup)
    assert callable(format_install_commands)
