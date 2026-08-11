# CLAUDE.md — Metamodeler Development Guide

## Project Overview

**Metamodeler** is a CLI-first framework for automated probabilistic metamodeling. It automates heterogeneous source-model execution across parameter sweeps, generates canonical datasets with full provenance, and layers surrogate learning and joint metamodel sampling on top.

- **Repo**: https://github.com/barakr/metamodeler_codex_scaffold_docs
- **Package**: `bayesian-metamodeling` (source in `src/bayesian_metamodeling/`)
- **CLI entrypoint**: `bayesmm` → `bayesian_metamodeling.cli.main:main`
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
src/bayesian_metamodeling/
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
projects/           # Independent research projects (Git submodules)
```

## Submodule Boundary

The `projects/` directory contains **independent research projects** as Git
submodules. Each is a separate repository with its own lifecycle.

| Submodule | Repo | Purpose |
|-----------|------|---------|
| `projects/tcr_signaling` | `github.com/barakr/tcr_signaling` | TCR signaling metamodel (Neve-Oz, Sherman & Raveh 2024) |

### Rules for submodule separation

1. **Each submodule owns its own docs**: `CLAUDE.md`, `Status.md`, `README.md`
   live inside the submodule and govern work done there.
2. **Root docs govern framework only**: This `CLAUDE.md`, `Status.md`, and all
   root-level design docs describe the `bayesian-metamodeling` package — not
   the research projects that use it.
3. **Do not mix status entries**: TCR-specific decisions go in
   `projects/tcr_signaling/Status.md`, framework decisions go in root `Status.md`.
4. **Submodules are consumers**: They depend on `bayesian-metamodeling` as a
   package. If framework changes are needed, switch context to root and make
   the change there — then update both Status files.
5. **Separate test runs**: Submodule tests run via their own `pytest.ini`.
   Root `make fast` covers framework tests only.
6. **Commits are separate**: Changes inside `projects/tcr_signaling/` must be
   committed to the submodule repo first, then the submodule pointer updated
   in the parent.
7. **Submodule CLAUDE.md takes precedence**: When working within a submodule
   directory, defer to that submodule's `CLAUDE.md` for development rules,
   conventions, and project-specific instructions. Claude Code's `CLAUDE.md`
   files load hierarchically by directory, so the submodule's instructions
   automatically apply when reading or editing files there. Note:
   `.claude/settings.json` does NOT support per-submodule overrides — only
   `CLAUDE.md` files provide directory-scoped instructions.

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

**Two sampling methods, and the difference is not a detail** (`--method`):

- `propagate` (default) — draw every variable from its prior, then overwrite each
  coupled target with `transform(source)`. Surrogate likelihoods are **not** evaluated
  (the compiled model is called with `surrogates={}`). A coupling informs its target
  only; the source stays at exactly its prior. This is forward uncertainty
  propagation, and calling its output a "posterior" is a misnomer.
- `joint` (`meta/joint_sampling.py`) — random-walk Metropolis over the full joint
  log-density: priors, couplings **and** surrogate likelihoods. Both ends of a coupling
  move; deterministic couplings are computed from their source rather than sampled.
  Gradient-free because a fitted surrogate's `log_prob` is a black box; expressing it
  as a PyTensor graph is what would unlock NUTS.

`inference_data.json` records `method` for both paths, so a stored dataset says how it
was made. Correctness of `joint` is pinned against a closed-form Gaussian in
`tests/test_joint_sampling.py`, and against both surrogate backends in
`tests/test_joint_sampling_backends.py` (`slow`; NPE `log_prob` is ~100x the cost of
`pymc_gp`, so it does not belong in the fast suite).

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
11. **Commit regularly** — make git commits at logical milestones (feature complete, bug fix verified, refactor done). Do not accumulate large uncommitted changesets
12. **A gate that can skip must be able to fail for skipping** — any suite that
    degrades when a dependency is absent needs a mode where that degradation is
    an error. Otherwise "green" means "nothing ran" and nobody can tell. See
    *Guarding against silent no-ops* below for the mechanisms already available

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

### Guarding against silent no-ops

Rule 12 exists because every defect found during the 2026-08-07 CI hardening was
the same shape — **a check that quietly did not run, and therefore reported
success**:

- 118 KS tests skipped on a broken toolchain; the suite exited 0
- Tutorial 2 skipped its entire BioModels sweep and printed `self-check OK`
- the slow suite had never run in CI at all (`CI` runs `-m "not slow"`)
- `test_biomodels_slow` asserted a column that never existed — it needs
  libroadrunner, which was installed in no environment, so it never ran
- `Deep CI`'s push filter did not include the tests it runs

Skips are legitimate. What is not legitimate is a skip that is indistinguishable
from a pass. Mechanisms already in place — reuse them rather than inventing more:

| Mechanism | Where | What it does |
|---|---|---|
| `REQUIRE_TUTORIAL_BACKENDS=1` | `tests/test_tutorial_integration.py` | a preflight skip becomes a failure |
| `REQUIRE_SUBMODULE_INTERFACE=1` | `tests/test_submodule_interface.py` | an absent submodule becomes a failure |
| junit floor + skip audit | `KS model CI`, `Deep CI` | fails on too few collected tests, or on any skip without a sanctioned reason |
| `::error::` annotations | `Deep CI` | failing test names and per-point `sweep_logs.jsonl` errors, readable without a token — logs are not |

When adding a suite that can degrade, give it one of these. The question to ask
is: *if every step silently did nothing, would this still be green?*

### CI signals

Five workflows, deliberately kept separate so a failure in one never reddens
another. Read the name to know what broke.

| Workflow | Repo | Red means | Runs |
|---|---|---|---|
| `CI` | this | the framework is broken | every push, 3 OSes |
| `Interface CI` | this | framework and submodule specs no longer fit | every push |
| `Deep CI` | this | the slow suite or a tutorial is broken | nightly + relevant pushes, 4-env matrix |
| `Submodule notebooks CI` | this | notebooks 01-04 broke against the compiled KS model | weekly + gitlink moves |
| `KS model CI` | tcr_signaling | the KS model is broken | every push, macOS + Linux |

`Submodule notebooks CI` is the only job that both checks out the submodule and
builds its native model — `notebooks/01-04` drive `ks_gpu` by subprocess, so
nothing cheaper can cover them. It is weekly because the build plus real sweeps
take minutes.

### Reading skipped tests in CI

Skips are normal — most jobs deliberately install only some backends. What is
not acceptable is a skip nobody can account for. So **every skip must match a
sanctioned reason, and the job summary says which and why.**

`Deep CI`'s summary carries a table like:

| verdict | test | reason | why that's OK |
|---|---|---|---|
| OK | `test_biomodels_slow::…` | libroadrunner is not installed | biomodels extra not installed in this job (the `full` job has it) |
| **UNEXPECTED** | `test_foo::…` | some new reason | — not a sanctioned reason |

Anything marked **UNEXPECTED** emits a `::error::` annotation and **fails the
job**. So when you look at a green run, the skips in it have already been
accounted for; you do not have to reason about them.

Two levels of strictness:

- **Partial jobs** (`main env`, `pymc env`, `sbi env`) — a backend-absence skip
  is expected; that is what those jobs exist to test.
- **`full` job** — everything is installed, so the *only* sanctioned skip is
  "submodule not checked out" (covered by `Interface CI`). Any other skip there
  means a dependency is missing from the job, and it goes red.

**When a new skip appears**, you have exactly two honest options — and picking
neither is what the check prevents:

1. Install the missing dependency in that job, so the test runs; or
2. Add the reason to `SANCTIONED` in `.github/workflows/slow.yml` **with a
   written justification** — the third column of that table is the justification,
   and it is there so the next reader does not have to re-derive it.

Never silence a skip by loosening the pattern without saying why.

### CI trigger paths (revisit if trouble arises)

`Deep CI` is the only workflow using `paths:` filters, and it is currently
correct — the filter covers everything the job runs. Two things to know if it
misbehaves:

- **Path filters fail open.** When the list is wrong you get silence, not an
  error. A fix to `tests/test_biomodels_slow.py`, for a failure only `Deep CI`
  could see, once failed to re-run `Deep CI` because the filter named a
  different test file.
- **The filter must cover everything the job executes**, not just the files that
  seem topical. `Deep CI` runs the whole slow suite, so it watches all of
  `tests/`.

If path filters cause a missed run again, the simple move is to drop them and
let the job run on every push — Actions minutes are free on public repos, so the
cost is queue time, not money. They were added only to keep a 4-job matrix off
unrelated commits, which is a convenience, not a requirement.

## CLI Reference

```
bayesmm validate <spec.json>           # Validate ModelSpec
bayesmm plan <spec.json>               # Preview DOE points
bayesmm run <spec.json>                # Execute sweep

