"""IR builder from metamodel spec."""

from __future__ import annotations

from metamodeler.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    SurrogateLikelihoodFactorIR,
    VariableIR,
)
from metamodeler.spec import MetaModelSpec


def build_ir_from_metamodel_spec(spec: MetaModelSpec) -> MetamodelIR:
    variable_names: set[str] = set()
    factors = []

    for link in spec.links:
        src = f"{link.from_.model}.{link.from_.var}"
        tgt = f"{link.to.model}.{link.to.var}"
        variable_names.add(src)
        variable_names.add(tgt)
        relation = link.relation if isinstance(link.relation, dict) else {"kind": "identity"}
        coupling_type = "gaussian_link"
        if relation.get("kind") == "identity":
            coupling_type = "equality_soft"
        factors.append(
            CouplingFactorIR(
                coupling_type=coupling_type,
                source=src,
                target=tgt,
                transform=relation,
                sigma=0.1,
            )
        )

    for model in spec.models:
        factors.append(
            SurrogateLikelihoodFactorIR(
                surrogate_ref=model.surrogate_artifact,
                inputs=[name for name in sorted(variable_names)[:1]] or ["placeholder_input"],
                outputs=[name for name in sorted(variable_names)[-1:]] or ["placeholder_output"],
            )
        )

    variables = [VariableIR(name=name) for name in sorted(variable_names)]

    for coupling_var in spec.coupling_variables:
        variables.append(VariableIR(name=coupling_var.name))

    return MetamodelIR(name=spec.name, variables=variables, factors=factors)
