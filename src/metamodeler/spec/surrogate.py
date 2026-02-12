"""Typed surrogate workflow specs (backend-neutral)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from metamodeler.surrogate_config import validate_backend_config


class SurrogateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["conditional", "joint"]
    inputs: list[str] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)
    backend: Literal["pymc_gp", "sbi_npe", "numpyro_gp"]
    backend_config: dict[str, Any] = Field(default_factory=dict)
    dataset_ref: str | dict[str, Any]
    seed: int = Field(ge=0)
    summary_config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_backend_contract(self) -> SurrogateSpec:
        validate_backend_config(self.backend, self.backend_config)
        if len(self.outputs) != 1:
            raise ValueError(
                "Surrogate learning currently supports exactly one output variable. "
                f"Got outputs={self.outputs}."
            )
        return self
