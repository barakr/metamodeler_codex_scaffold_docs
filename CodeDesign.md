# Code Design: Metamodeling Framework (Pre-Prompt-1 Validation)

## Purpose
This document refines the implementation design before Prompt 1. It validates two concrete target workflows:
1. Multi-model metamodeling with variable scans and coupling across three independent models (aligned with the Neve-Oz / Sherman / Raveh style use case).
2. BioModels SBML execution from JSON spec, with outputs suitable for surrogate probability modeling.

## Design goals for this phase
- Keep Prompt 1 focused on typed spec validation only.
- Ensure current architecture supports real end-to-end use cases before coding model logic.
- Preserve strict reproducibility: explicit seeds, model artifact digests, and saved stdout/stderr for each run.
- Provide a notebook-first onboarding path so non-specialist lab members can execute the workflow progressively.

## Architectural refinement

### A. Explicit spec family
Introduce a small family of typed specs (validated in Prompt 1+):
- `ModelSpec`: one executable source model + DOE + adapter mapping.
- `SurrogateSpec`: how to train/evaluate a surrogate from one model run store.
- `CouplingSpec`: coupling variables and constraints tying multiple surrogates.
- `MetaModelSpec`: orchestrates multiple `SurrogateSpec` + one `CouplingSpec`.

This keeps execution and learning contracts explicit and composable.

### B. Core interfaces (unchanged, now concretized)
- `Adapter.materialize_inputs(point, run_dir)`
- `Runner.run(materialization, resources)`
- `Adapter.parse_outputs(run_dir)`
- `RunStore.persist(run_artifacts)`

### C. Canonical run record (mandatory fields)
Each run record must include:
- `run_id`
- `seed`
- `spec_digest`
- `artifact_digest`
- `adapter_id`
- `runner_mode`
- `status`, `started_at`, `finished_at`
- paths for `stdout.log`, `stderr.log`, canonical outputs

## Use case 1: Three-model coupling metamodel

### Scenario
Run three independent model programs over scanned variables, learn one surrogate per model, then build a coupled joint distribution.

### Data flow
1. `mm plan model_A.json` / `model_B.json` / `model_C.json`
2. `mm run ...` for each model to produce canonical datasets + provenance
3. `mm surrogate fit surrogate_A.json` (and B/C)
4. `mm meta build metamodel_ABC.json` with coupling variables and constraints

### Minimal coupling representation
Coupling must support:
- Variable linkage (`A.out_x` linked to `B.in_k`)
- Transform link (`B.out_y = f(A.out_x)`)
- Shared latent (`z_shared` drives terms in A/B/C)
- Constraint set (bounds, monotonicity, units compatibility)

### Example coupling spec shape
See `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/examples/coupled/spec.three_model_coupling.json`.

### What implementation code should look like (shape only)
```python
# src/metamodeler/meta/builder.py

def build_joint_metamodel(surrogate_artifacts, coupling_spec):
    validate_compatibility(surrogate_artifacts, coupling_spec)
    graph = make_dependency_graph(surrogate_artifacts, coupling_spec)
    return JointMetaModel(graph=graph, coupling=coupling_spec)
```

```python
# src/metamodeler/cli/main.py (future)
# mm meta build metamodel_ABC.json
```

## Use case 2: BioModels SBML execution + surrogate-ready dataset

### Verified model artifact
User-provided SBML source URL:
- https://www.ebi.ac.uk/biomodels/services/download/get-files/MODEL1907260003/2/lever2014%20v5.0.xml

Downloaded local artifact:
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/biomodels/MODEL1907260003_lever2014_v5_0.xml`

### Verified sample simulations (3 runs)
A design-validation script executed three scenarios (baseline, low, high):
- parameter scanned: `k_on`
- values: `0.0001`, `0.00008`, `0.00012`
- time grid: `t0=0`, `t1=200`, `n_points=401`
- tracked species: `C0..C4`

Artifacts:
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/biomodels/simulations_MODEL1907260003/summary.json`
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/biomodels/simulations_MODEL1907260003/baseline.json`
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/biomodels/simulations_MODEL1907260003/param_low.json`
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/biomodels/simulations_MODEL1907260003/param_high.json`

Run logs:
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/run_logs/biomodel_download_lever.stderr.log`
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/run_logs/biomodel_sim_lever.stdout.log`
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/run_logs/biomodel_sim_lever.stderr.log`

