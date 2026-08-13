"""The sweep engine is usable as a library, not only through the CLI (D1).

Before this, `_execute_design_point`, `_run_serial`, `_run_parallel_local` and `_run_mpi`
lived inside `cli/main.py`. Running a sweep from a notebook therefore meant shelling out to
`bayesmm run` or importing underscore-prefixed CLI internals — backwards for a project whose
tutorials *are* notebooks.

These tests pin the properties that make the extraction worth having: a typed entry point
that returns results, a silent default, an injectable progress sink, and the ability to run
a caller-supplied subset of points.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest

import bayesian_metamodeling.storage.run_store as run_store
from bayesian_metamodeling.execution import run_sweep, run_sweep_to_store
from bayesian_metamodeling.spec import load_and_validate_modelspec


def _toy_spec(**overrides):
    payload = copy.deepcopy(
        json.loads(Path("examples/toy_program/spec.toy_program.json").read_text())
    )
    payload["design"] = {"strategy": "grid", "grid": {"a": [1.0, 2.0], "b": [2.0]}}
    payload["storage"] = {"root": f"tmp/pytest_exec_{uuid4().hex}"}
    payload.update(overrides)
    return payload


def test_run_sweep_returns_results_without_writing_anything():
    """The library call runs the models and hands back rows; persistence is a separate step."""
    spec = load_and_validate_modelspec(_toy_spec())
    outcome = run_sweep(spec)

    assert outcome.execution_mode == "serial"
    assert outcome.is_writer
    assert len(outcome.point_results) == 2
    assert outcome.success_count == 2
    assert outcome.failed_count == 0
    assert {r["point"]["a"] for r in outcome.point_results} == {1.0, 2.0}
    # Nothing was registered — run_sweep does not persist.
    assert not (Path(spec.storage.root) / "sweeps").exists()


def test_is_silent_by_default_and_reports_through_the_callback(capsys):
    """A library that prints is unusable from a notebook rendering its own progress."""
    spec = load_and_validate_modelspec(_toy_spec())

    run_sweep(spec)
    assert capsys.readouterr().out == "", "run_sweep must not print unless asked to"

    lines: list[str] = []
    run_sweep(spec, on_progress=lines.append)
    assert any("Running point 1/2" in line for line in lines)


def test_accepts_a_caller_supplied_subset_of_points():
    """Re-running a couple of failed points should not require re-planning the design."""
    spec = load_and_validate_modelspec(_toy_spec())
    outcome = run_sweep(spec, points=[{"a": 5.0, "b": 6.0}])

    assert len(outcome.point_results) == 1
    assert outcome.point_results[0]["point"] == {"a": 5.0, "b": 6.0}


def test_run_sweep_to_store_persists_and_returns_the_stored_run(monkeypatch, tmp_path):
    monkeypatch.setattr(run_store, "REGISTRY_PATH", tmp_path / "run_registry.json")

    payload = _toy_spec()
    spec = load_and_validate_modelspec(payload)
    outcome, stored = run_sweep_to_store(spec, spec_payload=payload)

    assert outcome.success_count == 2
    assert stored is not None
    assert stored.run_record_path.exists()
    assert (stored.run_dir / "sweep_rows.csv").exists()


def test_unsupported_mode_raises_rather_than_returning_a_bare_code():
    """A library raises; only the CLI turns failure into an exit code."""
    spec = load_and_validate_modelspec(_toy_spec())
    object.__setattr__(spec.runner, "sweep_mode", "teleport")
    with pytest.raises(ValueError, match="Unsupported runner.sweep_mode"):
        run_sweep(spec, points=[{"a": 1.0, "b": 2.0}])
