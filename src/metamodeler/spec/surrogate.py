"""Typed placeholder specs for surrogate workflows."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TrainingDataSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_store_root: str = Field(min_length=1)
    model_spec_ref: str = Field(min_length=1)
    input_variables: list[str] = Field(min_length=1)
    output_variable: str = Field(min_length=1)


class SurrogateConfigSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str = Field(min_length=1)
    backend: str = Field(min_length=1)
    objective: Literal["predictive_distribution", "mean_only"]


class SplitSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    train: float = Field(gt=0, lt=1)
    val: float = Field(gt=0, lt=1)
    test: float = Field(gt=0, lt=1)


class EvaluationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    splits: SplitSpec
    metrics: list[str] = Field(min_length=1)


class SurrogateReproducibilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int = Field(ge=0)


class SurrogateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    training_data: TrainingDataSpec
    surrogate: SurrogateConfigSpec
    evaluation: EvaluationSpec
    reproducibility: SurrogateReproducibilitySpec
