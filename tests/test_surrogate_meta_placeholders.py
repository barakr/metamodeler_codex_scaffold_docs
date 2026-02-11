import copy
import json
from pathlib import Path

from metamodeler.cli.main import main


def test_mm_surrogate_fit_placeholder(monkeypatch, capsys):
    spec_path = Path("examples/biomodels/surrogate.model1907260003.json")

    monkeypatch.setattr("sys.argv", ["mm", "surrogate", "fit", str(spec_path)])
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Placeholder: surrogate fit is not implemented yet" in out


def test_mm_surrogate_eval_placeholder(monkeypatch, capsys):
    spec_path = Path("examples/biomodels/surrogate.model1907260003.json")

    monkeypatch.setattr("sys.argv", ["mm", "surrogate", "eval", str(spec_path)])
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Placeholder: surrogate eval is not implemented yet" in out


def test_mm_meta_build_placeholder(monkeypatch, capsys):
    spec_path = Path("examples/coupled/spec.three_model_coupling.json")

    monkeypatch.setattr("sys.argv", ["mm", "meta", "build", str(spec_path)])
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Metamodel IR artifact stored:" in out


def test_mm_surrogate_fit_invalid_spec_fails(monkeypatch, capsys, tmp_path):
    payload = json.loads(Path("examples/biomodels/surrogate.model1907260003.json").read_text())
    bad_payload = copy.deepcopy(payload)
    del bad_payload["name"]

    bad_path = tmp_path / "bad_surrogate.json"
    bad_path.write_text(json.dumps(bad_payload))

    monkeypatch.setattr("sys.argv", ["mm", "surrogate", "fit", str(bad_path)])
    code = main()
    out = capsys.readouterr().out

    assert code == 1
    assert "Spec validation failed:" in out
