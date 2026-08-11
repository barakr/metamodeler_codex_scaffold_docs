"""Typed metamodel specs for coupling and sampling."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MetamodelVariableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: Literal["scalar", "vector", "matrix"] = "scalar"
    shape: list[int] = Field(default_factory=list)
    support: list[float] | None = None
    units: str | None = None


class MetamodelCouplingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["gaussian_link", "equality_soft", "deterministic"]
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    transform: dict[str, Any] = Field(default_factory=lambda: {"kind": "identity"})
    sigma: float | None = None


class MetamodelPriorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variable: str = Field(min_length=1)
    distribution: dict[str, Any]


class MetaModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    ppl_backend: Literal["pymc", "numpyro"]
    surrogate_refs: list[str] = Field(min_length=1)
    variables: list[MetamodelVariableSpec] = Field(default_factory=list)
    couplings: list[MetamodelCouplingSpec] = Field(default_factory=list)
    priors: list[MetamodelPriorSpec] = Field(default_factory=list)
    # Variables whose value you KNOW, mapped to that value: `{"y": 4.0}`.
    #
    # Without this the metamodel layer could only ever draw the full joint. There was no
    # way to ask the question people actually bring to a metamodel — "given that I measured
    # this one quantity, what does that imply about the others?" — because there was
    # nowhere to say what was measured. Emulating it with a very tight prior is the
    # workaround it replaces, and that workaround is bad: it puts the posterior on a thin
    # ridge, which is exactly the geometry a coordinate-wise random walk cannot follow.
    #
    # An observed variable is clamped: never proposed, never drawn, held at its value while
    # every factor that mentions it is evaluated there.
    observed: dict[str, float] = Field(default_factory=dict)
