import copy
import json
from pathlib import Path

from bayesian_metamodeling.cli.main import main
from bayesian_metamodeling.designs import plan_points
from bayesian_metamodeling.spec import load_and_validate_modelspec


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_grid_plan_count_is_cartesian_product():
    payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    spec = load_and_validate_modelspec(payload)

    points = plan_points(spec)

    assert len(points) == 9
    assert points[0] == {"a": 0.0, "b": 0.0}


def test_sobol_points_stay_within_input_support_and_are_deterministic():
    payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    payload["design"] = {
        "strategy": "sobol",
        "sobol": {"n_points": 8, "seed": 7, "scramble": False},
    }

    spec = load_and_validate_modelspec(payload)

    points_a = plan_points(spec)
    points_b = plan_points(spec)

    assert points_a == points_b
    assert len(points_a) == 8

    for point in points_a:
        assert 0.0 <= point["a"] <= 2.0
        assert 0.0 <= point["b"] <= 2.0


def test_mm_plan_prints_count_and_preview(monkeypatch, capsys, tmp_path):
    payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    payload["design"] = {
        "strategy": "sobol",
        "sobol": {"n_points": 4, "seed": 3, "scramble": False},
    }
    spec_path = tmp_path / "sobol_spec.json"
    spec_path.write_text(json.dumps(payload))

    monkeypatch.setattr("sys.argv", ["mm", "plan", str(spec_path)])
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Plan points: 4" in out
    assert "Preview:" in out


def test_mm_plan_fails_when_sobol_points_missing(monkeypatch, capsys, tmp_path):
    payload = _read_json(Path("examples/toy_program/spec.toy_program.json"))
    payload = copy.deepcopy(payload)
    payload["design"] = {"strategy": "sobol", "sobol": {"seed": 5}}
    spec_path = tmp_path / "bad_sobol.json"
    spec_path.write_text(json.dumps(payload))

    monkeypatch.setattr("sys.argv", ["mm", "plan", str(spec_path)])
    code = main()
    out = capsys.readouterr().out

    assert code == 1
    assert "DOE planning failed" in out
