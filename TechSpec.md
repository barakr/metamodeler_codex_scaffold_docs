# Tech Spec: Metamodeling Automation Framework

## Technical principles
- Typed contracts first: JSON Schema + Pydantic v2 validation at boundaries.
- Deterministic execution: explicit seeds, stable hashing, immutable run records.
- Strict separation of concerns:
  - Adapter = semantic translation.
  - Runner = process execution.
  - Store = persistence/provenance.
- No hidden compute shortcuts: no implicit downsampling or partial-run optimization.

## Architecture
### Layer 1: Spec and planning
- `ModelSpec`: model artifact, runner settings, I/O schema, design strategy, adapter mapping, reproducibility, storage target.
- `DesignPlan`: concrete list of design points produced by DOE planner.
- Validation stack:
  - JSON schema for external contract.
  - Pydantic models for runtime contract.

### Layer 2: Execution
- Adapter interface:
  - `materialize_inputs(point, run_dir) -> AdapterMaterialization`
  - `parse_outputs(run_dir) -> CanonicalOutputs`
- Runner interface:
  - `run(materialization, resources) -> RunResult`
- Local runner:
  - subprocess execution,
  - bounded resources (where feasible),
  - stdout/stderr capture to artifacts.
- Sweep orchestrator:
  - dispatch DOE points in `serial`, `parallel_local`, or `mpi` mode,
  - normalize each point result into one canonical row payload,
  - forward normalized rows to a synchronized centralized writer.
- Runner environment support:
  - `runner.execution_env` dict with optional `conda_env` key (added post-v1, see Status.md 2026-02-12).
  - When `conda_env` is set, commands execute via `conda run -n <env> ...`.

### Layer 3: Storage and lineage
- Run store layout (deterministic paths from digests):
  - `run.json` (metadata/provenance),
  - `inputs.json`,
  - `outputs.(json|nc)`,
  - `stdout.log`,
  - `stderr.log`.
- Provenance fields (required):
  - seed,
  - spec digest,
  - adapter id/version,
  - artifact digest/version,
  - runner mode/version,
  - timestamps and status.
- Centralized sweep artifact layout:
  - `sweep_manifest.json`:
    - spec digest, seed, DOE size, output schema, execution mode, completion status.
  - `sweep_rows.csv`:
    - one row per DOE point with deterministic `point_index`,
    - input columns and flattened output columns (example: `y__0`, `y__1`).
  - `sweep_logs.jsonl`:
    - per-point stdout/stderr references or inline payloads keyed by `point_index`.

### Layer 3b: Synchronized writer model
- Centralized writer contract:
  - `open(manifest) -> handle`
  - `append_row(row)`
  - `append_log(log_record)`
  - `finalize()`
- Concurrency model:
  - serial/local-parallel: one coordinator writer process receives worker results and writes rows.
  - MPI: rank 0 is the only filesystem writer; worker ranks send row/log payloads to rank 0.
  - finalize step enforces deterministic ordering by `point_index` before digesting artifacts.

### Layer 4: Surrogate and metamodel (post-v1 core)
- v1 provides interfaces and placeholders only.
- Initial strategy after v1:
  - start with practical baselines (e.g., GP/BNN-compatible interfaces),
  - add calibration diagnostics before advanced coupling.
- Spec-to-IR mapping note: `MetamodelCouplingSpec.kind="deterministic"` is mapped to `CouplingFactorIR.coupling_type="deterministic_transform"` by the IR builder (`meta/builder.py`). The IR uses the more explicit name to distinguish from other deterministic operations.

## v1 implementation scope
- Implement:
  - `ModelSpec` parsing/validation.
  - DOE planning (`grid`, `sobol`) with deterministic ordering.
  - Adapter registry and base contracts.
  - Local process runner.
  - Run store + cache key utilities.
  - Centralized sweep output sink (`sweep_rows.csv` + manifest/log sidecars).
  - Execution mode selector for `serial`, `parallel_local`, `mpi` with synchronized centralized writing.
  - CLI commands:
    - `mm validate <spec>`
    - `mm plan <spec>`
    - `mm run <spec>`
    - `mm runs list`
    - `mm runs show <run_id>`
- Defer:
  - `mm surrogate *` and `mm meta *` full functionality.

## Canonical data contracts
### Inputs
- Canonical point: `dict[str, float]` in v1.
- Every variable includes units + support metadata in spec.

