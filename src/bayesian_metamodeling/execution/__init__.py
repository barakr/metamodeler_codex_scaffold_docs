"""Sweep execution — the layer between a planned DOE and stored results.

This exists because the sweep engine used to live inside `cli/main.py`, which meant the
only supported way to run a sweep was to invoke the CLI. For a project whose tutorials are
notebooks, that is backwards: a student who wanted to run a sweep from a cell had to shell
out to `bayesmm run`, or import underscore-prefixed functions out of a CLI module and hope
they kept working.

`TechSpec.md` describes the pipeline as spec -> design -> adapter -> runner -> storage. There
was no home for *orchestration* — deciding how the planned points get executed — so it landed
in the CLI by default. This package is that home.

The CLI is now argument parsing and printing.
"""

from __future__ import annotations

from bayesian_metamodeling.execution.sweep import (
    ProgressCallback,
    SweepOutcome,
    execute_design_point,
    run_sweep,
    run_sweep_to_store,
)

__all__ = [
    "ProgressCallback",
    "SweepOutcome",
    "execute_design_point",
    "run_sweep",
    "run_sweep_to_store",
]
