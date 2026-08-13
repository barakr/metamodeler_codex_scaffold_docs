"""End-to-end integration test: execute every tutorial notebook + verify its self-check.

This test is the tracked counterpart to the per-tutorial self-check cells
appended to each `tutorials/Tutorial_*.ipynb` (commit 8fe052b). The
self-check cells assert the tutorial's canonical scientific artifact is
present and non-trivial — sweep_rows.csv has success rows, surrogate MAE
within tolerance, coupling correlation > 0.9, capstone composes
end-to-end, etc. This test wraps that contract in pytest so CI catches
notebook regressions automatically.

Marked `@pytest.mark.slow` because executing all 10 notebooks takes ~5
minutes (PyMC fits + SBI training + metamodel sampling + BioModels SBML
runs when available). Run locally with:

    PYTHONPATH=src pytest -m slow tests/test_tutorial_integration.py

The test runs in the CURRENT pytest interpreter — so per-env coverage
comes from running this test in each conda env (or via the CI matrix).
Skip-safe for backend-gated tutorials: if libroadrunner/sbi/torch are
missing, the tutorial's preflight prints a banner and skips its
backend-gated steps; the self-check assertion accepts that as success.

Background: the previous "30/30 PASS" verification (~commit 61454b5)
checked only `jupyter execute` exit code and missed T2 silently failing
11/11 BioModels DOE points (root cause + fix in commit 28835b8). This
test closes the false-success-metric gap. See `Status.md` "Tutorial-
stability hardening + post-mortem" for the full story.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TUTORIALS = REPO_ROOT / "tutorials"

# --- Stale shared state makes a local run worse than useless -----------------
#
# The tutorials pass data to each other through one directory: T1 and T4 *write*
# `tmp/tutorials/toy_store`, T5 and T6 *read* it. On a machine that has run the
# series before, that store is already populated — so a notebook which would fail
# in a clean checkout can pass here, standing on data an earlier session left
# behind.
#
# This is not hypothetical. On 2026-08-12 `Tutorial_5` failed in Deep CI and
# passed locally. It had no defect: its surrogate fits on the store `Tutorial_1`
# produces, and `Tutorial_1` was crashing. A clean checkout had nothing to fit on;
# this machine had last week's copy. The local run did not merely miss the problem,
# it reported the opposite.
#
# So: refuse to run against a pre-existing store unless the caller says otherwise.
# Fail rather than skip — a skipped suite and a passing suite look identical in a
# terminal, which is the defect this repo keeps finding in itself (CLAUDE.md,
# "Guarding against silent no-ops").
TUTORIAL_STORE = REPO_ROOT / "tmp" / "tutorials"
ALLOW_DIRTY_ENV_VAR = "MM_ALLOW_DIRTY_TUTORIAL_STORE"


def _dirty_store_reason() -> str | None:
    """Return a message if a leftover tutorial store would taint this run."""
    if os.environ.get(ALLOW_DIRTY_ENV_VAR, "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    if not TUTORIAL_STORE.exists():
        return None
    leftovers = sorted(p.name for p in TUTORIAL_STORE.iterdir() if p.is_dir())
    if not leftovers:
        return None
    # Display the path relative to the repo when it is inside it (the real case), and
    # absolutely otherwise (tests point this at a tmp dir). `relative_to` raises rather
    # than falling back, so ask first.
    try:
        shown = TUTORIAL_STORE.relative_to(REPO_ROOT)
    except ValueError:
        shown = TUTORIAL_STORE
    return (
        f"{shown} already contains data from an earlier run "
        f"({', '.join(leftovers[:6])}{'…' if len(leftovers) > 6 else ''}).\n"
        "\n"
        "The tutorials hand data to each other through this directory, so a notebook that "
        "would FAIL in a clean checkout can PASS against these leftovers — which is what "
        "happened to Tutorial_5 on 2026-08-12. A run against a dirty store cannot tell you "
        "whether the series works.\n"
        "\n"
        "Either clear it and re-run:\n"
        f"    rm -rf {shown}\n"
        "\n"
        f"or set {ALLOW_DIRTY_ENV_VAR}=1 to accept a result that proves less than it looks "
        "like it does. CI always runs on a clean checkout and never needs the override."
    )


# Snapshot at IMPORT time, which is before any notebook has run.
#
# Checking this per-test would be self-defeating: `Tutorial_1` legitimately *creates*
# `tmp/tutorials/toy_store`, so tutorials 2-12 would then see a populated store and fail
# — in CI, on a clean checkout, every time. The question is only ever "was the store
# dirty when this session started", and that has exactly one answer per run.
_DIRTY_STORE_AT_IMPORT = _dirty_store_reason()


# Failure markers — cell-output substrings that mean the tutorial DID
# something wrong, even if no Python exception was raised. Grep'd from
# the framework's own error messages + nbformat conventions.
FAILURE_MARKERS = (
    "Run complete with failures",
    "successful runs: 0",
    "0 successful runs",
    "Traceback (most recent call last)",
    "ModuleNotFoundError",
    "AssertionError",
    "RuntimeError: ",
    "Surrogate fit failed:",
    "Spec validation failed:",  # T3 PRINTS this in cell outputs intentionally; we
    # exempt T3 below.
)

# Tutorials that legitimately print a known failure marker as part of the lesson.
# Each entry maps notebook name -> set of failure markers we're allowed to ignore
# in that notebook's output.
EXPECTED_DIAGNOSTIC_MARKERS = {
    # T3's break/repair cycles intentionally trigger validation errors
    # — the cell printouts ARE the lesson.
    #
    # `Run complete with failures` joined the list when Step 5 was retargeted. The step
    # used to rename a `design.grid` key, which `bayesmm run` turned into a `KeyError`
    # from the storage layer — the sweep died and wrote nothing, so no summary line was
    # ever printed. That break is now rejected at validation, so Step 5 demonstrates the
    # contract that IS still unenforced: an `adapter.input_mapping` var that `io_schema`
    # never declares. That one runs, fails all nine points with the adapter's message,
    # and persists the sweep — which is a better outcome and a legible summary line.
    # The line is the lesson; the self-check asserts its content precisely.
    "Tutorial_3.ipynb": {
        "Spec validation failed:",
        "Run complete with failures",
        "0 successful runs",
    },
    # T0 is the diagnostic notebook: `bayesmm doctor` reports the literal
    # `ModuleNotFoundError` text that Python would raise for each missing
    # optional package, as actionable info. Not a failure.
    "Tutorial_0.ipynb": {"ModuleNotFoundError"},
}

# Each tutorial's self-check cell prints a `[T<N> self-check OK]` line. We
# assert it appears in some cell's output to confirm the assertion cell
# actually ran (rather than being skipped, deleted, or silently failing).
SELFCHECK_BEACONS = {f"Tutorial_{i}.ipynb": f"[T{i} self-check OK]" for i in range(10)}
# Module 7 is three notebooks rather than one — 7a (what a coupling is), 7b (sampling the
# joint), 7c (asking questions of it) — because one 31-minute notebook was three questions
# wearing a trench coat. An unregistered notebook makes this test `pytest.fail` rather than
# skip, deliberately, so a new tutorial cannot slip in unchecked.
del SELFCHECK_BEACONS["Tutorial_7.ipynb"]
for _part in ("a", "b", "c"):
    SELFCHECK_BEACONS[f"Tutorial_7{_part}.ipynb"] = f"[T7{_part} self-check OK]"


def _notebook_paths() -> list[Path]:
    if not TUTORIALS.exists():
        return []
    return sorted(TUTORIALS.glob("Tutorial_*.ipynb"))


@pytest.fixture(params=_notebook_paths(), ids=lambda p: p.stem)
def notebook_path(request) -> Path:
    return request.param


def _read_outputs(executed_nb: dict) -> str:
    """Concatenate every cell's text output into one searchable string."""
    chunks: list[str] = []
    for cell in executed_nb.get("cells", []):
        for output in cell.get("outputs", []):
            text = output.get("text", "")
            if isinstance(text, list):
                text = "".join(text)
            chunks.append(text)
            data = output.get("data", {})
            for value in data.values():
                if isinstance(value, list):
                    chunks.append("".join(value))
                elif isinstance(value, str):
                    chunks.append(value)
            # Capture exception output (raised cells get an `ename`/`evalue` pair).
            if output.get("output_type") == "error":
                chunks.append(output.get("ename", ""))
                chunks.append(output.get("evalue", ""))
                chunks.append("\n".join(output.get("traceback", [])))
    return "\n".join(chunks)


