"""Backend-neutral metamodel intermediate representation (IR)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class VariableIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: Literal["scalar", "vector", "matrix"] = "scalar"
    shape: list[int] = Field(default_factory=list)
    support: list[float] | None = None
    units: str | None = None


class PriorFactorIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["prior"] = "prior"
    variable: str
    distribution: dict[str, Any]


class CouplingFactorIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["coupling"] = "coupling"
    coupling_type: Literal["equality_soft", "gaussian_link", "deterministic_transform"]
    source: str
    target: str
    transform: dict[str, Any] = Field(default_factory=lambda: {"kind": "identity"})
    sigma: float | None = None


class SurrogateLikelihoodFactorIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["surrogate_likelihood"] = "surrogate_likelihood"
    surrogate_ref: str
    inputs: list[str] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)


DEFAULT_COUPLING_SIGMA: float = 0.1


class MetamodelIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    name: str
    variables: list[VariableIR]
    factors: list[PriorFactorIR | CouplingFactorIR | SurrogateLikelihoodFactorIR]
    # Clamped variables: name -> known value. Not a factor, because it does not
    # contribute a term to the density — it removes a dimension from the sample space.
    # Defaulted so IR files written before conditioning existed still load.
    observed: dict[str, float] = Field(default_factory=dict)


def ir_to_json_dict(ir: MetamodelIR) -> dict[str, Any]:
    return ir.model_dump(mode="json", by_alias=True)


def ir_from_json_dict(payload: dict[str, Any]) -> MetamodelIR:
    return MetamodelIR.model_validate(payload)
