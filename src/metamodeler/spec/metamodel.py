"""Typed placeholder specs for metamodel build workflows."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CoupledModelRefSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    surrogate_artifact: str = Field(min_length=1)


class CouplingVariableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    distribution: dict


class CouplingLinkEndpointSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    var: str = Field(min_length=1)


class CouplingLinkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_: CouplingLinkEndpointSpec = Field(alias="from")
    to: CouplingLinkEndpointSpec
    relation: dict


class MetaModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    models: list[CoupledModelRefSpec] = Field(min_length=1)
    coupling_variables: list[CouplingVariableSpec] = Field(default_factory=list)
    links: list[CouplingLinkSpec] = Field(default_factory=list)
    constraints: list[dict] = Field(default_factory=list)