### JSON design for this workflow
- Model execution spec (BioModels):
  - `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/examples/biomodels/spec.model1907260003.json`
- Surrogate training spec (placeholder contract):
  - `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/examples/biomodels/surrogate.model1907260003.json`

## Prompt-1 readiness checklist
- Prompt 0 scaffold is complete.
- Spec boundaries are now explicit for validation work.
- Two target workflows are represented with concrete JSON examples.
- Real BioModels artifact execution path was verified and logged.

## Centralized sweep table + synchronized parallel writing (implemented in Prompt 17)

### Problem being solved
Tutorial 1 currently reconstructs sweep outputs by traversing per-point run folders.
For DOE grids, this is inefficient and hard to analyze directly.

### Target behavior
- A DOE sweep should emit one centralized table artifact for numeric results.
- The same artifact contract must work for:
  - serial local execution,
  - local parallel execution,
  - MPI-coordinated execution.
- Tutorial 1 should consume this table directly and render two heatmaps:
  - `sum = a + b`
  - `product = a * b`

### Proposed artifact contract
- `sweep_rows.csv`:
  - one row per DOE point
  - deterministic `point_index` column
  - one column per input variable
  - flattened output columns (toy example: `y__0`, `y__1`)
  - status/error/timing columns
- `sweep_manifest.json`:
  - spec digest, seed, DOE cardinality, column schema, execution mode, completion status
- `sweep_logs.jsonl`:
  - one record per point with stdout/stderr references or payload snippets

This preserves the "no per-point output file/folder for numeric results" goal while keeping per-point observability and provenance.

### Synchronization design
- Single-writer rule:
  - exactly one writer owns `sweep_rows.csv` at a time.
- Serial mode:
  - executor writes rows directly through writer API.
- Local parallel mode:
  - workers return row payloads through a queue;
  - coordinator process performs all file writes.
- MPI mode:
  - rank 0 is the only writer;
  - worker ranks send row/log payloads to rank 0 (message passing);
  - rank 0 finalizes and closes artifacts after barrier.
- Deterministic finalize step:
  - enforce ordering by `point_index` before digesting and registering artifact.

### Interface impact (planned)
- Runner/spec additions:
  - execution mode selector: `serial | parallel_local | mpi`
  - parallel config (`workers` for local parallel, MPI process count external)
- Store additions:
  - centralized sweep writer API
  - sweep artifact registry fields in `run.json`
- Backward compatibility:
  - keep per-run provenance/log records;
  - migrate Tutorial 1 and future surrogate dataset loaders to consume sweep table first.

### Test strategy for this extension
- Fast tests:
  - sweep table schema and deterministic ordering
  - serial and local-parallel produce equivalent `sweep_rows.csv` content
  - tutorial toy parser builds two heatmap matrices from centralized CSV
  - optional backend checks remain robust in mixed PyMC/SBI environments:
    - exercise SBI paths when available,
    - treat PyMC compile/toolchain gaps as explicit runtime constraints (skip/fallback)
  - SBI training summary logs are emitted under `tmp/sbi-logs/` (not repo root)
- Slow/optional tests:
  - MPI integration: one centralized output file with correct row count and no corruption
  - marker: `mpi`

## Out of scope in this document
- Implementing Pydantic models, schema emission, or CLI command behavior.
- Implementing surrogate fitting algorithms.
- Implementing joint Bayesian inference.

## Tutorial/onboarding design notes
- Tutorials are delivered notebook-first in `tutorials/Tutorial_0.ipynb` to `tutorials/Tutorial_9.ipynb`.
- Each tutorial carries two explicit aims:
  - package operation objective (CLI/spec/artifact action),
  - light scientific/computational objective (e.g., DOE coverage, Bayesian posterior, SBI intuition).
- BioModels is intentionally early (Tutorial 2) so biological context precedes advanced surrogate/metamodel work.
- Tutorials are decoupled by design:
  - standalone bootstrap commands are included,
  - serial execution remains supported for cumulative learning.
- Tutorials include visual checkpoints (plots/graphics) to support rapid comprehension during onboarding.
- Known execution blockers discovered during tutorial dry-run should be fixed in code with explicit regression tests (not only docs edits).
