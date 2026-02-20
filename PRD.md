# PRD: Metamodeling Automation Framework

## Product vision
Build a CLI-first framework for probabilistic metamodeling:
1) Execute several independent source models across many input combinations.
2) Learn a surrogate probability model for each source model.
3) Build a joint distribution across surrogates using explicit coupling variables and constraints.

The first release is focused on deterministic, reproducible execution and data generation. Advanced surrogate families and full Bayesian coupling are staged after a reliable execution core exists.

## Context and motivation
Current workflows are manual and brittle:
- Each source model has custom run commands and I/O layout.
- Parameter mapping, units, and array dimensions drift over time.
- Provenance is incomplete, making reruns and comparisons difficult.
- Surrogate training pipelines are ad hoc and hard to reuse.

This project standardizes execution and data contracts first, then layers probabilistic modeling on top.

## Target users
- Research scientist: wants to evaluate many model combinations and later compose a joint metamodel.
- Applied ML engineer: wants reusable surrogate training/evaluation workflows.
- Platform developer: wants to add new model adapters without touching core runner logic.

## Problem statement
Need a framework that can:
- Run heterogeneous model programs from a single typed spec.
- Generate canonical datasets suitable for surrogate learning.
- Capture strict provenance and reproducibility metadata.
- Support later composition into coupled probabilistic metamodels.

## Scope
### In scope for v1
- JSON-first `ModelSpec` for model execution.
- Adapter plugin interface for model-specific I/O translation.
- Local process runner.
- DOE planning (`grid`, `sobol`) for input sweeps.
- Canonical run store with:
  - input/output artifacts,
  - full stdout/stderr logs,
  - seed and digest metadata,
  - deterministic cache keys.
- Centralized sweep-result artifact for DOE execution:
  - one aggregated table per sweep (initial format: CSV),
  - no separate output file/folder per grid point for numeric results,
  - stable row identity (`point_index`) for reproducibility and joins.
- Local sweep execution modes:
  - serial mode,
  - local parallel mode,
  - MPI-coordinated mode with synchronized writes to one centralized sweep artifact.
- CLI commands: validate, plan, run, runs list/show.
- Two examples: toy CLI model and BioModels SBML spec stub.
- Notebook-first onboarding curriculum:
  - Tutorial 0 hub + Tutorial 1-9 progression.
  - Standalone and serial paths for new lab members.
  - Light scientific concept in each tutorial, aligned to package actions.
  - Guided narrative + visual checkpoints (plots/graphics) for each tutorial.

### Out of scope for v1
- Production-grade joint Bayesian inference.
- Full HPC/cloud execution support (only interfaces/stubs).
- Web UI.
- Auto-tuning/auto-downsampling/implicit compute shortcuts.

## Functional requirements
- FR1: User can validate a spec before execution.
- FR2: User can generate a deterministic DOE plan from a spec.
- FR3: User can run a model sweep and persist canonical results.
- FR4: User can replay the same run plan with exact provenance.
- FR5: User can inspect run metadata and logs from CLI.
- FR6: Adapter API is minimal and typed, with contract tests.
- FR7: DOE sweep results are persisted in one centralized, tabular artifact per sweep (CSV in the first rollout).
- FR8: The same centralized output contract is used in serial, local parallel, and MPI execution modes.
- FR9: Tutorial 1 demonstrates centralized sweep output by plotting both toy outputs (`sum`, `product`) as heatmaps.

## Non-functional requirements
- NFR1: Fast local test suite under 30 seconds (`not slow` marker set).
- NFR2: No silent downsampling or data reduction.
- NFR3: All model runs persist stdout/stderr and seed.
- NFR4: Schema and shape mismatches fail early with clear errors.
- NFR5: Documentation files remain synchronized (`PRD.md`, `TechSpec.md`, `Status.md`, `README.md`).
- NFR6: Tutorials are delivered as Jupyter notebooks (`.ipynb`) and are runnable in a conda-based workflow.
- NFR7: Tutorial notebooks avoid manual placeholders when practical (auto-select run IDs/artifacts for smoother onboarding).
- NFR8: Centralized sweep output must be deterministic and mergeable across execution modes (stable `point_index` ordering).
- NFR9: Parallel/MPI synchronization must avoid row corruption and partial-write ambiguity in the centralized artifact.
- NFR10: Optional-backend fast tests must be resilient to environment/toolchain limits (skip/fallback with explicit reason when backend runtime is unavailable, while still validating available backends).

## User stories
- US1: As a researcher, I define one `ModelSpec` and run it without writing glue code.
- US2: As a researcher, I can rerun with the same seed/spec and reproduce outputs.
- US3: As a developer, I can add an adapter in one module with contract tests.
- US4: As an ML engineer, I can consume canonical run outputs for surrogate training.
- US5: As a user, I can inspect failed runs through stored stderr and provenance.
- US6: As a lab member, I can onboard via tutorial notebooks and complete progressively harder tasks without reading source code first.
- US7: As a modeler, I can load one sweep CSV and directly analyze full response surfaces without traversing per-point run folders.

## Success metrics
- SM1: New simple model integration in under 2 engineering hours.
- SM2: 100 percent of runs contain seed, spec digest, artifact digest, stdout, stderr.
- SM3: Shape/unit mapping errors are caught before long run execution.
- SM4: 10k-point planning and cached re-run workflow supported without schema drift.
- SM5: New lab member can complete Tutorials 1-3 in one session and produce one interpreted scientific result.
- SM6: Tutorial execution blockers discovered by dry-run are patched with regression tests before onboarding release.
- SM7: Tutorial 1 produces two heatmaps (`sum`, `product`) from one centralized sweep artifact with no per-point output traversal.

## Risks and mitigations
- Risk: Time-series outputs have inconsistent dimensions.
  - Mitigation: Strict canonical output schema + validation before storage.
- Risk: Surrogate uncertainty is miscalibrated.
  - Mitigation: Stage surrogate choices behind explicit evaluation contracts.
- Risk: BioModels/SBML edge cases.
  - Mitigation: Mark as slow/integration and isolate adapter-specific tests.
- Risk: Parallel/MPI writes to one artifact can cause races or nondeterministic row ordering.
  - Mitigation: single-writer synchronization model + deterministic finalize step keyed by `point_index`.

## Roadmap
- Phase 0: scaffold + typed specs + hooks + basic tests.
- Phase 1: DOE + local runner + canonical run store + toy end-to-end.
- Phase 1.5: Centralized sweep artifact + synchronized serial/parallel/MPI write path + Tutorial 1 heatmap upgrade.
- Phase 2: BioModels adapter milestone + slow integration tests.
- Phase 3: Surrogate training baseline (single-model).
- Phase 4: Coupling spec and joint metamodel builder (multi-model).
- Phase 5: Calibration diagnostics, docs hardening, and packaging polish.