@pytest.mark.slow
@pytest.mark.integration
def test_tutorial_executes_and_self_check_passes(notebook_path: Path, tmp_path: Path) -> None:
    """Execute the tutorial end-to-end; assert no failure markers + self-check beacon present.

    This is the contract the user asked for after the missed T2 silent
    failure: a notebook's execution status must reflect whether the
    notebook achieved its scientific goal, not merely whether it crashed.
    """
    if _DIRTY_STORE_AT_IMPORT is not None:
        pytest.fail(_DIRTY_STORE_AT_IMPORT)

    nbclient = pytest.importorskip("nbclient")
    nbformat = pytest.importorskip("nbformat")

    # Read the source notebook and execute in a tmp working directory so
    # the test doesn't mutate the on-disk .ipynb (its outputs).
    nb = nbformat.read(notebook_path, as_version=4)
    client = nbclient.NotebookClient(
        nb,
        timeout=600,
        kernel_name="python3",
        resources={"metadata": {"path": str(REPO_ROOT)}},
    )
    try:
        client.execute()
    except Exception as exc:
        pytest.fail(
            f"{notebook_path.name} raised during execution: {exc!r}\n"
            f"This means a code cell raised an unhandled exception — the "
            f"self-check cell may have caught a real artifact problem."
        )

    # 1) No general failure markers in cell outputs.
    output_text = _read_outputs(nb)
    exempted = EXPECTED_DIAGNOSTIC_MARKERS.get(notebook_path.name, set())
    for marker in FAILURE_MARKERS:
        if marker in exempted:
            continue
        # `AssertionError` from a self-check would have raised in client.execute()
        # above; if it shows up in outputs without raising, that's a different
        # AssertionError (e.g., from inside a try block) — still a real failure.
        assert marker not in output_text, (
            f"{notebook_path.name} executed cleanly (no exception) but its cell "
            f"outputs contain failure marker {marker!r}. The notebook's "
            f"self-check cell did not catch this; debug the marker's source "
            f"and either fix the tutorial or extend the self-check (or add an "
            f"entry to EXPECTED_DIAGNOSTIC_MARKERS if the marker is "
            f"intentionally part of the lesson)."
        )

    # 2) The self-check beacon must appear — proves the assertion cell ran.
    expected_beacon = SELFCHECK_BEACONS.get(notebook_path.name)
    if expected_beacon is None:
        pytest.fail(f"No self-check beacon registered for {notebook_path.name}")
    assert expected_beacon in output_text, (
        f"{notebook_path.name} did not print {expected_beacon!r} — the "
        f"self-check cell at the end of the notebook may be missing or "
        f"broken. Every tutorial must end with a `[T<N> self-check OK]` "
        f"print so this test can confirm the assertion cell actually ran."
    )

    # 3) In the deep/scheduled run, a preflight skip is a FAILURE.
    #
    # Every backend-gated tutorial degrades to a "SKIPPED" path when its
    # backend is absent, and the self-check then reports OK for having skipped
    # cleanly. That is correct for a learner on a laptop, but it means a green
    # run proves nothing about the science. T2 sat in exactly that state — its
    # whole BioModels sweep skipped, self-check green — which is the same
    # false-success shape as the original post-mortem, merely sanctioned.
    #
    # The scheduled job installs every backend and sets this variable, so there
    # is no legitimate reason for a skip there.
    if os.environ.get("REQUIRE_TUTORIAL_BACKENDS") == "1":
        skip_markers = ("SKIPPED", "skipped per preflight")
        found = sorted({m for m in skip_markers if m in output_text})
        assert not found, (
            f"{notebook_path.name} took a preflight-skip path {found} while "
            f"REQUIRE_TUTORIAL_BACKENDS=1. This job exists to exercise the "
            f"backends, so a skip means a dependency is missing from the job "
            f"(install it) — not that the tutorial passed."
        )