### Outputs
- Canonical output payload should carry:
  - variable name,
  - dimensions,
  - units,
  - values.
- Preferred internal representation: `xarray.Dataset`; serialization format chosen per adapter (`json` for toy examples, `netcdf` optional later).
- Centralized sweep contract (tabular):
  - required columns:
    - `point_index`,
    - all input variables,
    - flattened scalar/vector outputs,
    - `status` and `error` (if failed),
    - optional timing fields.
  - deterministic row ordering:
    - sorted by `point_index` at finalize time for all execution modes.
  - tutorial target:
    - Tutorial 1 reads this table directly and plots toy `sum` and `product` heatmaps.

## Target repo layout
- `src/metamodeler/spec/`
- `src/metamodeler/designs/`
- `src/metamodeler/adapters/`
- `src/metamodeler/runners/`
- `src/metamodeler/storage/`
- `src/metamodeler/cli/`
- `src/metamodeler/surrogates/` (placeholder in v1)
- `src/metamodeler/meta/` (placeholder in v1)
- `examples/`
- `tutorials/` (notebook-first onboarding track)
  - `Tutorial_0.ipynb` (hub)
  - `Tutorial_1.ipynb` ... `Tutorial_9.ipynb` (progressive modules)
  - `specs/` (tutorial-specific runnable specs)
  - `artifacts/` (tutorial artifact stubs for standalone paths)
- `tests/`
- `githooks/`
- `tmp/`
  - `sbi-logs/` (SBI backend training summary/tensorboard logs)

## Tutorial delivery design
- Format: Jupyter notebooks only for tutorials (`.ipynb`).
- Onboarding structure per notebook:
  - audience + prerequisites + estimated time,
  - primary package aim + secondary scientific aim,
  - runnable steps with checkpoint outcomes,
  - troubleshooting and fallback path,
  - at least one visual checkpoint (plot/graphic).
- Decoupling policy:
  - every tutorial should run standalone when possible,
  - if prior artifacts are required, provide a bootstrap or stub artifact path.
- Placeholder policy:
  - avoid manual placeholders (e.g., `RUN_ID`) when an artifact can be discovered programmatically in notebook cells.
- Lint policy for docs notebooks:
  - repository lint gate excludes `.ipynb` files via Ruff config to keep code-quality checks focused on source and tests.

## Design validation scenarios (pre-Prompt-1)
- Scenario A: three independent models, each with its own surrogate, coupled via explicit coupling variables and constraints.
  - Design artifact: `examples/coupled/spec.three_model_coupling.json`
- Scenario B: BioModels SBML source model execution from JSON spec, with outputs shaped for surrogate training.
  - Design artifacts:
    - `examples/biomodels/spec.model1907260003.json`
    - `examples/biomodels/surrogate.model1907260003.json`
  - Verified download target:
    - `MODEL1907260003` (`lever2014 v5.0.xml`)

These scenarios define interface requirements for Prompt 1 (typed validation) without adding runtime feature implementation yet.

## Package strategy for later probabilistic modules
Decision for implementation phases after v1:
- Bayesian PPL backbone candidate: `PyMC` (modern replacement path from legacy `pymc3`).
- Optional deep probabilistic backend candidates: `PyTorch` ecosystem (`Pyro`/`NumPyro` deferred decision by benchmark).
- Decision gate: add package only with:
  - clear interface boundary,
  - reproducibility plan,
  - benchmark entry in `Status.md`.

## Testing strategy
- Fast suite (`not slow`) must stay under 30 seconds:
  - schema/model validation,
  - DOE bounds and determinism,
  - adapter contracts,
  - local runner smoke,
  - cache digest behavior,
  - centralized sweep-writer determinism and schema checks,
  - Tutorial 1 toy post-processing from one sweep CSV (including two heatmap-ready matrices),
  - optional backend checks that exercise SBI when available and treat PyMC toolchain compile gaps as explicit runtime constraints (skip/fallback, not false regression failures),
  - regression check that SBI summary logs are routed to `tmp/sbi-logs/` (not repo root).
- Slow suite:
  - BioModels integration and heavy simulations,
  - optional MPI integration path validating synchronized centralized writes to one sweep artifact.
- Markers:
  - `slow`
  - `integration`
  - `contract`
  - `optional_backend` (requires pymc and/or sbi; skipped when missing)
  - `mpi` (optional, environment-dependent)
