"""Guards for the tcr_signaling submodule's framework-dependent notebooks.

`projects/tcr_signaling/notebooks/0{1..4}` drive the `bayesmm` CLI, so they can only be
verified from here -- the submodule deliberately does not depend on the framework, and
its own CI installs numpy/scipy/matplotlib and nothing else. The submodule verifies its
framework-free KS series itself.

Split deliberately:

* The **static** checks are fast and backend-free, so they run in Interface CI on every
  push. They catch the failure modes that actually occurred: a hardcoded absolute path,
  a stale module path, a missing self-check beacon.
* The **execution** tests are marked `slow` and are not in CI. `02` needs PyMC and `03`
  samples a posterior; pulling those backends into the Interface job would make a job
  that is intentionally fast and pin-independent both slow and pin-coupled. Run them
  with `make slow`, or `pytest -m slow tests/test_submodule_notebooks.py`.

This mirrors how the framework's own tutorials are treated (`test_tutorial_integration.py`
is `slow` and excluded from CI, with `test_tutorial_portability.py` fast).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_REPO = Path(__file__).resolve().parents[1]
_NB_DIR = _REPO / "projects" / "tcr_signaling" / "notebooks"

# Notebooks that require the framework, with the beacon each must print.
_FRAMEWORK_NOTEBOOKS = {
    "01_explore_models.ipynb": "[NB01 self-check OK]",
    "02_fit_surrogates.ipynb": "[NB02 self-check OK]",
    "03_metamodel_inference.ipynb": "[NB03 self-check OK]",
    "04_reproduce_figures.ipynb": "[NB04 self-check OK]",
}

# Notebooks needing an optional backend, and the module that provides it.
_NEEDS_BACKEND = {"02_fit_surrogates.ipynb": "pymc", "03_metamodel_inference.ipynb": "pymc"}

_FAILURE_MARKERS = ("Traceback", "ModuleNotFoundError", "unrecognized arguments")


def _submodule_present() -> bool:
    return _NB_DIR.is_dir() and any(_NB_DIR.glob("0*.ipynb"))


def _require_or_skip() -> None:
    if _submodule_present():
        return
    msg = (
        f"tcr_signaling submodule not checked out at {_NB_DIR}. "
        "Run: git submodule update --init projects/tcr_signaling"
    )
    # Interface CI sets this, so a broken checkout fails loudly instead of
    # quietly passing as "all skipped".
    if os.environ.get("REQUIRE_SUBMODULE_INTERFACE") == "1":
        pytest.fail(msg)
    pytest.skip(msg)


def _sources(nb_path: Path) -> str:
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    return "\n".join("".join(c.get("source", [])) for c in nb.get("cells", []))


# ---------------------------------------------------------------- static


def test_submodule_notebooks_are_present():
    _require_or_skip()
    missing = [n for n in _FRAMEWORK_NOTEBOOKS if not (_NB_DIR / n).is_file()]
    assert not missing, f"missing notebooks: {missing}"


@pytest.mark.parametrize("name", sorted(_FRAMEWORK_NOTEBOOKS))
def test_notebook_has_a_self_check_beacon(name: str):
    """Without a beacon, executing the notebook proves only that it did not raise."""
    _require_or_skip()
    beacon = _FRAMEWORK_NOTEBOOKS[name]
    assert beacon in _sources(_NB_DIR / name), (
        f"{name} has no {beacon!r} cell, so the execution test below cannot tell "
        "'it worked' from 'it did nothing'."
    )


@pytest.mark.parametrize("name", sorted(_FRAMEWORK_NOTEBOOKS))
def test_notebook_has_no_absolute_or_stale_paths(name: str):
    """Both of these actually shipped: a fixed-depth bootstrap and a doubled prefix."""
    _require_or_skip()
    src = _sources(_NB_DIR / name)
    for bad in (
        "/Users/",
        "/home/",
        "parent.parent.parent",
        "projects.tcr_signaling.models.",
        '"projects/tcr_signaling/',
    ):
        assert bad not in src, f"{name} contains {bad!r}, which breaks outside one layout"


@pytest.mark.parametrize("name", sorted(_FRAMEWORK_NOTEBOOKS))
def test_notebook_declares_its_framework_dependency(name: str):
    """A reader without bayesmm should learn that from the notebook, not a traceback."""
    _require_or_skip()
    src = _sources(_NB_DIR / name)
    assert "bayesian-metamodeling" in src or "HAVE_BAYESMM" in src, (
        f"{name} drives the framework but never says so"
    )


def test_ks_series_stays_framework_free():
    """The KS notebooks must not acquire a framework dependency: it is what lets the
    submodule execute them in its own CI, which installs no framework."""
    _require_or_skip()
    ks_dir = _NB_DIR / "models" / "kinetic_segregation"
    if not ks_dir.is_dir():
        pytest.skip("KS series not present")
    offenders = []
    for nb in sorted(ks_dir.glob("KS_*.ipynb")):
        src = _sources(nb)
        if "bayesian_metamodeling" in src or "bayesmm" in src:
            offenders.append(nb.name)
    assert not offenders, (
        f"KS notebooks must stay framework-free, but these reference it: {offenders}"
    )


# ------------------------------------------------------------- execution


# Notebooks that cannot currently pass, with the reason. `strict=True` means a
# fix turns the XPASS into a failure, so the entry has to be removed rather than
# quietly outliving the defect.
#
# 03_metamodel_inference: specs/metamodel.tcr_signaling.json references four
# surrogate artifacts under projects/tcr_signaling/artifacts/ that NOTHING
# produces — `surrogate fit` (which 02 runs) writes into the surrogate store, not
# there — so `meta build` dies with "Could not resolve surrogate_ref". This is a
# reference-chain defect in the research config, not a test problem; see
# tcr_signaling Status.md, which already recorded the artifacts as missing.
_KNOWN_BROKEN = {
    "03_metamodel_inference.ipynb": (
        "metamodel spec references surrogate artifacts that no pipeline step creates "
        "(meta build: Could not resolve surrogate_ref)"
    ),
}


def _execution_params():
    out = []
    for name in sorted(_FRAMEWORK_NOTEBOOKS):
        reason = _KNOWN_BROKEN.get(name)
        marks = [pytest.mark.xfail(reason=reason, strict=True)] if reason else []
        out.append(pytest.param(name, marks=marks, id=name))
    return out


@pytest.mark.slow
@pytest.mark.parametrize("name", _execution_params())
def test_notebook_executes_and_self_check_passes(name: str, tmp_path):
    _require_or_skip()
    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")

    backend = _NEEDS_BACKEND.get(name)
    if backend:
        pytest.importorskip(backend, reason=f"{name} needs {backend}")

    nb_path = _NB_DIR / name
    nb = nbformat.read(nb_path, as_version=4)
    nbclient.NotebookClient(
        nb,
        # 02_fit_surrogates sweeps every model.*.json — 79 DOE points, 56 of them
        # the KS production spec — which is ~30 min of real simulation, and 03
        # samples the metamodel with 2000 draws. These are reproduce-the-science
        # notebooks, not smoke tests; 1800s timed out mid-sweep in CI. The weekly
        # job budgets 90 minutes for the lot.
        timeout=3600,
        kernel_name="python3",
        resources={"metadata": {"path": str(_NB_DIR)}},
    ).execute()

    texts = []
    for cell in nb.cells:
        for out in cell.get("outputs", []):
            if out.output_type == "error":
                raise AssertionError(f"{name}: {out.get('ename')}: {out.get('evalue')}")
            texts.append(out.get("text", "") or "")
    combined = "\n".join(texts)

    for marker in _FAILURE_MARKERS:
        assert marker not in combined, f"{name} printed a failure marker: {marker}"

    beacon = _FRAMEWORK_NOTEBOOKS[name]
    assert beacon in combined, f"{name} ran without raising but never printed {beacon!r}"
