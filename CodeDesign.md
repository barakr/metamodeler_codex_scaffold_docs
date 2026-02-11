# Code Design: Metamodeling Framework (Pre-Prompt-1 Validation)

## Purpose
This document refines the implementation design before Prompt 1. It validates two concrete target workflows:
1. Multi-model metamodeling with variable scans and coupling across three independent models (aligned with the Neve-Oz / Sherman / Raveh style use case).
2. BioModels SBML execution from JSON spec, with outputs suitable for surrogate probability modeling.

## Design goals for this phase
- Keep Prompt 1 focused on typed spec validation only.
- Ensure current architecture supports real end-to-end use cases before coding model logic.
- Preserve strict reproducibility: explicit seeds, model artifact digests, and saved stdout/stderr for each run.

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

## Out of scope in this document
- Implementing Pydantic models, schema emission, or CLI command behavior.
- Implementing surrogate fitting algorithms.
- Implementing joint Bayesian inference.
