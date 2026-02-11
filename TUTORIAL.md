# Tutorial: Using Metamodeler (Prompt 0-10 Baseline)

This tutorial reflects the current implemented CLI surface.

## 1) Setup

```bash
conda activate /Users/barak/miniconda3/envs/py314_metamodeling
cd /Users/barak/Downloads/metamodeler_codex_scaffold_docs
```

Optional editable install:

```bash
pip install -e .
```

Without install, use module mode:

```bash
PYTHONPATH=src python -m metamodeler.cli.main --version
```

## 2) Quick guided flow

Print the built-in guided command sequence:

```bash
PYTHONPATH=src python -m metamodeler.cli.main tutorial
```

## 3) Validate and plan a model spec

```bash
PYTHONPATH=src python -m metamodeler.cli.main validate examples/toy_program/spec.toy_program.json
PYTHONPATH=src python -m metamodeler.cli.main plan examples/toy_program/spec.toy_program.json
```

## 4) Run model sweeps and inspect runs

```bash
PYTHONPATH=src python -m metamodeler.cli.main run examples/toy_program/spec.toy_program.json
PYTHONPATH=src python -m metamodeler.cli.main runs list
PYTHONPATH=src python -m metamodeler.cli.main runs show <RUN_ID>
```

Primary run artifacts:
- `examples/toy_program/store/runs/<run_id>/run.json`
- `examples/toy_program/store/runs/<run_id>/inputs.json`
- `examples/toy_program/store/runs/<run_id>/outputs.json`
- `examples/toy_program/store/_active/<model>_<index>/stdout.log`
- `examples/toy_program/store/_active/<model>_<index>/stderr.log`
- `tmp/run_registry.json`

## 5) Fit and evaluate surrogates

Use a surrogate spec that points to a run-store dataset:

```bash
PYTHONPATH=src python -m metamodeler.cli.main surrogate fit examples/surrogates/surrogate.toy.pymc_gp.json
```

Evaluate with explicit input arrays:

```bash
PYTHONPATH=src python -m metamodeler.cli.main surrogate eval \
  examples/surrogates/surrogate.toy.pymc_gp.json \
  --inputs '{"a":[0.5,1.0],"b":[1.0,2.0]}' \
  --n 100
```

List stored surrogate artifacts:

```bash
PYTHONPATH=src python -m metamodeler.cli.main surrogate list
```

Surrogate artifacts are stored under:
- `tmp/surrogate_artifacts/<artifact_id>/artifact.json`
- `tmp/surrogate_artifacts/<artifact_id>/backend_payload.json`
- `tmp/surrogate_registry.json`

## 6) Build and sample metamodels

Build IR from metamodel spec:

```bash
PYTHONPATH=src python -m metamodeler.cli.main meta build examples/metamodels/metamodel.simple.json
```

Sample posterior/joint draws:

```bash
PYTHONPATH=src python -m metamodeler.cli.main meta sample \
  examples/metamodels/metamodel.simple.json \
  --draws 100 --tune 50 --chains 2 --seed 1
```

List metamodel artifacts and samples:

```bash
PYTHONPATH=src python -m metamodeler.cli.main meta list
```

Metamodel artifacts are stored under:
- `tmp/metamodel_ir/<artifact_id>/artifact.json`
- `tmp/metamodel_ir/<artifact_id>/ir.json`
- `tmp/meta_registry.json`
- `tmp/metamodel_samples/<sample_id>/inference_data.json`
- `tmp/metamodel_samples/<sample_id>/samples_dataset.json`
- `tmp/metamodel_samples_registry.json`

## 7) Backend selection for metamodel sampling

`MetaModelSpec` supports:
- `ppl_backend: "pymc"`
- `ppl_backend: "numpyro"`

Both backends use the same JSON interface and write the same canonical sample artifact files.

## 8) BioModels adapter workflow (slow/integration path)

Example spec:

```bash
examples/biomodels/spec.prompt4.model1907260003.json
```

Run:

```bash
PYTHONPATH=src python -m metamodeler.cli.main run examples/biomodels/spec.prompt4.model1907260003.json
```

Notes:
- Downloads SBML to `storage_root/_cache/biomodels/`.
- Requires `libroadrunner`.
- Slow tests may skip if dependency is unavailable.

## 9) Standard quality gate

```bash
ruff format .
ruff check .
pytest -q -m "not slow"
```

## 10) Current baseline limitations

- Backend implementations are pragmatic baselines that match interfaces/artifact contracts; they are not full production PyMC/SBI/NumPyro inference stacks yet.
- Run logs are currently written under `_active` paths; immutable finalized log placement is still a hardening target.
- BioModels runtime depends on environment availability of `libroadrunner`.
