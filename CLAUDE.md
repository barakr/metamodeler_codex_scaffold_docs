# CLAUDE.md — Metamodeler Development Guide

## Project Overview

**Metamodeler** is a CLI-first framework for automated probabilistic metamodeling. It automates heterogeneous source-model execution across parameter sweeps, generates canonical datasets with full provenance, and layers surrogate learning and joint metamodel sampling on top.

- **Repo**: https://github.com/barakr/metamodeler_codex_scaffold_docs
- **Package**: `metamodeler` (source in `src/metamodeler/`)
- **CLI entrypoint**: `mm` → `metamodeler.cli.main:main`
- **Python**: ≥ 3.14
- **Core deps**: pydantic ≥2, requests ≥2, scipy ≥1.11
- **Optional backends**: `pip install -e '.[pymc]'` or `pip install -e '.[sbi]'`

## Quick Commands

```bash
make fmt          # ruff format .
make lint         # ruff check .
make fast         # pytest -q -m "not slow"   (must stay < 30s)
make slow         # pytest -q -m slow
pip install -e .  # editable install
```

## Project Structure

```
src/metamodeler/
├── spec/           # Pydantic v2 specs: ModelSpec, SurrogateSpec, MetaModelSpec
├── designs/        # DOE planning (grid, sobol)
├── adapters/       # Adapter protocol + implementations (python_cli, biomodels_sbml)
├── runners/        # LocalProcessRunner (subprocess execution)
├── storage/        # RunStore, SweepStore, SurrogateStore, MetaStore
├── surrogates/     # SurrogateModel protocol + backends (pymc_gp, sbi_npe)
├── meta/           # Backend-neutral IR → compiler → sampling (PyMC, NumPyro)
├── cli/            # CLI commands (validate, plan, run, surrogate, meta, tutorial)
└── tutorials/      # Tutorial helper modules

tests/              # Fast + slow + optional_backend test suites
examples/           # Runnable specs and toy models
tutorials/          # Jupyter notebook curriculum (Tutorial_0 through Tutorial_9)
githooks/           # pre-commit, pre-push, commit-msg hooks
```

## Key Documents

| File | Purpose |
|------|---------|
| `PRD.md` | Product requirements and user stories |
| `TechSpec.md` | Architecture, layer structure, canonical contracts |
| `CodeDesign.md` | Design validation with concrete use cases |
| `Status.md` | Implementation progress, decisions log — **update after every meaningful change** |
| `PROMPT_TO_CODEX.md` | Detailed prompt pack with acceptance criteria |
| `TEST_PLAN.md` | Test strategy and acceptance criteria |

## Architecture

### Core Pipeline

1. **Spec** (JSON → Pydantic v2) defines model, DOE, I/O schema, adapter, runner, storage
2. **DOE Planner** generates deterministic design points (grid or sobol)
3. **Adapter** materializes inputs and parses outputs (protocol-based, pluggable)
4. **Runner** executes model via subprocess with full provenance capture
5. **SweepStore** writes centralized `sweep_rows.csv` + `sweep_manifest.json` + `sweep_logs.jsonl`

### Surrogate Layer

- Backend-neutral `SurrogateSpec` → `SurrogateModel` protocol (`sample`, `log_prob`, `summary`)
- Real backends: `pymc_gp` (Bayesian linear regression), `sbi_npe` (Neural Posterior Estimator)
- Artifacts persisted via `SurrogateStore`

### Metamodel Layer

- `MetaModelSpec` → backend-neutral IR (variables, priors, couplings, surrogate likelihoods)
- IR compiled to PyMC or NumPyro model
- Sampling produces canonical `inference_data.json` + `samples_dataset.json`

## Non-Negotiable Rules

1. **Small, incremental commits** — one logical change per commit
2. **No hidden shortcuts** — never downsample, reduce datasets, or change sampling without recording in Status.md
3. **Full provenance** — seeds, spec digests, artifact digests, stdout/stderr saved for every run
4. **Fast tests must pass before commit** — `make fmt && make lint && make fast`
5. **Status.md updated** for any change to `src/` or `examples/`
6. **Temporary files under `tmp/`** (gitignored)
7. **Delete orphaned code** — no dead code after refactors
8. **Typed contracts first** — Pydantic v2 with `extra="forbid"`, explicit return types, `from __future__ import annotations`
9. **No destructive shell commands** — never run recursive deletes, force pushes, or history rewrites without explicit user approval; record in Status.md
10. **Tests with every change** — any non-trivial change must add or update tests

## Coding Conventions

- **Ruff**: line-length 100, target py314, select E/F/I, exclude `*.ipynb`
- **Protocols** for pluggable interfaces (Adapter, Runner, SurrogateModel)
- **Dataclasses** for simple value containers
- **One concept per module**, public API via `__all__` in `__init__.py`
- **Private helpers** prefixed with `_`
- **Imports**: stdlib → third-party → local, enforced by ruff isort

## Testing

### Markers

| Marker | Meaning |
|--------|---------|
| `not slow` | Fast suite, must stay < 30s, required for all commits |
| `slow` | Long-running tests (BioModels, MPI) |
| `integration` | Cross-component tests |
| `contract` | Interface contract tests |
| `optional_backend` | Requires pymc or sbi; skipped gracefully when missing |
| `mpi` | Requires MPI launcher + mpi4py |

### pytest config

```ini
addopts = -q
testpaths = tests
filterwarnings = error
```

### Optional backend handling

- PyMC/SBI detected at collection time (`tests/backend_support.py`)
- Missing deps → skip with reason (not a regression)
- `MM_SKIP_OPTIONAL_BACKEND_TESTS=1` to force-skip all optional backend tests
- PyMC compile failures treated as runtime constraints (skip), not regressions

## CLI Reference

```
mm validate <spec.json>           # Validate ModelSpec
mm plan <spec.json>               # Preview DOE points
mm run <spec.json>                # Execute sweep

mm runs list                      # List run IDs
mm runs show <run_id>             # Show run metadata

mm surrogate fit <spec.json>      # Train surrogate
mm surrogate eval <spec.json> --inputs <json> --n N
mm surrogate list                 # List surrogate artifacts

mm meta build <spec.json>         # Build metamodel IR
mm meta sample <spec.json> --draws D --tune T
mm meta list                      # List metamodel samples

mm tutorial                       # Print workflow guide
mm --version
```

## Conda Environments

| Environment | Purpose |
|-------------|---------|
| `py314_metamodeling` | Main dev (Python 3.14) |
| `py312_metamodeling_pymc` | PyMC 5.27.1 + ArviZ |
| `py312_metamodeling_sbi` | SBI 0.23.3 + Torch 2.10.0 |

## Git Hooks (in `githooks/`)

- **pre-commit**: `ruff format`, `ruff check`, fast tests, Status.md change check for `src/` edits
- **pre-push**: fast tests
- **commit-msg**: conventional commit style enforcement

## Definition of Done

- Code compiles and runs
- Fast tests pass (`make fast`)
- Status.md updated with decisions
- No dead code, no temporary artifacts outside `tmp/`
