"""Typed ModelSpec and validation helpers."""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

# Fields that end up as a path *segment* must be safe to interpolate into one.
# `model.name` and `biomodels_id` are both used to build directories/filenames
# (`cli/main.py` builds `<storage.root>/_active/<token>/<name>_<i>`, which is
# `shutil.rmtree`'d in a `finally`; `adapters/biomodels_sbml.py` builds
# `<cache>/<biomodels_id>.xml`). Without this, a name containing `..` or a
# separator escapes the store — and in the first case takes a recursive delete
# with it. The realistic failure is not an attack (a spec already names the
# command to run) but an accident: a model called `lck/activity` silently
# writing, and then deleting, somewhere nobody looked.
#
# Same charset as `runner.execution_env.conda_env` below, deliberately: one rule
# for "this string becomes a path segment" is easier to remember than three.
_PATH_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _require_path_safe(value: str, *, field: str) -> str:
    if not _PATH_SAFE_SEGMENT.match(value):
        raise ValueError(
            f"{field} must start with a letter or digit and contain only letters, digits, "
            f"'.', '_' or '-' (it is used to build a directory or file name): {value!r}"
        )
    return value


def _reject_absolute_or_traversal(value: str, *, field: str) -> str:
    """Reject absoluteness and `..` under BOTH POSIX and Windows conventions.

    Platform-independent on purpose: without the double check, `/tmp/x` slips
    through on Windows (pathlib treats it as drive-relative, not absolute) and
    `C:\\x` / UNC paths slip through on POSIX. The explicit leading-separator
    test catches drive-less rooted paths like `\\foo`, which Windows pathlib
    does not flag as absolute even though they unambiguously escape.
    """
    if (
        PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or value.startswith(("/", "\\"))
    ):
        raise ValueError(f"{field} must be a project-relative path")
    # Split on either separator so `..\foo` is caught on POSIX and `../foo` on Windows.
    if ".." in value.replace("\\", "/").split("/"):
        raise ValueError(f"{field} must not contain directory traversal (..) sequences")
    return value


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

    @field_validator("biomodels_id")
    @classmethod
    def check_biomodels_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _require_path_safe(value, field="model.artifact.biomodels_id")

    @field_validator("local_sbml_path")
    @classmethod
    def check_local_sbml_path(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _reject_absolute_or_traversal(value, field="model.artifact.local_sbml_path")

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

    @field_validator("name")
    @classmethod
    def check_name_is_path_safe(cls, value: str) -> str:
        return _require_path_safe(value, field="model.name")


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


class SobolDesignSpec(BaseModel):
    """Typed Sobol configuration (D4).

    This was `dict[str, Any]` — the only untyped object in an otherwise strictly-validated
    spec tree — and the planner read exactly three keys from it with `.get()`. Anything else
    was silently ignored, which is how both research specs came to carry a `ranges` key that
    nothing reads. See `ModelSpec.check_design_against_io_schema` for what happens to it now.
    """

    model_config = ConfigDict(extra="forbid")

    n_points: int = Field(ge=1)
    #: Default `False` preserves every number this project has already produced. Note that
    #: **scipy's own default is `True`**, so a reader who knows `qmc.Sobol` will expect the
    #: opposite; with `scramble=False` the first point is exactly the lower corner of the
    #: box (every variable at its minimum). Tutorial 4 teaches this.
    scramble: bool = False
    seed: int | None = None
    #: Accepted, and cross-checked against `io_schema.inputs[].support` rather than used.
    #: See the class docstring and the ModelSpec validator.
    ranges: dict[str, list[float]] | None = None


class DesignSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["grid", "sobol"]
    grid: dict[str, list[float]] | None = None
    sobol: SobolDesignSpec | None = None

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
        return _reject_absolute_or_traversal(value, field="storage.root")


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

    @model_validator(mode="after")
    def check_design_against_io_schema(self) -> "ModelSpec":
        """The design and the I/O schema must agree — D5, and the `ranges` trap in D4.

        Nothing previously connected these two halves of a spec, so a design could name a
        variable that does not exist, sample outside a variable's declared support, or (the
        one that actually happened) declare bounds in a key the planner never reads. Each
        failed late and unhelpfully, or not at all.
        """
        declared = {variable.name: variable for variable in self.io_schema.inputs}

        if self.design.strategy == "grid" and self.design.grid:
            unknown = sorted(set(self.design.grid) - set(declared))
            if unknown:
                raise ValueError(
                    f"design.grid names variables that are not declared in io_schema.inputs: "
                    f"{unknown}. Declared inputs are {sorted(declared)}. (Previously this "
                    f'failed mid-sweep as "Missing input variable", once per design point.)'
                )
            for name, values in self.design.grid.items():
                support = declared[name].support
                if support is None:
                    continue
                outside = [v for v in values if not (support[0] <= v <= support[1])]
                if outside:
                    raise ValueError(
                        f"design.grid['{name}'] contains values outside the declared support "
                        f"{support}: {outside}. Either widen io_schema support or correct the "
                        f"grid — sampling outside the domain a model declares is not a "
                        f"decision that should be made silently."
                    )

        if self.design.strategy == "sobol" and self.design.sobol is not None:
            unknown = sorted(set(self.design.sobol.ranges or {}) - set(declared))
            if unknown:
                raise ValueError(
                    f"design.sobol.ranges names variables that are not declared in "
                    f"io_schema.inputs: {unknown}. Declared inputs are {sorted(declared)}."
                )
            # `ranges` is NOT read by the planner — Sobol bounds come from
            # `io_schema.inputs[].support`. Rather than forbid the key (which would reject
            # specs that already ship, in a *separate repository*) or start honouring it
            # (two sources of truth for one number), require the two to agree. Divergence
            # then fails at validation instead of silently sampling a region nobody asked
            # for, and a spec author who edits the obvious-looking place is told.
            for name, bounds in (self.design.sobol.ranges or {}).items():
                support = declared[name].support
                if support is None:
                    raise ValueError(
                        f"design.sobol.ranges['{name}'] is set but io_schema declares no "
                        f"support for '{name}'. Sobol bounds are taken from io_schema.support, "
                        f"so the range would be ignored."
                    )
                if [float(b) for b in bounds] != [float(s) for s in support]:
                    raise ValueError(
                        f"design.sobol.ranges['{name}'] is {bounds} but "
                        f"io_schema.inputs['{name}'].support is {support}, and **support is "
                        f"what the planner actually samples**. These must agree. Edit "
                        f"io_schema support (or remove the redundant ranges entry) — "
                        f"otherwise the spec says one thing and the sweep does another."
                    )

        return self


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
