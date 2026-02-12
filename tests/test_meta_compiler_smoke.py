import numpy as np

from metamodeler.meta import compile_metamodel
from metamodeler.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    SurrogateLikelihoodFactorIR,
    VariableIR,
)


class DummySurrogate:
    def sample(self, inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray:
        x = inputs["x"]
        rng = np.random.default_rng(seed)
        return rng.normal(loc=x[:, None], scale=0.1, size=(len(x), n))

    def log_prob(self, inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray:
        x = inputs["x"]
        y = outputs["y"]
        return -((y - x) ** 2)

    def summary(self, inputs: dict[str, np.ndarray]) -> dict:
        return {"n": int(len(inputs["x"]))}


def test_compile_ir_pymc_smoke_with_surrogate_factor():
    ir = MetamodelIR(
        name="smoke",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(variable="x", distribution={"kind": "normal", "loc": 0.0, "scale": 1.0}),
            CouplingFactorIR(
                coupling_type="gaussian_link",
                source="x",
                target="y",
                transform={"kind": "identity"},
                sigma=0.3,
            ),
            SurrogateLikelihoodFactorIR(
                surrogate_ref="s0",
                inputs=["x"],
                outputs=["y"],
            ),
        ],
    )

    compiled = compile_metamodel(ir, backend="pymc")
    score = compiled.evaluate_log_prob({"x": 0.2, "y": 0.25}, surrogates={"s0": DummySurrogate()})

    assert np.isfinite(score)


def test_compile_ir_numpyro_stub_is_clear():
    ir = MetamodelIR(name="stub", variables=[VariableIR(name="x")], factors=[])
    compiled = compile_metamodel(ir, backend="numpyro")
    assert compiled.backend == "numpyro"
