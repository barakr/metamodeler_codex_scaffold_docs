"""Compiler boundary for metamodel IR backends."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bayesian_metamodeling.meta.ir import (
    DEFAULT_COUPLING_SIGMA,
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    SurrogateLikelihoodFactorIR,
)
from bayesian_metamodeling.surrogates import SurrogateModel

_DETERMINISTIC_PENALTY = -1e6
_DETERMINISTIC_TOL = 1e-9


@dataclass
class CompiledMetaModel:
    backend: str
    ir: MetamodelIR

    def evaluate_log_prob(
        self, values: dict[str, float], surrogates: dict[str, SurrogateModel] | None = None
    ) -> float:
        surrogates = surrogates or {}
        total = 0.0
        for factor in self.ir.factors:
            if isinstance(factor, PriorFactorIR):
                dist_kind = factor.distribution.get("kind", "normal")
                if dist_kind == "normal":
                    loc = float(factor.distribution.get("loc", 0.0))
                    scale = float(factor.distribution.get("scale", 1.0))
                    x = float(values[factor.variable])
                    var = scale**2
                    total += -0.5 * (np.log(2 * np.pi * var) + ((x - loc) ** 2) / var)
            elif isinstance(factor, CouplingFactorIR):
                source = float(values[factor.source])
                target = float(values[factor.target])
                relation = factor.transform.get("kind", "identity")
                if relation == "identity":
                    transformed = source
                elif relation == "affine":
                    alpha = float(factor.transform.get("alpha", 1.0))
                    beta = float(factor.transform.get("beta", 0.0))
                    transformed = alpha * source + beta
                else:
                    transformed = source

                if factor.coupling_type == "deterministic_transform":
                    total += (
                        _DETERMINISTIC_PENALTY
                        if abs(target - transformed) > _DETERMINISTIC_TOL
                        else 0.0
                    )
                else:
                    sigma = float(factor.sigma or DEFAULT_COUPLING_SIGMA)
                    var = sigma**2
                    residual = target - transformed
                    total += -0.5 * (np.log(2 * np.pi * var) + (residual**2) / var)
            elif isinstance(factor, SurrogateLikelihoodFactorIR):
                surrogate = surrogates.get(factor.surrogate_ref)
                if surrogate is None:
                    # Keep a neutral contribution when surrogate payloads
                    # are not loaded in a sampling-only flow.
                    continue
                inputs = {name: np.array([values[name]], dtype=float) for name in factor.inputs}
                outputs = {name: np.array([values[name]], dtype=float) for name in factor.outputs}
                total += float(np.asarray(surrogate.log_prob(inputs, outputs)).reshape(-1)[0])
        return float(total)


def compile_metamodel(ir: MetamodelIR, backend: str = "pymc") -> CompiledMetaModel:
    if backend in {"pymc", "numpyro"}:
        return CompiledMetaModel(backend=backend, ir=ir)
    raise ValueError(f"Unsupported backend: {backend}")
