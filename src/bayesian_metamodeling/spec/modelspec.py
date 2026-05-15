"""Typed ModelSpec and validation helpers."""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ArtifactSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["local", "biomodels"]
    entrypoint: list[str] | None = None
    biomodels_id: str | None = None
    source_url: str | None = None
    # Optional path (relative to the spec / repo) to a local SBML file used as
    # the source-of-truth instead of the BioModels HTTP download. When set, the
    # adapter copies this file into the per-spec cache the first time it's
    # materialized, so a tutorial can ship a reproducible sample SBML in-tree
    # and run with no network. Compatible with `MM_BIOMODELS_OFFLINE=1`.
    local_sbml_path: str | None = None

    @model_validator(mode="after")
    def check_required_fields(self) -> "ArtifactSpec":
        if self.type == "local" and not self.entrypoint:
            raise ValueError(
                "model.artifact.entrypoint is required when model.artifact.type is 'local'"
            )
        if self.type == "biomodels" and not self.biomodels_id:
            raise ValueError(
                "model.artifact.biomodels_id is required when model.artifact.type is 'biomodels'"
            )
        return self


class ModelInfoSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    artifact: ArtifactSpec


class RunnerResourcesSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpus: int = Field(ge=1)
    mem_gb: int = Field(ge=1)
    walltime_min: int = Field(ge=1)


class RunnerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["local_process", "container", "hpc", "http"]
    resources: RunnerResourcesSpec
    execution_env: dict[str, str] = Field(default_factory=dict)
    sweep_mode: Literal["serial", "parallel_local", "mpi"] = "serial"
    workers: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_execution_env(self) -> "RunnerSpec":
        allowed = {"conda_env"}
        unknown = sorted(set(self.execution_env) - allowed)
        if unknown:
            raise ValueError(
                f"runner.execution_env contains unsupported keys: {unknown}. "
                "Allowed keys: ['conda_env']."
            )
        if "conda_env" in self.execution_env:
            conda_env = self.execution_env["conda_env"].strip()
            if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$", conda_env):
                raise ValueError(f"Invalid conda environment name: {conda_env!r}")
            self.execution_env["conda_env"] = conda_env
        if self.sweep_mode != "parallel_local" and self.workers is not None:
            raise ValueError(
                "runner.workers is supported only when runner.sweep_mode='parallel_local'."
            )
        if self.sweep_mode == "parallel_local" and self.workers is None:
            self.workers = max(1, self.resources.cpus)
        return self


class VariableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: Literal["float", "int", "array", "string", "bool"]
    units: str = Field(min_length=1)
    support: list[float] | None = None
    dims: list[str] | None = None

    @field_validator("support")
    @classmethod
    def check_support(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return value
        if len(value) != 2:
            raise ValueError("support must contain exactly [min, max]")
        if value[1] <= value[0]:
            raise ValueError("support max must be greater than support min")
        return value

    @model_validator(mode="after")
    def check_dims_for_array(self) -> "VariableSpec":
        if self.type == "array" and not self.dims:
            raise ValueError("dims must be provided when variable type is 'array'")
        return self


class TimeGridSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t0: float
    t1: float
    dt: float | None = None
    n_points: int | None = None

    @model_validator(mode="after")
    def check_time_grid(self) -> "TimeGridSpec":
        if self.t1 <= self.t0:
            raise ValueError("time_grid.t1 must be greater than time_grid.t0")
        has_dt = self.dt is not None
        has_n_points = self.n_points is not None
        if has_dt == has_n_points:
            raise ValueError("time_grid must provide exactly one of dt or n_points")
        if self.dt is not None and self.dt <= 0:
            raise ValueError("time_grid.dt must be positive")
        if self.n_points is not None and self.n_points < 2:
            raise ValueError("time_grid.n_points must be >= 2")
        return self


class IOSchemaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: list[VariableSpec] = Field(min_length=1)
    outputs: list[VariableSpec] = Field(min_length=1)
    time_grid: TimeGridSpec | None = None


class DesignSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["grid", "sobol"]
    grid: dict[str, list[float]] | None = None
    sobol: dict[str, Any] | None = None

    @model_validator(mode="after")
    def check_strategy_config(self) -> "DesignSpec":
        if self.strategy == "grid" and not self.grid:
            raise ValueError("design.grid is required when design.strategy is 'grid'")
        if self.strategy == "sobol" and not self.sobol:
            raise ValueError("design.sobol is required when design.strategy is 'sobol'")
        return self


class MappingEndpointSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1)
    key: str | None = None
    path: str | None = None


class MappingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    var: str = Field(min_length=1)
    to: MappingEndpointSpec | None = None
    from_: MappingEndpointSpec | None = Field(default=None, alias="from")

    @model_validator(mode="after")
    def check_direction(self) -> "MappingSpec":
        if (self.to is None) == (self.from_ is None):
            raise ValueError("mapping must contain exactly one of 'to' or 'from'")
        return self


class AdapterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    input_mapping: list[MappingSpec] = Field(default_factory=list)
    output_mapping: list[MappingSpec] = Field(default_factory=list)


class ReproducibilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int = Field(ge=0)


class StorageSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = Field(min_length=1)

    @field_validator("root")
    @classmethod
    def check_not_absolute(cls, value: str) -> str:
        # Reject absoluteness under EITHER POSIX or Windows conventions so the
        # rule is platform-independent. Without this, `/tmp/x` would slip
        # through on Windows (pathlib treats it as drive-relative, not
        # absolute) and `C:\x` / UNC paths would slip through on POSIX. Also
        # catch a leading `/` or `\` explicitly, since Windows pathlib does
        # not flag drive-less rooted paths like `\foo` as absolute even
        # though they unambiguously try to escape relativeness.
        if (
            PurePosixPath(value).is_absolute()
            or PureWindowsPath(value).is_absolute()
            or value.startswith(("/", "\\"))
        ):
            raise ValueError("storage.root must be a project-relative path")
        # Same idea for parent-directory traversal: split on either separator
        # so `..\foo` is caught on POSIX and `../foo` is caught on Windows.
        parts = value.replace("\\", "/").split("/")
        if ".." in parts:
            raise ValueError("storage.root must not contain directory traversal (..) sequences")
        return value


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(min_length=1)
    model: ModelInfoSpec
    runner: RunnerSpec
    io_schema: IOSchemaSpec
    design: DesignSpec
    adapter: AdapterSpec
    reproducibility: ReproducibilitySpec
    storage: StorageSpec


class ModelSpecValidationError(ValueError):
    """Raised when ModelSpec validation fails with formatted details."""


def load_and_validate_modelspec(payload: dict[str, Any]) -> ModelSpec:
    """Validate an in-memory ModelSpec payload."""
    return ModelSpec.model_validate(payload)


def format_validation_error(error: ValidationError) -> str:
    """Render clear, actionable validation errors."""
    lines: list[str] = ["Spec validation failed:"]
    for item in error.errors():
        loc = ".".join(str(part) for part in item["loc"])
        lines.append(f"- {loc}: {item['msg']}")
    return "\n".join(lines)
