# Tutorial: Using Metamodeler (Current Baseline)

This tutorial walks through the implemented CLI workflow in this repository.

## 1) Environment setup

Activate the project environment used in this repo:

```bash
conda activate /Users/barak/miniconda3/envs/py314_metamodeling
```

From project root:

```bash
cd /Users/barak/Downloads/metamodeler_codex_scaffold_docs
```

Optional: install package in editable mode so `mm` is available as a command.

```bash
pip install -e .
```

If you do not install the package, use module mode in this tutorial:

```bash
PYTHONPATH=src python -m metamodeler.cli.main --version
```

## 2) Validate a model spec

Validate the toy model spec:

```bash
PYTHONPATH=src python -m metamodeler.cli.main validate examples/toy_program/spec.toy_program.json
```

Expected result: a success line containing model name, strategy, and adapter.

## 3) Plan DOE points

Preview the input sweep:

```bash
PYTHONPATH=src python -m metamodeler.cli.main plan examples/toy_program/spec.toy_program.json
```

Expected result:
- total point count
- first few planned points

## 4) Run the toy model end-to-end

Execute planned points and persist run records:

```bash
PYTHONPATH=src python -m metamodeler.cli.main run examples/toy_program/spec.toy_program.json
```

This writes artifacts under the spec storage root:
- `examples/toy_program/store/runs/<run_id>/run.json`
- `examples/toy_program/store/runs/<run_id>/inputs.json`
- `examples/toy_program/store/runs/<run_id>/outputs.json`
- `examples/toy_program/store/_active/<model>_<index>/stdout.log`
- `examples/toy_program/store/_active/<model>_<index>/stderr.log`

The run registry is stored at:
- `tmp/run_registry.json`

## 5) Inspect runs

List runs:

```bash
PYTHONPATH=src python -m metamodeler.cli.main runs list
```

Show one run record:

```bash
PYTHONPATH=src python -m metamodeler.cli.main runs show <RUN_ID>
```

## 6) BioModels milestone workflow (Prompt 4 baseline)

A BioModels example spec is included:

```bash
examples/biomodels/spec.prompt4.model1907260003.json
```

Run it:

```bash
PYTHONPATH=src python -m metamodeler.cli.main run examples/biomodels/spec.prompt4.model1907260003.json
```

Notes:
- The adapter downloads SBML and caches it under `storage_root/_cache/biomodels/`.
- It requires `libroadrunner` to simulate SBML.
- If `libroadrunner` is unavailable in your active env, this flow fails or slow tests skip.

Run slow tests only:

```bash
pytest -q -m slow
```

## 7) Surrogate and metamodel placeholder commands (Prompt 5)

These commands currently validate specs and return placeholder messages:

```bash
PYTHONPATH=src python -m metamodeler.cli.main surrogate fit examples/biomodels/surrogate.model1907260003.json
PYTHONPATH=src python -m metamodeler.cli.main surrogate eval examples/biomodels/surrogate.model1907260003.json
PYTHONPATH=src python -m metamodeler.cli.main meta build examples/coupled/spec.three_model_coupling.json
```

## 8) Standard local quality gate

Run before committing:

```bash
ruff format .
ruff check .
pytest -q -m "not slow"
```

## 9) Current limitations

- Surrogate fitting and metamodel build are not implemented yet (validation/placeholders only).
- Run-store layout keeps process logs in `_active`; future hardening should move/copy them into immutable run dirs.
- BioModels runtime dependency (`libroadrunner`) is environment-sensitive.
