"""A centralized store may hold sweeps from several models.

Regression test for a bug found on 2026-08-07.

`_load_from_centralized_sweeps` globs every `sweep_rows.csv` under the store and
indexed the surrogate's input columns on each row. A store containing more than
one model's sweeps therefore raised `KeyError: '<input>'` on the first foreign
row — so fitting ANY surrogate broke as soon as a second model had been swept.

That is not an exotic layout: it is what "centralized sweep store" means, and it
is exactly how `projects/tcr_signaling` is arranged — four partial models sharing
one `store/`. It is why the surrogates there had never been fitted.

The fix skips sweeps whose header does not provide this surrogate's inputs. This
test pins the behaviour from both sides: a foreign sweep must be ignored, and a
store with no usable sweep at all must still raise — with a message that says
what it was looking for.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from bayesian_metamodeling.spec import SurrogateSpec
from bayesian_metamodeling.surrogates.dataset import load_tabular_dataset


def _write_sweep(root: Path, name: str, fieldnames: list[str], rows: list[dict]) -> None:
    d = root / "sweeps" / name
    d.mkdir(parents=True, exist_ok=True)
    with (d / "sweep_rows.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _spec(store: Path) -> SurrogateSpec:
    return SurrogateSpec.model_validate(
        {
            "schema_version": "1.0.0",
            "name": "surrogate_alpha",
            "kind": "conditional",
            "inputs": ["a", "b"],
            "outputs": ["y"],
            "backend": "pymc_gp",
            "dataset_ref": str(store),
            "seed": 0,
        }
    )


@pytest.mark.contract
def test_foreign_model_sweeps_are_ignored(tmp_path: Path) -> None:
    store = tmp_path / "store"
    # This surrogate's own model.
    _write_sweep(
        store,
        "alpha",
        ["a", "b", "y", "status"],
        [
            {"a": "1", "b": "2", "y": "3", "status": "success"},
            {"a": "2", "b": "3", "y": "5", "status": "success"},
        ],
    )
    # A different model in the SAME store — no 'a'/'b' columns at all. Before the
    # fix this raised KeyError and took the whole fit down with it.
    _write_sweep(
        store,
        "beta",
        ["time_sec", "rigidity", "depletion_nm", "status"],
        [{"time_sec": "5", "rigidity": "1", "depletion_nm": "220", "status": "success"}],
    )

    x, y, digest = load_tabular_dataset(_spec(store))
    assert x.shape == (2, 2), f"expected only alpha's 2 rows, got {x.shape}"
    assert y.shape == (2, 1)
    assert digest


@pytest.mark.contract
def test_store_with_only_foreign_sweeps_raises_with_a_useful_message(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_sweep(
        store,
        "beta",
        ["time_sec", "depletion_nm", "status"],
        [{"time_sec": "5", "depletion_nm": "220", "status": "success"}],
    )
    with pytest.raises(ValueError) as excinfo:
        load_tabular_dataset(_spec(store))
    message = str(excinfo.value)
    # Skipping must not become silent: the error has to name the inputs it wanted
    # and say that other models' sweeps were passed over.
    assert "['a', 'b']" in message, message
    assert "other models" in message, message


@pytest.mark.contract
def test_failed_rows_are_still_excluded(tmp_path: Path) -> None:
    """Filtering foreign sweeps must not have loosened the status filter."""
    store = tmp_path / "store"
    _write_sweep(
        store,
        "alpha",
        ["a", "b", "y", "status"],
        [
            {"a": "1", "b": "2", "y": "3", "status": "success"},
            {"a": "9", "b": "9", "y": "0", "status": "failed"},
        ],
    )
    x, _y, _d = load_tabular_dataset(_spec(store))
    assert x.shape == (1, 2), "a failed row was included in the training set"
    assert json.dumps(x.tolist())  # shape is what matters; keep the payload legible
