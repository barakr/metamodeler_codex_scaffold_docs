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

### Layer 4: Surrogate and metamodel (post-v1 core)
- v1 provides interfaces and placeholders only.
- Initial strategy after v1:
  - start with practical baselines (e.g., GP/BNN-compatible interfaces),
  - add calibration diagnostics before advanced coupling.

## v1 implementation scope
- Implement:
  - `ModelSpec` parsing/validation.
  - DOE planning (`grid`, `sobol`) with deterministic ordering.
  - Adapter registry and base contracts.
  - Local process runner.
  - Run store + cache key utilities.
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
- `tests/`
- `githooks/`
- `tmp/`

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
  - cache digest behavior.
- Slow suite:
  - BioModels integration and heavy simulations.
- Markers:
  - `slow`
  - `integration`
  - `contract`
