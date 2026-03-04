import json
from pathlib import Path

from bayesian_metamodeling.cli.main import main
from bayesian_metamodeling.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    VariableIR,
    ir_from_json_dict,
    ir_to_json_dict,
)


def test_meta_ir_roundtrip_serialization():
    ir = MetamodelIR(
        name="roundtrip",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=[
            CouplingFactorIR(
                coupling_type="equality_soft",
                source="x",
                target="y",
                transform={"kind": "identity"},
                sigma=0.1,
            )
        ],
    )

    payload = ir_to_json_dict(ir)
    restored = ir_from_json_dict(payload)

    assert restored.name == ir.name
    assert restored.model_dump(mode="json") == ir.model_dump(mode="json")


def test_mm_meta_build_outputs_ir_artifact(monkeypatch, capsys, tmp_path):
    spec_path = Path("examples/coupled/spec.three_model_coupling.json")

    monkeypatch.setattr("sys.argv", ["mm", "meta", "build", str(spec_path)])
    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Metamodel IR artifact stored:" in out
    assert Path("tmp/meta_registry.json").exists()

    registry = json.loads(Path("tmp/meta_registry.json").read_text())
    assert registry
    artifact_meta = Path(next(iter(registry.values())))
    assert artifact_meta.exists()