bayesmm runs list                      # List run IDs
bayesmm runs show <run_id>             # Show run metadata

bayesmm surrogate fit <spec.json>      # Train surrogate
bayesmm surrogate eval <spec.json> --inputs <json> --n N
bayesmm surrogate list                 # List surrogate artifacts

bayesmm meta build <spec.json>         # Build metamodel IR
bayesmm meta sample <spec.json> --draws D --tune T [--method propagate|joint]
bayesmm meta list                      # List metamodel samples

bayesmm tutorial                       # Print workflow guide
bayesmm --version
```

## Conda Environments during development

| Environment | Purpose | Create with |
|-------------|---------|-------------|
| `py314_bayesmm` | Main dev (Python 3.14) | `conda env create -f environment.yml` |
| `py312_bayesmm_pymc` | PyMC + ArviZ | `conda env create -f environment-pymc.yml` |
| `py312_bayesmm_sbi` | SBI + Torch | `conda env create -f environment-sbi.yml` |
| `py312_bayesmm_biomodels` | libRoadRunner + tellurium (Tutorial 2) | `conda env create -f environment-biomodels.yml` |
| `py312_bayesmm_all` | Both backends — for working through the tutorials | `conda env create -f environment-all.yml` |

Keep the single-backend envs single-backend: they reproduce CI's per-backend jobs, and an
`sbi` env that quietly contained PyMC is what once hid Tutorial 6's missing PyMC guard.
`py312_bayesmm_all` exists because no env had both, and T6's Step 4 (GP vs NPE on the same
query points) needs both — it printed `Step 4 SKIPPED` in every environment we shipped.

`py314_bayesmm` is the env the `githooks/` hooks fall back to by name, and the
only one carrying `pytest`, `ruff` and `cmake`.

## Git Hooks (in `githooks/`)

- **pre-commit**: `ruff format`, `ruff check`, fast tests, Status.md change check for `src/` edits
- **pre-push**: fast tests
- **commit-msg**: conventional commit style enforcement

## Definition of Done

- Code compiles and runs
- Fast tests pass (`make fast`)
- Status.md updated with decisions
- No dead code, no temporary artifacts outside `tmp/`
