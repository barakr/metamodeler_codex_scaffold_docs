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
