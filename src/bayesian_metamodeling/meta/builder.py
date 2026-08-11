"""IR builder from metamodel spec."""

from __future__ import annotations

import json
from pathlib import Path

from bayesian_metamodeling.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    SurrogateLikelihoodFactorIR,
    VariableIR,
)
from bayesian_metamodeling.spec import MetaModelSpec
from bayesian_metamodeling.storage.surrogate_store import SURROGATE_REGISTRY_PATH


def _resolve_surrogate_ref(ref: str) -> tuple[str, dict]:
    path = Path(ref)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload["artifact_id"], payload

    if SURROGATE_REGISTRY_PATH.exists():
        registry = json.loads(SURROGATE_REGISTRY_PATH.read_text(encoding="utf-8"))
        if ref in registry:
            artifact_path = Path(registry[ref])
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            return payload["artifact_id"], payload

    raise ValueError(f"Could not resolve surrogate_ref: {ref}")


def build_ir_from_metamodel_spec(spec: MetaModelSpec) -> MetamodelIR:
    factors = []

    variable_map: dict[str, VariableIR] = {}
    for variable in spec.variables:
        variable_map[variable.name] = VariableIR(
            name=variable.name,
            type=variable.type,
            shape=variable.shape,
            support=variable.support,
            units=variable.units,
        )

    for prior in spec.priors:
        factors.append(PriorFactorIR(variable=prior.variable, distribution=prior.distribution))
        variable_map.setdefault(prior.variable, VariableIR(name=prior.variable))

    for coupling in spec.couplings:
        c_type = coupling.kind
        if c_type == "deterministic":
            c_type = "deterministic_transform"
        factors.append(
            CouplingFactorIR(
                coupling_type=c_type,
                source=coupling.source,
                target=coupling.target,
                transform=coupling.transform,
                sigma=coupling.sigma,
            )
        )
        variable_map.setdefault(coupling.source, VariableIR(name=coupling.source))
        variable_map.setdefault(coupling.target, VariableIR(name=coupling.target))

    for ref in spec.surrogate_refs:
        surrogate_id, artifact = _resolve_surrogate_ref(ref)
        var_lists = artifact.get("variable_lists", {})
        inputs = list(var_lists.get("inputs", []))
        outputs = list(var_lists.get("outputs", []))
        if not inputs or not outputs:
            raise ValueError(f"Surrogate artifact missing variable lists: {ref}")

        for name in inputs + outputs:
            variable_map.setdefault(name, VariableIR(name=name))

        factors.append(
            SurrogateLikelihoodFactorIR(
                surrogate_ref=surrogate_id,
                inputs=inputs,
                outputs=outputs,
            )
        )

    observed = dict(spec.observed)
    for name in observed:
        variable_map.setdefault(name, VariableIR(name=name))

    # A deterministic coupling COMPUTES its target from its source. Observing that same
    # target asserts a second, independent value for it. One of the two must lose, and
    # silently picking either would be worse than refusing: the sampler would report
    # perfectly healthy draws for a model that cannot be satisfied.
    computed = {
        factor.target
        for factor in factors
        if isinstance(factor, CouplingFactorIR)
        and factor.coupling_type == "deterministic_transform"
    }
    conflict = sorted(computed & set(observed))
    if conflict:
        raise ValueError(
            f"cannot observe {conflict}: each is the target of a deterministic coupling, so "
            "its value is computed from its source rather than free to be set. Observe the "
            "coupling's SOURCE instead, or make the coupling a gaussian_link so the target "
            "has room to disagree with what you measured."
        )

    return MetamodelIR(
        name=spec.name,
        variables=list(variable_map.values()),
        factors=factors,
        observed=observed,
    )
