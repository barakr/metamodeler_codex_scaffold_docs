"""DOE checks for a project that teaches DOE (D4, D5).

Nothing previously connected the two halves of a spec: `design` could name a variable
`io_schema` never declared, sample outside a declared support, or describe bounds in a key
the planner does not read. Each failed late, unhelpfully, or not at all.

The `ranges` case is the one with scientific consequence and is the reason this file exists.
Both research specs in `projects/tcr_signaling` carry `design.sobol.ranges`. The planner
takes Sobol bounds from `io_schema.inputs[].support` and has never read `ranges`. They agree
today — checked, all 8 variables — so no sweep has been wrong. But nothing made them agree,
and `ranges` is the more natural-looking place to edit.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bayesian_metamodeling.designs import plan_points
from bayesian_metamodeling.designs.planner import SobolBalanceWarning
from bayesian_metamodeling.spec import load_and_validate_modelspec


def _spec(**design) -> dict:
    payload = copy.deepcopy(
        json.loads(Path("examples/toy_program/spec.toy_program.json").read_text())
    )
    payload["design"] = design
    return payload


class TestGridAgreesWithIOSchema:
    def test_rejects_a_grid_variable_that_is_not_a_declared_input(self):
        payload = _spec(strategy="grid", grid={"a": [1.0], "not_an_input": [2.0]})
        with pytest.raises(ValidationError, match="not declared in io_schema.inputs"):
            load_and_validate_modelspec(payload)

    def test_rejects_grid_values_outside_the_declared_support(self):
        """Sampling outside the domain a model declares should not be a silent decision."""
        payload = _spec(strategy="grid", grid={"a": [0.0, 999.0], "b": [1.0]})
        with pytest.raises(ValidationError, match="outside the declared support"):
            load_and_validate_modelspec(payload)

    def test_accepts_a_grid_inside_support(self):
        payload = _spec(strategy="grid", grid={"a": [1.0, 2.0], "b": [1.0]})
        assert load_and_validate_modelspec(payload).design.grid["a"] == [1.0, 2.0]


class TestSobolRangesMustAgreeWithSupport:
    """The trap: two places declare the same bounds, only one is read."""

    def _support_of(self, payload: dict, name: str) -> list[float]:
        return next(v["support"] for v in payload["io_schema"]["inputs"] if v["name"] == name)

    def test_rejects_ranges_that_disagree_with_support(self):
        payload = _spec(strategy="sobol", sobol={"n_points": 8, "ranges": {"a": [0.0, 99.0]}})
        with pytest.raises(ValidationError, match="support is what the planner actually samples"):
            load_and_validate_modelspec(payload)

    def test_accepts_ranges_that_agree(self):
        payload = _spec(strategy="sobol", sobol={"n_points": 8})
        payload["design"]["sobol"]["ranges"] = {"a": self._support_of(payload, "a")}
        assert load_and_validate_modelspec(payload).design.sobol.ranges is not None

    def test_rejects_ranges_for_an_undeclared_variable(self):
        payload = _spec(strategy="sobol", sobol={"n_points": 8, "ranges": {"nope": [0.0, 1.0]}})
        with pytest.raises(ValidationError, match="not declared in io_schema.inputs"):
            load_and_validate_modelspec(payload)

    def test_the_shipped_research_specs_still_validate(self):
        """The two specs that carry `ranges` must keep working — they are in another repo."""
        specs = sorted(Path("projects/tcr_signaling/specs").glob("model.*.json"))
        if not specs:
            pytest.skip("tcr_signaling submodule is not checked out")
        checked = 0
        for path in specs:
            payload = json.loads(path.read_text())
            if payload.get("design", {}).get("strategy") != "sobol":
                continue
            load_and_validate_modelspec(payload)
            checked += 1
        assert checked >= 1, "expected at least one sobol research spec to exercise this"


class TestSobolBalanceWarning:
    def test_warns_when_n_is_not_a_power_of_two(self):
        payload = _spec(strategy="sobol", sobol={"n_points": 9})
        spec = load_and_validate_modelspec(payload)
        with pytest.warns(SobolBalanceWarning, match="not a power of 2"):
            points = plan_points(spec)
        assert len(points) == 9, "the design is still produced — this is a quality note"

    def test_suggests_the_neighbouring_powers_of_two(self):
        spec = load_and_validate_modelspec(_spec(strategy="sobol", sobol={"n_points": 9}))
        with pytest.warns(SobolBalanceWarning, match=r"Consider 8 or 16"):
            plan_points(spec)

    def test_silent_at_a_power_of_two(self):
        import warnings

        spec = load_and_validate_modelspec(_spec(strategy="sobol", sobol={"n_points": 16}))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert len(plan_points(spec)) == 16


def test_unscrambled_sobol_starts_at_the_corner_of_the_box():
    """Pins the behaviour Tutorial 4 teaches, and the reason the default differs from scipy.

    `scramble` defaults to False here and True in `scipy.stats.qmc.Sobol`. Unscrambled, the
    first point is the all-zeros vector, which maps to every variable's *minimum* — rarely
    what someone sampling a design space intends for point 1.
    """
    spec = load_and_validate_modelspec(
        _spec(strategy="sobol", sobol={"n_points": 8, "scramble": False})
    )
    first = plan_points(spec)[0]
    supports = {v.name: v.support for v in spec.io_schema.inputs}
    for name, value in first.items():
        assert value == pytest.approx(supports[name][0]), (
            f"unscrambled Sobol point 1 should sit at {name}'s lower bound"
        )
