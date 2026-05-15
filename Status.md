# Status: Metamodeling Automation Framework

## High level state
- Stage: Prompt 17 implementation complete
- Current focus: validating centralized sweep output behavior across tutorial and optional MPI environments

## Decision Log

### 2026-03-05: Fix KS model MC loop + self-contained example specs
- **MC loop fix**: Changed from single-particle stepping to full sweeps — each
  `n_steps` iteration now updates every molecule and every grid cell once,
  matching standard MC convention. Previous behavior updated ~3 molecules per
  step (150 molecules / 500 steps), far too few for equilibration.
- **n_steps auto-scaling**: Changed from `max(500, time*100)` to `max(50, time*5)`
  since each step now does ~1000x more work (full sweep vs single particle).
- **Default grid_size**: Increased from 32 to 64 for better spatial resolution.
- **Per-point seed derivation**: `__main__.py` now derives a unique reproducible
  seed per DOE point via `seed + hash(inputs)`, eliminating correlated MC noise
  across the parameter sweep.
- **Self-contained example specs**: Created `examples/specs/` with model, pymc_gp,
  and sbi_npe specs. Example script now references local specs instead of
  global `specs/` directory. Moved `specs/surrogate.kinetic_segregation.sbi_npe.json`
  to `examples/specs/`.
- **Tests updated**: All n_steps values reduced (full sweeps need far fewer
  iterations); grid_size and molecule counts reduced for speed. All 54
  submodule tests and 272+ root fast tests pass.

### 2026-03-05: Co-locate model tests within each model subdirectory
- Moved `tests/test_kinetic_segregation.py` into `projects/tcr_signaling/models/kinetic_segregation/tests/`
  split into `test_potentials.py`, `test_model.py`, `test_cli.py`
- Added new test suites for `membrane_topography`, `lck_activity`, `tcr_phosphorylation`
- Added `projects/tcr_signaling/pytest.ini` and `conftest.py` for standalone test discovery
- Root `pytest.ini` updated to discover submodule tests via `testpaths`
- Total: 54 submodule tests, 272 fast tests from root (all passing)

### 2026-03-05: Add TCR signaling case study (Neve-Oz, Sherman & Raveh 2024)
- Created `projects/` top-level directory for real-world scientific reproductions
- First project: `projects/tcr_signaling/` — reproduces Bayesian metamodeling of
  early TCR signaling from Frontiers in Immunology 2024
- 4 partial models: membrane topography, kinetic segregation, Lck activity, TCR phosphorylation
- 4 ModelSpecs (2 grid DOE, 2 sobol DOE), 4 SurrogateSpecs, 1 MetaModelSpec
- 4 Jupyter notebooks for exploration, surrogate fitting, inference, and figure reproduction
- All model specs pass `bayesmm validate`; all fast tests pass

### 2026-03-04: Rename package from metamodeler to bayesian-metamodeling
- pip name: `bayesian-metamodeling`
- import name: `bayesian_metamodeling`
- CLI command: `bayesmm` (was `mm`)
- Source directory: `src/bayesian_metamodeling/` (was `src/metamodeler/`)
- Conda envs: `py314_bayesmm`, `py312_bayesmm_pymc`, `py312_bayesmm_sbi`

## Folder structure
- src/bayesian_metamodeling/: library code
- examples/: example specs and toy models
- projects/: real-world scientific case studies using the framework
- tutorials/: modular tutorial curriculum, tutorial specs, and notebook entrypoint
- tests/: unit and integration tests
- tmp/: scratch and temporary files, not committed
- githooks/: git hooks that enforce formatting, lint, and fast tests

## Implemented
- Prompt 17 implemented: centralized sweep output + synchronized execution modes (2026-02-15):
  - Replaced per-point numeric result persistence in `bayesmm run` with one centralized sweep artifact set:
    - `sweep_rows.csv`
    - `sweep_manifest.json`
    - `sweep_logs.jsonl`
  - Added synchronized execution modes in `RunnerSpec` and `bayesmm run`:
    - `runner.sweep_mode`: `serial` (default), `parallel_local`, `mpi`
    - `runner.workers` (parallel-local only; defaults to runner CPUs)
  - Single-writer guarantees:
    - serial: direct writer
    - parallel_local: coordinator writes centralized files
    - mpi: rank 0 writes centralized files; non-root ranks synchronize via broadcast
  - Added centralized sweep helpers:
    - `src/bayesian_metamodeling/storage/sweep_store.py`
  - Added sweep persistence contract:
    - `src/bayesian_metamodeling/storage/run_store.py` (`persist_sweep`)
    - run registry now tracks sweep records with `sweep_rows_path`, `sweep_manifest_path`, `sweep_logs_path`
  - Updated surrogate dataset loading to support centralized sweep CSV stores (with legacy `runs/*` fallback):
    - `src/bayesian_metamodeling/surrogates/dataset.py`
  - Tutorial updates:
    - `tutorials/Tutorial_1.ipynb` now reads centralized `sweep_rows.csv` and renders two heatmaps (`sum`, `product`)
    - helper module for Tutorial 1 heatmap loading:
      - `src/bayesian_metamodeling/tutorials/toy_heatmap.py`
  - Test updates:
    - `tests/test_run_pipeline.py` now validates centralized sweep CSV and serial-vs-parallel equivalence
    - `tests/test_sweep_store.py` added for flattening and deterministic CSV order
    - `tests/test_tutorial_toy_heatmap.py` added for Tutorial 1 CSV-to-heatmap parsing
    - `tests/test_surrogate_dataset_loading.py` now covers centralized sweep dataset loading
    - `tests/test_modelspec_validation.py` now covers `sweep_mode`/`workers`
    - `tests/test_biomodels_slow.py` updated to consume centralized sweep rows
    - optional MPI integration test:
      - `tests/test_mpi_sweep_integration.py`
  - Schema/docs updates:
    - `src/bayesian_metamodeling/spec/modelspec.schema.json`
    - `README.md`, `tutorials/README.md`, `PRD.md`, `TechSpec.md`, `CodeDesign.md`, `TEST_PLAN.md`, `PROMPT_TO_CODEX.md`
- Runner/env portability + optional backend test controls (2026-02-12):
  - Added optional `runner.execution_env` to `ModelSpec` (`default={}`), currently supporting:
    - `conda_env` (validated key; whitespace normalized).
  - Plumbed `runner.execution_env` through adapter materialization into local process runner:
    - `src/bayesian_metamodeling/adapters/base.py`
    - `src/bayesian_metamodeling/adapters/python_cli.py`
    - `src/bayesian_metamodeling/adapters/biomodels_sbml.py`
    - `src/bayesian_metamodeling/runners/local_process.py`
  - Local runner behavior:
    - If `conda_env` is set, run commands via `conda run -n <conda_env> ...`.
    - If no `conda_env` and command starts with `python` but no `python` on PATH, fallback to current `sys.executable`.
  - Removed hardcoded environment names from runtime backend dependency error messages:
    - now uses generic `conda install -n <env_name> ...` guidance.
  - Added optional backend test controls and reporting:
    - env flag: `MM_SKIP_OPTIONAL_BACKEND_TESTS=1`
    - pytest report header now prints optional backend availability and skip-flag state
    - optional backend tests are marked and can be skipped explicitly via the flag
    - files:
      - `tests/backend_support.py`
      - `tests/conftest.py`
      - `tests/test_surrogate_backends.py`
      - `tests/test_surrogate_backend_hardening.py`
      - `pytest.ini`
  - Added tests for env execution behavior and ModelSpec validation:
    - `tests/test_local_process_runner.py`
    - `tests/test_modelspec_validation.py`
  - Regenerated schema artifact:
    - `src/bayesian_metamodeling/spec/modelspec.schema.json`
  - Created permanent backend-specific conda environments:
    - `/Users/barak/miniconda3/envs/py312_bayesmm_pymc`
    - `/Users/barak/miniconda3/envs/py312_bayesmm_sbi`
  - Renamed PyMC env prefix to match actual Python version:
    - removed `/Users/barak/miniconda3/envs/py314_bayesmm_pymc`
    - active env is `/Users/barak/miniconda3/envs/py312_bayesmm_pymc`
  - Installed backend stacks:
    - `py312_bayesmm_pymc`: Python `3.12.12`, `pymc 5.27.1`, `arviz 0.23.4`
    - `py312_bayesmm_sbi`: Python `3.12.12`, `torch 2.10.0`, `sbi 0.23.3`
  - Verified both PyMC tracks in the renamed env:
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTENSOR_FLAGS='cxx=' PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_pymc/bin/python -m pytest -q tests/test_surrogate_backends.py -k pymc_gp_backend_fit_sample_and_logprob` -> `1 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTENSOR_FLAGS='cxx=' PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_pymc/bin/python -m pytest -q tests/test_metamodel_sampling.py -k two_surrogates` -> `1 passed`
  - Validation commands (passed):
    - `ruff format .`
    - `ruff check .`
    - `pytest -q -m "not slow"`
- Scaffold created:
  - Python package skeleton under `src/bayesian_metamodeling/` including target subpackages from TechSpec.
  - `pyproject.toml` added with setuptools build, Python package metadata, and CLI entry point `mm`.
  - Minimal CLI scaffold at `src/bayesian_metamodeling/cli/main.py`.
  - Baseline pytest smoke test at `tests/test_scaffold_smoke.py`.
  - Git hooks implemented in `githooks/`:
    - `pre-commit` runs format/lint/fast tests, blocks main/master commits by default, and enforces `Status.md` staging when `src/` or `examples/` are staged.
    - `pre-push` runs fast tests.
    - `commit-msg` enforces conventional commit style.
  - Hook logs path standardized to `tmp/hook_logs/`.
  - `tmp/` confirmed gitignored.
- Design validation artifacts created:
  - `CodeDesign.md` added with explicit spec family (`ModelSpec` / `SurrogateSpec` / `CouplingSpec` / `MetaModelSpec`) and concrete workflow mapping.
  - Three-model coupling example spec added:
    - `examples/coupled/spec.three_model_coupling.json`
  - BioModels execution + surrogate-spec examples added:
    - `examples/biomodels/spec.model1907260003.json`
    - `examples/biomodels/surrogate.model1907260003.json`
  - `TechSpec.md` and `README.md` updated to reference design-validation scenarios and `CodeDesign.md`.
- Prompt 1 implemented:
  - Added typed Pydantic v2 spec model hierarchy in `src/bayesian_metamodeling/spec/modelspec.py`:
    - `ModelSpec`, `VariableSpec`, `AdapterSpec`, `RunnerSpec` and nested contract models.
  - Added schema export helper in `src/bayesian_metamodeling/spec/schema.py`.
  - Added JSON schema artifact:
    - `src/bayesian_metamodeling/spec/modelspec.schema.json`
  - Added `bayesmm validate <spec>` command with actionable validation output in:
    - `src/bayesian_metamodeling/cli/main.py`
  - Added fast tests in:
    - `tests/test_modelspec_validation.py`
  - Added shared test path setup in:
    - `tests/conftest.py`
- Prompt 2 implemented:
  - Added DOE planner module in:
    - `src/bayesian_metamodeling/designs/planner.py`
  - Added strategy support:
    - `grid` cartesian product planning
    - `sobol` deterministic low-discrepancy planning with bounds scaling
  - Added `bayesmm plan <spec>` CLI command with deterministic preview output.
  - Added fast tests in:
    - `tests/test_doe_planner.py`
- Prompt 3 implemented:
  - Added adapter interfaces and registry:
    - `src/bayesian_metamodeling/adapters/base.py`
    - `src/bayesian_metamodeling/adapters/python_cli.py`
    - `src/bayesian_metamodeling/adapters/registry.py`
  - Added local process runner:
    - `src/bayesian_metamodeling/runners/local_process.py`
  - Added run store + registry with provenance and stdout/stderr references:
    - `src/bayesian_metamodeling/storage/run_store.py`
  - Added CLI commands:
    - `bayesmm run <spec>`
    - `bayesmm runs list`
    - `bayesmm runs show <run_id>`
  - Added toy executable program:
    - `examples/toy_program/run.py`
  - Added fast end-to-end integration test:
    - `tests/test_run_pipeline.py`
- Prompt 4 implemented:
  - Added BioModels SBML adapter baseline:
    - `src/bayesian_metamodeling/adapters/biomodels_sbml.py`
  - Added SBML worker script for simulation:
    - `src/bayesian_metamodeling/adapters/biomodels_worker.py`
  - Adapter registry now resolves `biomodels_sbml_adapter_v1`.
  - Added BioModels example spec:
    - `examples/biomodels/spec.prompt4.model1907260003.json`
  - Added slow integration test:
    - `tests/test_biomodels_slow.py`
- Prompt 5 implemented:
  - Added typed placeholder surrogate spec:
    - `src/bayesian_metamodeling/spec/surrogate.py`
  - Added typed placeholder metamodel spec:
    - `src/bayesian_metamodeling/spec/metamodel.py`
  - Added CLI placeholder commands:
    - `bayesmm surrogate fit <spec>`
    - `bayesmm surrogate eval <spec>`
    - `bayesmm meta build <spec>`
  - Added fast tests for placeholder CLI wiring:
    - `tests/test_surrogate_meta_placeholders.py`
- Prompt 6 implemented:
  - Refined `SurrogateSpec` to backend-neutral contract fields (`kind`, `inputs`, `outputs`, `backend`, `backend_config`, `dataset_ref`, `seed`).
  - Added backend-neutral `SurrogateModel` wrapper interface:
    - `src/bayesian_metamodeling/surrogates/base.py`
  - Added metamodel IR schema and helpers:
    - `src/bayesian_metamodeling/meta/ir.py`
  - Added compiler boundary:
    - `src/bayesian_metamodeling/meta/compiler.py`
    - `compile_metamodel(..., backend=\"pymc\")` implemented
    - `compile_metamodel(..., backend=\"numpyro\")` stubbed with clear `NotImplementedError`
  - Added metamodel IR builder + artifact store:
    - `src/bayesian_metamodeling/meta/builder.py`
    - `src/bayesian_metamodeling/storage/meta_store.py`
  - Updated CLI:
    - `bayesmm meta build <spec>` now writes IR artifact to `tmp/metamodel_ir/` and registers it in `tmp/meta_registry.json`
  - Added tests:
    - IR roundtrip serialization: `tests/test_meta_ir_roundtrip.py`
    - Compiler smoke with mocked surrogate factor: `tests/test_meta_compiler_smoke.py`
    - Generic fit-quality tests with increasing challenge: `tests/test_surrogate_fit_quality_generic.py`
- Prompt 7 implemented:
  - Added backend implementations behind wrapper contract:
    - `pymc_gp` (pragmatic linear-Gaussian baseline API)
    - `sbi_npe` (pragmatic linear-Gaussian baseline API)
    - module: `src/bayesian_metamodeling/surrogates/backends.py`
  - Added dataset loader from canonical run store:
    - `src/bayesian_metamodeling/surrogates/dataset.py`
    - no implicit downsampling/thinning
  - Added backend-neutral surrogate artifact persistence:
    - `src/bayesian_metamodeling/storage/surrogate_store.py`
    - includes spec digest, dataset digest, variable lists, seed, dependency versions
  - Added surrogate fit/eval service layer:
    - `src/bayesian_metamodeling/surrogates/service.py`
  - Updated CLI:
    - `bayesmm surrogate fit surrogate.json`
    - `bayesmm surrogate eval surrogate.json --inputs '<json>' --n 1000`
  - Added examples:
    - `examples/surrogates/surrogate.toy.pymc_gp.json`
  - Added fast tests:
    - `tests/test_surrogate_backends.py`
    - updated `tests/test_surrogate_meta_placeholders.py` for real fit/eval flow
- Prompt 8 implemented:
  - Added MetamodelSpec v1 fields in `src/bayesian_metamodeling/spec/metamodel.py`:
    - `ppl_backend`, `surrogate_refs`, `variables`, `couplings`, `priors`
  - Updated IR builder to load surrogate artifacts and include surrogate likelihood factors:
    - `src/bayesian_metamodeling/meta/builder.py`
  - Added metamodel sampling module and artifacts:
    - `src/bayesian_metamodeling/meta/sampling.py`
    - stores `inference_data.json` and canonical `samples_dataset.json`
    - registry: `tmp/metamodel_samples_registry.json`
  - Updated CLI:
    - `bayesmm meta build metamodel.json`
    - `bayesmm meta sample metamodel.json --draws D --tune T --chains C --seed S`
    - backend behavior:
      - `pymc`: sampling path implemented
      - `numpyro`: explicit `NotImplementedError` pending Prompt 9
  - Added example metamodel specs/artifacts:
    - `examples/metamodels/metamodel.simple.json`
    - `examples/coupled/spec.three_model_coupling.json` updated to v1 structure
  - Added fast synthetic integration test:
    - `tests/test_metamodel_sampling.py`
- Prompt 9 implemented:
  - Enabled `compile_metamodel(ir, backend=\"numpyro\")` path:
    - `src/bayesian_metamodeling/meta/compiler.py`
  - Enabled `ppl_backend: \"numpyro\"` sampling mode using same metamodel spec interface:
    - `src/bayesian_metamodeling/meta/sampling.py`
  - Kept canonical sample storage format aligned with pymc path:
    - `inference_data.json`
    - `samples_dataset.json`
  - Added fast backend integration test:
    - `tests/test_metamodel_sampling_numpyro.py`
  - Added backend-switch documentation and known numerical differences in `README.md`.
- Prompt 10 implemented:
  - Added guided CLI command:
    - `bayesmm tutorial`
  - Added artifact listing commands:
    - `bayesmm surrogate list`
    - `bayesmm meta list`
  - Hardened artifact metadata fields across surrogate/meta artifacts:
    - `spec_digest`
    - `dataset_digest`
    - `dependency_versions`
    - `seed`
  - Added end-to-end quickstart block in `README.md`.
  - Added fast UX/repro tests:
    - `tests/test_cli_ux_commands.py`
- Documentation update:
  - Linked tutorial notebooks from:
    - `README.md`
    - `tutorials/README.md`
  - Refreshed tutorial after Prompts 6-10 to reflect real commands and backend behavior:
    - `bayesmm tutorial`
    - `bayesmm surrogate list`
    - `bayesmm meta list`
    - real surrogate fit/eval and metamodel build/sample flow
- Tutorial architecture update (modular track):
  - Added `tutorials/` subfolder with 9-part progression and notebook hub:
    - `tutorials/Tutorial_0.ipynb`
    - `tutorials/Tutorial_1.ipynb` ... `tutorials/Tutorial_9.ipynb`
  - Added tutorial-specific runnable specs and artifact stubs:
    - `tutorials/specs/`
    - `tutorials/artifacts/`
  - Added standalone vs serial execution guidance, prerequisites, estimated times, checkpoints, and troubleshooting in each notebook.
  - Converted tutorials to notebook-only delivery by retiring `tutorials/Tutorial_*.md` files.
  - Re-pointed top-level docs:
    - `README.md` now links to notebook-only tutorial track.
    - tutorials are indexed from `tutorials/README.md` and `tutorials/Tutorial_0.ipynb`.
- Prompt 11 implemented:
  - Replaced placeholder `pymc_gp` backend with a real PyMC probabilistic fit path in:
    - `src/bayesian_metamodeling/surrogates/backends.py`
  - Added posterior-based surrogate methods (`sample`, `log_prob`, `summary`) backed by PyMC posterior draws.
  - Added actionable missing-dependency error for `pymc_gp` with conda/pip install guidance.
  - Added warning-safe PyMC import path to avoid ArviZ startup warning failures under `filterwarnings = error`.
  - Added backend dependency version capture and persistence into surrogate artifacts:
    - `src/bayesian_metamodeling/surrogates/service.py`
    - `src/bayesian_metamodeling/storage/surrogate_store.py`
  - Added optional dependency extra for PyMC:
    - `pyproject.toml`
  - Updated tests for real PyMC backend behavior and graceful skip/error handling:
    - `tests/test_surrogate_backends.py`
  - Strengthened PyMC fit test with a real-learning quality assertion (bounded predictive MSE on synthetic mapping).
  - Updated user docs with backend install and behavior notes:
    - `README.md`
    - `tutorials/Tutorial_0.ipynb`
- Prompt 12 implemented:
  - Replaced placeholder `sbi_npe` backend with real SBI NPE fit/eval flow in:
    - `src/bayesian_metamodeling/surrogates/backends.py`
  - Added dependency guards with actionable runtime errors for missing `sbi` / `torch`.
  - Added warning-safe SBI training path to ignore known non-fatal 1D-flow warning under `filterwarnings = error`.
  - Added persisted SBI backend payload format:
    - model type `sbi_npe_posterior`
    - serialized posterior payload via torch-save + base64
    - normalization metadata (`x_mean`, `x_scale`, `y_mean`, `y_scale`)
  - Added optional dependency extra for SBI:
    - `pyproject.toml`
  - Added/updated tests:
    - real SBI backend fit/eval test (skip-safe when dependency missing)
    - SBI missing-dependency actionable error test
    - backend selection helpers for integration tests so fast suite remains stable without optional deps
  - Updated docs with SBI install and verification commands:
    - `README.md`
    - `tutorials/Tutorial_0.ipynb`
- Prompt 13 implemented:
  - Added explicit backend-config validation contract with actionable errors:
    - `src/bayesian_metamodeling/surrogate_config.py`
    - wired into `SurrogateSpec` validation in `src/bayesian_metamodeling/spec/surrogate.py`
  - Added strict artifact compatibility checks during eval:
    - backend mismatch detection
    - artifact input/output signature mismatch detection
    - payload input/output order mismatch detection
    - backend payload presence check
    - module: `src/bayesian_metamodeling/surrogates/service.py`
  - Added backend payload signature checks at load boundary:
    - module: `src/bayesian_metamodeling/surrogates/backends.py`
  - Improved CLI robustness for surrogate fit/eval failures:
    - clear `Surrogate fit failed: ...` / `Surrogate eval failed: ...` messages
    - module: `src/bayesian_metamodeling/cli/main.py`
  - Hardened artifact metadata for IO compatibility:
    - added `io_signature` fields in `src/bayesian_metamodeling/storage/surrogate_store.py`
  - Added dedicated hardening tests:
    - `tests/test_surrogate_backend_hardening.py`
      - backend_config key/value validation
      - backend mismatch and signature mismatch guards
      - malformed/missing eval payload and artifact CLI errors
      - optional dual-backend integration path (slow, dependency-gated)
  - Added troubleshooting section for surrogate fit/eval guardrails:
    - `README.md`
- Prompt 15 implemented:
  - Converted tutorial delivery to notebook-only (`.ipynb`) in:
    - `tutorials/Tutorial_0.ipynb` ... `tutorials/Tutorial_9.ipynb`
  - Removed markdown tutorial duplicates:
    - retired `tutorials/Tutorial_*.md`
  - Upgraded onboarding structure across all tutorials:
    - estimated time
    - prerequisites/dependencies
    - success criteria
    - runnable checkpoints
    - troubleshooting/fallback guidance
  - Synchronized tutorial architecture across docs:
    - `README.md`
    - `tutorials/README.md`
    - `PRD.md`
    - `TechSpec.md`
    - `CodeDesign.md`
    - `PROMPT_TO_CODEX.md`
- Tutorial hardening pass (post-Prompt 15):
  - Fixed surrogate tutorial blocker in dataset parsing:
    - `src/bayesian_metamodeling/surrogates/dataset.py`
    - now supports adapter output envelope shape `{out_name: {\"inputs\": ..., out_name: [...]}}`.
  - Added regression coverage:
    - `tests/test_surrogate_dataset_loading.py`
  - Notebook quality-gate compatibility:
    - `pyproject.toml` updated with Ruff `extend-exclude = [\"*.ipynb\"]` so docs notebooks do not break repo lint gate.
  - Regenerated tutorial notebooks with richer guided pedagogy:
    - explicit prerequisites, time estimates, success criteria, and troubleshooting.
    - added graphics/plots in each tutorial notebook.
    - removed manual `RUN_ID` placeholder in Tutorial 1 (auto-selects latest tutorial run).
  - Validation results:
    - `ruff format .` / `ruff check .` / `pytest -q -m \"not slow\"` pass in `py314_bayesmm`.
    - PyMC and SBI tutorial fit/eval commands verified in dependency-capable env:
      - `tmp/conda_pymc_verify`.
    - New dataset parser regression test passes:
      - `pytest -q tests/test_surrogate_dataset_loading.py`
- SBI module verification + Tutorial 6 portability hardening (2026-02-20):
  - Updated `tutorials/Tutorial_6.ipynb` to remove machine-specific absolute paths:
    - Bash cells now auto-detect repo root when notebook runs from either repo root or `tutorials/`.
    - Step 3 spec-loading cell now resolves `tutorials/specs/surrogate.toy.sbi_npe.json` from detected repo root.
    - Tutorial checkpoint test command now uses `PYTHONPATH=src python -m pytest ...` instead of bare `pytest`.
  - Added regression coverage for Tutorial 6 portability:
    - `tests/test_tutorial_sbi_notebook.py`
  - Environment fixes applied to support real SBI validation in the dedicated SBI env:
    - Installed `pytest` and `pydantic` into `/Users/barak/miniconda3/envs/py312_bayesmm_sbi`.
  - Validation results (2026-02-20):
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_tutorial_sbi_notebook.py` -> `1 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_surrogate_backends.py -k sbi` -> `2 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests -k \"sbi or tutorial\"` -> `5 passed`
    - `/Users/barak/miniconda3/envs/py314_bayesmm/bin/ruff format .` -> no changes
    - `/Users/barak/miniconda3/envs/py314_bayesmm/bin/ruff check .` -> passed
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py314_bayesmm/bin/python -m pytest -m \"not slow\" -ra` -> passed (`47 passed`, `8 skipped`, `3 deselected`)
- Optional-backend fast-suite hardening for mixed PyMC/SBI environments (2026-02-20):
  - Added PyMC runtime-constraint classifier for optional backend tests:
    - `tests/backend_support.py` (`is_pymc_runtime_constraint`)
  - Routed SBI training summary logs from repo root into `tmp/`:
    - `src/bayesian_metamodeling/surrogates/backends.py`
      - added `_make_sbi_summary_writer()` and wired it into `_build_sbi_inference(...)`
      - default SBI tensorboard output now writes under `tmp/sbi-logs/` (fallback no-op writer when unavailable)
  - Added regression coverage for SBI log root location:
    - `tests/test_surrogate_backends.py::test_make_sbi_summary_writer_uses_tmp_log_root`
  - Synchronized main-folder docs with backend/runtime behavior and log-path policy:
    - `README.md`
    - `PRD.md`
    - `TechSpec.md`
    - `CodeDesign.md`
    - `TEST_PLAN.md`
    - `PROMPT_TO_CODEX.md`
  - Cleaned obsolete root-level SBI log artifact:
    - removed untracked `sbi-logs/` (old runs); active log path remains `tmp/sbi-logs/`.
  - Hardened optional backend tests to skip/fallback on toolchain-limited PyMC runtime failures while still executing SBI paths:
    - `tests/test_surrogate_backends.py`
      - `test_pymc_gp_backend_fit_sample_and_logprob` now skips with explicit runtime-constraint reason when PyMC cannot compile locally.
      - `test_backend_specific_fit_quality_increasing_difficulty` now falls back to `sbi_npe` when PyMC is installed but not runtime-usable.
  - Validation result (no `PYTENSOR_FLAGS` override):
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -m \"not slow\" -ra` -> passed (`54 passed`, `1 skipped`, `3 deselected`)
- SBI backend extensive test expansion (2026-02-20):
  - Added a dedicated SBI unit/behavior coverage file:
    - `tests/test_sbi_backend_extended.py`
  - New tests added: `20` (SBI-focused), covering:
    - `SbiNPEPosteriorModel` input normalization, sampling shape/seed behavior, denormalization, `log_prob` jacobian correction, length mismatch errors, and summary statistics.
    - `_make_sbi_summary_writer` fallback behavior when tensorboard writer import is unavailable.
    - `_build_sbi_inference` NPE-first path and SNPE fallback path.
    - `_train_sbi_density_estimator` full-kwargs train path and compatibility fallback-on-`TypeError`.
    - `_fit_sbi_npe` normalization details (including constant-feature scaling guard) and default/configured `summary_samples`.
    - SBI payload persistence and loading (`save_backend_payload` + `load_backend_model` for `sbi_npe_posterior`).
    - `fit_backend_model` SBI dispatch + invalid-density-estimator rejection.
  - Validation results:
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py314_bayesmm/bin/python -m pytest -q tests/test_sbi_backend_extended.py -ra` -> `20 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_sbi_backend_extended.py -ra` -> `20 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_surrogate_backends.py -k sbi -ra` -> `3 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_surrogate_backend_hardening.py -ra` -> `7 passed`, `1 skipped` (optional dual-backend runtime constraint)
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py314_bayesmm/bin/python -m pytest -m \"not slow\" -ra` -> passed (`67 passed`, `8 skipped`, `3 deselected`)
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -m \"not slow\" -ra` -> passed (`74 passed`, `1 skipped`, `3 deselected`)

## Provenance log (design verification runs)
- BioModels sample source used:
  - `https://www.ebi.ac.uk/biomodels/services/download/get-files/MODEL1907260003/2/lever2014%20v5.0.xml`
- Local artifact:
  - `tmp/biomodels/MODEL1907260003_lever2014_v5_0.xml`
- Artifact digest (SHA256):
  - `bb58b84e80f11b7cea87393bb8b79247e0c13fa9c5347a13c65b341d70a3b94e`
- Simulation driver:
  - `tmp/scripts/simulate_lever_model.py`
- Driver digest (SHA256):
  - `d35ac97d4df556fb960f3b25dd2ea56d13990da7d8723fd838633f93d4921dd0`
- Executed scenarios (seeds): baseline=101, param_low=102, param_high=103
- Scanned parameter:
  - `k_on` with values `[0.00008, 0.0001, 0.00012]`
- Output summary:
  - `tmp/biomodels/simulations_MODEL1907260003/summary.json`
- Summary digest (SHA256):
  - `1bce50952d5df74eb399dff9f247efbf250541315b22c407884d033347178536`
- Run logs:
  - `tmp/run_logs/biomodel_download_lever.stderr.log`
  - `tmp/run_logs/biomodel_sim_lever.stdout.log`
  - `tmp/run_logs/biomodel_sim_lever.stderr.log`
- PyMC verification run (Prompt 11 acceptance backfill):
  - Verification environment:
    - `tmp/conda_pymc_verify` (Python `3.11.14`, PyMC `5.27.1`, ArviZ `0.23.4`)
  - Command:
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTENSOR_FLAGS='cxx=' PYTHONPATH=src /Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/conda_pymc_verify/bin/pytest -q tests/test_surrogate_backends.py -k pymc_gp_backend_fit_sample_and_logprob`
  - Result:
    - `1 passed` (2026-02-11)
  - Note:
    - `PYTENSOR_FLAGS='cxx='` was required in this sandbox to avoid missing local C++ stdlib/toolchain headers during PyTensor compilation.
- SBI verification run (Prompt 12 acceptance backfill):
  - Verification environment:
    - `tmp/conda_pymc_verify` (Python `3.11.14`, SBI `0.25.0`, Torch `2.5.1`)
  - Command:
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/conda_pymc_verify/bin/pytest -q tests/test_surrogate_backends.py -k sbi_npe_backend_fit_sample_and_logprob`
  - Result:
    - `1 passed` (2026-02-11)
- SBI + Tutorial 6 verification run (2026-02-20):
  - Verification environment:
    - `/Users/barak/miniconda3/envs/py312_bayesmm_sbi` (Python `3.12.12`, SBI `0.23.3`, Torch `2.10.0`, Pydantic `2.12.5`, Pytest `9.0.2`)
  - Spec digests (SHA256):
    - `tutorials/specs/model.toy.grid.json`: `1e9932106f67261a6ca49ed389e332cef20711d978e455e8234f9d1aae9858ae`
    - `tutorials/specs/surrogate.toy.sbi_npe.json`: `7cfd28482379c5327b3d556376d669141d3c5d12540e4172f5b8e84d8755d2f8`
  - Tutorial commands:
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m bayesian_metamodeling.cli.main run tutorials/specs/model.toy.grid.json`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m bayesian_metamodeling.cli.main surrogate fit tutorials/specs/surrogate.toy.sbi_npe.json`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m bayesian_metamodeling.cli.main surrogate eval tutorials/specs/surrogate.toy.sbi_npe.json --inputs '{\"a\":[0.25,0.75,1.25,1.75],\"b\":[0.2,0.6,1.0,1.4]}' --n 200`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_surrogate_backends.py -k sbi_npe_backend_fit_sample_and_logprob`
  - Outputs:
    - Sweep run id: `318336745d994b8abd053abfe8427b83` (`9/9` successful points)
    - Surrogate artifact id: `e43a8159607e44eca97700c76fd90c4b`
    - Eval summary (`n=4`, `posterior_draws=256`):
      - `mean=[0.421676390359283, 1.3336015344047611, 2.249973503133714, 3.1773650763390755]`
      - `std=[0.00926032403558707, 0.006743305751872682, 0.005223104873577676, 0.007056205854447724]`
  - Artifact digest (SHA256):
    - `tmp/surrogate_artifacts/e43a8159607e44eca97700c76fd90c4b/artifact.json`: `0eb8f17692b10673cbf3bb16884aa35751dc0734c317fe159b446450fdc95e10`
  - Logs:
    - `tmp/sbi_verify_2026-02-20/tutorial6_step1_run.log`
    - `tmp/sbi_verify_2026-02-20/tutorial6_step2_fit.log`
    - `tmp/sbi_verify_2026-02-20/tutorial6_step2_eval.log`
    - `tmp/sbi_verify_2026-02-20/tutorial6_step4_pytest.log`

### 2026-03-04: Security hardening audit and remediation
- Performed comprehensive security audit and applied fixes across 9 files:
  - **C1 (Critical)**: `surrogates/backends.py` — added type validation on `torch.load` deserialized objects (must implement `sample`/`log_prob` posterior interface)
  - **H1 (High)**: `adapters/python_cli.py` — added entrypoint path confinement to repo root
  - **H2 (High)**: `adapters/python_cli.py` — added path traversal guard on output mapping paths (confined to `run_dir`)
  - **H3 (High)**: `storage/run_store.py` — added registry path confinement (must resolve within CWD or `tmp/`)
  - **H4 (High)**: `spec/modelspec.py` — added regex validation for `conda_env` names (rejects injection characters)
  - **M1 (Medium)**: `surrogates/dataset.py` — added `..` traversal guard on dataset paths
  - **M2 (Medium)**: `surrogates/service.py` — replaced predictable temp file with UUID-based name + `finally` cleanup
  - **M4 (Medium)**: `adapters/biomodels_sbml.py` — added explicit `verify=True` on `requests.get`
  - **L1 (Low)**: `spec/modelspec.py` — added `..` traversal guard on `storage.root` validator
- Added security test suite: `tests/test_security_hardening.py` (23 tests covering all guards)
- Validation: `ruff format .`, `ruff check .`, `pytest -q -m "not slow"` all pass

## Next steps, ordered
1) Run optional MPI integration path under `mpirun` and record environment/result details
2) Migrate remaining tutorial notebooks that still read legacy `runs/*` folders to centralized sweep paths
3) Extend centralized sweep schema validation for higher-dimensional/non-scalar outputs

## Decisions log
- 2026-02-11: Prioritize execution/reproducibility core before advanced Bayesian coupling.
- 2026-02-11: Freeze v1 to local runner + typed contracts + run provenance; defer full surrogate/meta inference.
- 2026-02-11: Enforce explicit no-downsampling policy in docs and prompt pack.
- 2026-02-11: Scaffold step implemented with strict hooks and no modeling logic added.
- 2026-02-11: Main-branch commit blocking hook includes explicit override (`ALLOW_MAIN_COMMIT=1`) to support controlled bootstrap commits.
- 2026-02-11: Added pre-implementation `CodeDesign.md` to lock target interfaces against a three-model coupling use case and a real BioModels sample use case.
- 2026-02-11: BioModels sample verification executed against MODEL1907260003 with logged three-scenario parameter scan (no downsampling).
- 2026-02-11: Prompt 1 implemented using Pydantic v2 contracts and explicit schema artifact generation.
- 2026-02-11: Prompt 2 implemented with deterministic DOE planning for `grid` and `sobol`.
- 2026-02-11: Prompt 3 implemented with adapter/runner/storage separation and run registry CLI.
- 2026-02-11: Prompt 4 implemented with BioModels SBML adapter baseline and slow integration test path.
- 2026-02-11: Prompt 5 implemented as typed contract placeholders only; no inference logic added.
- 2026-02-11: Added tutorial-first usage guide to reduce onboarding friction before full implementation.
- 2026-02-11: Prompt 6 added backend-neutral IR and compiler boundary before binding runtime inference backends.
- 2026-02-11: Prompt 7 introduced concrete backend names and artifact contracts while keeping user-facing surrogate interface stable.
- 2026-02-11: Prompt 8 implemented metamodel build/sample flow with backend-gated behavior and canonical sample artifacts.
- 2026-02-11: Prompt 9 enabled backend switching (`pymc`/`numpyro`) without changing metamodel JSON interface.
- 2026-02-11: Prompt 10 added UX commands and reproducibility metadata guarantees for emitted artifacts.
- 2026-02-11: Tutorial and README backend notes updated to remove stale placeholder/stub language.
- 2026-02-11: Added prompts 11-13 in `PROMPT_TO_CODEX.md` to implement real `pymc_gp` and `sbi_npe` backends plus compatibility hardening.
- 2026-02-11: Prompt 11 implemented real PyMC-backed surrogate learning for `pymc_gp` with persisted posterior payload and optional dependency handling.
- 2026-02-11: Prompt 11 acceptance criteria retroactively tightened to require at least one executed real-PyMC verification test run and log in `Status.md`.
- 2026-02-11: Verified real PyMC surrogate learning test passes in isolated conda env (`tmp/conda_pymc_verify`) using PyTensor non-C fallback.
- 2026-02-11: Prompt 12 implemented real SBI NPE surrogate learning path with persisted posterior payload and dependency-gated tests.
- 2026-02-11: Prompt 12 acceptance criteria retroactively tightened to require at least one executed real-SBI verification test run and log in `Status.md`.
- 2026-02-11: Verified real SBI surrogate learning test passes in isolated conda env (`tmp/conda_pymc_verify`).
- 2026-02-11: Prompt 13 implemented backend-config validation, artifact compatibility checks, and improved surrogate CLI error reporting.
- 2026-02-12: Consolidated tutorial requests into Prompt 14 and implemented a modular 9-part tutorial curriculum with BioModels moved early and per-tutorial scientific side-aims.
- 2026-02-12: Prompt 15 converted tutorials to notebook-only delivery and upgraded onboarding structure (time estimates, prerequisites, success criteria, checkpoints, troubleshooting).
- 2026-02-12: Hardened tutorial execution by fixing surrogate dataset envelope parsing and regenerating all notebooks with guided explanations and graphics.
- 2026-02-12: Introduced `runner.execution_env` (default empty) and explicit `conda_env` support so runtime environment is user-configurable via JSON, not hardcoded.
- 2026-02-12: Added `MM_SKIP_OPTIONAL_BACKEND_TESTS` to make optional backend tests warning/skip-friendly when `pymc`/`sbi` are intentionally unavailable.
- 2026-02-12: Created dedicated backend conda envs and installed `pymc`/`sbi` stacks there; kept the main project env skip-safe.
- 2026-02-12: Renamed `py314_bayesmm_pymc` to `py312_bayesmm_pymc` and re-verified surrogate-PyMC plus metamodel-PyMC test tracks in the renamed env.
- 2026-02-12: Updated `tutorials/Tutorial_0.ipynb` to run no install commands at all; replaced with a manual "Loading environment" guidance box and commented conda examples (`py314_bayesmm` kept as recommendation/example only).
- 2026-02-15: Removed redundant root tutorial files (`TUTORIAL.md`, `TUTORIAL.ipynb`); tutorials now live only under `tutorials/` with `tutorials/Tutorial_0.ipynb` as the entry point.
- 2026-02-15: Hardened `tutorials/Tutorial_0.ipynb` preflight cell to auto-detect repo root from either repo-root or `tutorials/` execution context; verified by executing notebook end-to-end in `py314_bayesmm` (`tmp/Tutorial_0.executed.ipynb`).
- 2026-02-15: Commit pass: finalized runner `execution_env` plumbing (spec validation, adapter materialization, local runner conda prefixing, and dedicated runner/spec tests).
- 2026-02-15: Commit pass: finalized optional-backend test controls (`optional_backend` marker + `MM_SKIP_OPTIONAL_BACKEND_TESTS`) and generalized backend install guidance to use `<env_name>`.
- 2026-02-15: Refined `tutorials/Tutorial_0.ipynb` for safer onboarding (manual install guidance only, no hardcoded path/env assumptions) and re-validated notebook execution (`tmp/Tutorial_0.executed.ipynb`).
- 2026-02-15: Simplified `tutorials/Tutorial_0.ipynb` to a standard notebook flow: explicit "use a pre-set kernel environment" guidance, CLI preflight with `PYTHONPATH` wiring, manual/commented install examples only, and successful end-to-end execution check (`tmp/Tutorial_0.executed.ipynb`).
- 2026-02-15: Expanded `examples/toy_program/run.py` module docstring to document toy-run behavior and its role in local integration testing.
- 2026-02-15: Added Prompt 17 design package (PRD/TechSpec/CodeDesign/TEST_PLAN/PROMPT_TO_CODEX updates) for centralized DOE sweep CSV output and synchronized serial/local-parallel/MPI writing; no runtime implementation in this step.
- 2026-02-15: Completed Prompt 17 implementation with centralized sweep artifacts, synchronized serial/local-parallel/MPI execution modes, Tutorial 1 dual-heatmap update, and updated fast/slow test coverage.
- 2026-02-15: Hardened `tutorials/Tutorial_1.ipynb` against stale registry paths and missing prior sweep records by auto-running the toy sweep when needed; verified end-to-end notebook execution to `tmp/Tutorial_1.executed.ipynb`.
- 2026-02-15: Refactored `tutorials/Tutorial_1.ipynb` CLI helper naming/usage to `run_mm_cli` consistently (removed mixed `run_mm`/`run_mm_CLI` calls and shell-style invocation remnants).
- 2026-02-15: Refactored `tutorials/Tutorial_2.ipynb` to notebook-native CLI execution via `run_mm_cli`, added dense/wider `k_on` sweep generation (11-point grid over `[8e-05, 1.2e-04]`), switched analysis to centralized sweep CSV parsing, and added time-vs-`k_on` heatmap plus biological interpretation guidance.
- 2026-02-15: Hardened `tutorials/Tutorial_2.ipynb` for offline BioModels execution by seeding dense-run SBML cache from existing local cache/file when available; fixed heatmap parsing to use centralized columns (`time_series__rows__json` + `time_series__columns__*`).
- 2026-02-15: Verified Tutorial 2 in `py313_metamodeling_pymc` using notebook code cells (3/5/7/9): dense BioModels run completed successfully with 11/11 successful points (`run_id=ed4db1e01b1d449684784f5503fa56f8`).
- 2026-02-20: Hardened `tutorials/Tutorial_6.ipynb` for portable execution (no hardcoded local paths) and added a regression test to lock this behavior.
- 2026-02-20: Optional backend tests now treat PyMC compile/toolchain failures as runtime constraints (skip/fallback) so SBI-enabled environments can still pass the fast suite without forcing `PYTENSOR_FLAGS='cxx='`.
- 2026-02-20: Routed SBI training logs to `tmp/sbi-logs/` to prevent root-level `sbi-logs/` workspace pollution and added explicit coverage for this path.
- 2026-02-20: Updated root docs (`README.md`, `PRD.md`, `TechSpec.md`, `CodeDesign.md`, `TEST_PLAN.md`, `PROMPT_TO_CODEX.md`) to reflect optional-backend runtime behavior and SBI log-path policy.
- 2026-02-20: Removed stale root `sbi-logs/` directory left by earlier SBI runs; canonical location is `tmp/sbi-logs/`.
- 2026-02-20: Added a dedicated 20-test SBI backend coverage suite (`tests/test_sbi_backend_extended.py`) and re-validated both baseline and SBI-enabled fast suites.
- 2026-02-20: Hardened optional backend imports for sandboxed environments by routing ArviZ/matplotlib cache writes to `tmp/` (`HOME`, `MPLCONFIGDIR`, `XDG_CACHE_HOME`) and suppressing ArviZ startup warning during import; validated with `conda run -n py312_bayesmm_sbi ruff format .`, `ruff check .`, and `pytest -q -m "not slow"`.

### 2026-03-04: Production hardening (8-commit series)
- **Commit 1** `fix(cli): replace broad exception handlers with specific types`
  - `src/bayesian_metamodeling/cli/main.py`: replaced two `except Exception` blocks with specific exception types (`ValueError`, `FileNotFoundError`, `json.JSONDecodeError`, `KeyError`, `OSError`, `subprocess.SubprocessError`)
  - Added tests: `tests/test_cli_ux_commands.py` (specific exception catch + unexpected propagation)
- **Commit 2** `fix(runner): add subprocess timeout from walltime_min`
  - `src/bayesian_metamodeling/runners/local_process.py`: added `__init__` with `timeout_sec`, `subprocess.TimeoutExpired` handling
  - `src/bayesian_metamodeling/cli/main.py`: plumbed `walltime_min * 60` into `LocalProcessRunner`
  - Added tests: `tests/test_local_process_runner.py` (timeout pass-through + TimeoutExpired handling)
- **Commit 3** `fix(storage): add file locking to registry operations`
  - New: `src/bayesian_metamodeling/storage/_filelock.py` — `locked_registry()` context manager using `fcntl.flock()`
  - Modified: `run_store.py`, `surrogate_store.py`, `meta_store.py`, `meta/sampling.py` — wrapped registry writes
  - Added tests: `tests/test_storage_unit.py` (concurrent write safety)
- **Commit 4** `fix(meta): unify coupling sigma default and document approximation`
  - `src/bayesian_metamodeling/meta/ir.py`: added `DEFAULT_COUPLING_SIGMA = 0.1`
  - `src/bayesian_metamodeling/meta/compiler.py`: named constants `_DETERMINISTIC_PENALTY`, `_DETERMINISTIC_TOL`, use shared default
  - `src/bayesian_metamodeling/meta/sampling.py`: use shared default, added `_NUMPYRO_NOISE_SCALE_FACTOR`, docstring for `_sample_core()`
  - Added tests: `tests/test_meta_ir_edge_cases.py` (sigma default consistency)
- **Commit 5** `fix: thread-safe backend imports, CLI input size limit`
  - `src/bayesian_metamodeling/surrogates/backends.py`: `_ENV_LOCK = threading.Lock()` around env var manipulation
  - `src/bayesian_metamodeling/cli/main.py`: `_MAX_INPUTS_JSON_BYTES = 10 MB` size check before JSON parse
  - Added tests: `tests/test_surrogate_backend_hardening.py` (lock exists + oversized input rejection)
- **Commit 6** `test: add tier-1 unit tests` (~80 tests across 9 files)
  - New test files: `test_spec_edge_cases.py`, `test_adapter_unit.py`, `test_runner_unit.py`, `test_storage_unit.py` (expanded), `test_dataset_edge_cases.py`, `test_surrogate_model_contract.py`, `test_meta_ir_edge_cases.py` (expanded), `test_compiler_edge_cases.py`, `test_sampling_edge_cases.py`
  - Shared helpers added to `tests/conftest.py`
- **Commit 7** `test: add tier-2/3 integration and tutorial regression tests`
  - New test files: `test_cli_error_paths.py`, `test_run_failure_handling.py`, `test_tutorial_portability.py`, `test_example_specs.py`, `test_surrogate_quality_extended.py`, `test_metamodel_coupling_quality.py`
- **Commit 8** `docs: fix tutorials, update Status.md`
  - `tutorials/Tutorial_2.ipynb`: removed legacy `tmp/Old/` cache path reference
  - `tutorials/Tutorial_3.ipynb`: added markdown cells showing expected validator output inline
  - `tutorials/Tutorial_9.ipynb`: added pre-flight cell checking which prior tutorial artifacts exist
  - `Status.md`: recorded all 8 fixes
- Validation: `ruff format .`, `ruff check .`, `pytest -q -m "not slow"` all pass

## 2026-05-14: joint multi-output surrogates, configurer, cross-platform tutorials
Ported from `main` (PR #2 had merged the same features there against the old
`metamodeler` package name) and adapted for develop's `bayesian_metamodeling`
package + `bayesmm` CLI. Backup ref `claude/develop-pre-port` retained.
- **Commit `feat(cli): add bayesmm doctor / bayesmm setup configurer`** — new
  `bayesian_metamodeling.config` package (`bootstrap`, `diagnose`, `setup`,
  `platform`, `_import_helpers.probe_package`) + `bayesian_metamodeling.tutorial`
  helper. CLI gains `bayesmm doctor [--json]` and
  `bayesmm setup [--non-interactive --backend ...]`. The hardened `_require_*`
  helpers stay in `surrogates/backends.py`.
- **Commit `feat(surrogates): joint multi-output learning`** — `SurrogateSpec`
  accepts any number of outputs; `backend_config.output_correlation` selects
  `"diagonal"` (independent per-output, default) or `"full"` (joint covariance:
  PyMC `LKJCholeskyCov`, SBI D-dim density estimator). Dataset loader reads all
  output columns (`y` is now `(N, D)`). Multi-output posterior models return
  `(N, n)` for D=1 and `(N, n, D)` for D>=2; `LinearGaussianModel` keeps its
  original 2-D contract. Payload schema bumped to `..._v2` with v1 read-back.
  `SbiNPEPosteriorModel` keeps a back-compatible constructor for the old
  `posterior=` / `output_name=` / scalar-`y_mean` call sites.
- **Commit `chore(tutorials): cross-platform notebooks`** — converted the
  remaining `%%bash` cells in Tutorials 3/4/5/6/7/8/9 to in-notebook
  `run_mm_cli` / `run_tool` helpers (no `%%bash`, no `PYTHONPATH=src`); each
  notebook bootstraps and chdir's to the repo root. Added `environment.yml`.
  README + tutorials/README rewritten with cross-platform install + configurer
  notes; README doc-map paths de-absolutized. Tutorial_9's quality gate scoped
  to `src tests` (was `.`, which dragged in the unrelated tcr_signaling submodule).
- Worked around a ruff 0.15.12 formatter bug that unwraps bare `except (A, B):`
  tuples into invalid `except A, B:` (`config/platform.py`).
- Validation: all 10 tutorials execute end-to-end via `jupyter execute` on the
  `py312_bayesmm_sbi` env; `ruff check src tests` clean; fast suite
  (`pytest -q -m "not slow" tests`) green.

## Independent review + cross-platform verification (2026-05-14)
- Code-reviewed both packages and ran every test.
- `bayesian_metamodeling` (macOS): fast suite green on `py312_bayesmm_sbi` (256 passed)
  and `py314_bayesmm` (244 passed; optional-backend tests skip-safe); slow suite green
  on `py312_bayesmm_sbi`; `ruff check` / `ruff format --check` clean.
- `tcr_signaling` submodule (macOS, run from inside the submodule): clean CMake build of
  `ks_gpu` + `libks_potentials.dylib`; full `pytest` suite — 169 tests — all passed. The
  32 GPU tests ran on Metal with no silent CPU fallback (stderr clean). Treated
  read-only; its Windows gaps (Makefile-only build, `ks_gpu` not `.exe`, Metal-only GPU)
  are documented, not fixed.
- All 10 tutorial notebooks execute end-to-end via `jupyter execute` on `py312_bayesmm_sbi`.
- Cross-platform fixes applied (`bayesian_metamodeling` + tutorials only):
  - `tutorials/Tutorial_0.ipynb`: hardcoded `:` PYTHONPATH separator → `os.pathsep` (broke
    PYTHONPATH on Windows). The preflight cell now also runs `bayesmm doctor` for fast
    onboarding; stale `py*_metamodeling_*` env references replaced with pointers to
    `bayesmm doctor` / `bayesmm setup`.
  - `pytest.ini`: dropped `projects/tcr_signaling` from `testpaths` — collecting the
    submodule under the parent's `filterwarnings = error` turned its unregistered
    `deterministic` marker into a collection error. The submodule is tested from inside
    itself (its own pytest.ini).
  - `config/diagnose.py`: Python-floor advisory aligned to the real floor (`>=3.12` per
    pyproject.toml; was warning at `< 3.11`).
  - `tutorial.py::run_tool`: a bare `python` now also routes through `sys.executable`
    (conda-on-Windows PATH robustness).
- Added `.github/workflows/ci.yml`: matrix CI on ubuntu/windows/macos × py3.12 — install
  with `[pymc,sbi]`, ruff lint + format, fast test suite, and a `bayesmm doctor` / `setup`
  smoke. This is the authoritative Windows + Linux verification (cannot be run from a
  macOS dev box). The `tcr_signaling` submodule is intentionally out of CI scope (native
  CMake/Metal build).
- Note: Linux verification was subsequently completed locally via Docker — see the
  2026-05-15 entry below for the run, the two issues it surfaced (`sbi` 0.26 +
  PyMC/PyTensor BLAS), and the resulting fixes. The CI `ubuntu-latest` leg now
  has the same fixes baked in.

## Cross-platform compat fixes from Linux Docker re-verify (2026-05-15)
- Re-verified the `bayesian_metamodeling` fast suite in a fresh `python:3.12`
  Docker container with the repo mounted (`docker run --rm -v <repo>:/work -w /work
  -e PYTENSOR_FLAGS=cxx= python:3.12 …`). The first run surfaced two real issues
  that were silently hidden by the local conda envs:
  - **sbi 0.26 incompatibility**: pip pulled `sbi 0.26.1` in the container.
    0.26 renamed the training-logger kwarg `summary_writer` → `tracker` (a
    `FutureWarning`, fatal under the suite's `filterwarnings = error`) **and**
    changed the tracker object interface so it now calls `.log_metric()` —
    `SummaryWriter` doesn't have that method, so even after passing the new
    kwarg the training loop crashes with `AttributeError`. Scoped fix: pinned
    `sbi = ["sbi>=0.22,<0.26", "torch>=2,<3"]` in `pyproject.toml`. Verified
    against sbi 0.25.x. Supporting sbi 0.26+ requires a tracker-protocol shim
    and is tracked as a follow-up (see Open issues).
  - **PyMC/PyTensor BLAS**: the bare `python:3.12` image lacks the system BLAS
    PyTensor needs to compile its C ops, so PyMC tests crashed in compile.
    Fix: added `PYTENSOR_FLAGS: cxx=` to the CI workflow's job-level `env:`
    (PyTensor's C-less fallback — already documented for constrained envs in
    `README`). The same env var is what the local `py312_bayesmm_pymc`
    verification has used since 2026-02-11.
- Hardened `_build_sbi_inference` (in `surrogates/backends.py`) to be
  sbi-version-robust anyway: it now tries the new (`tracker`), legacy
  (`summary_writer`), then no-logger constructor signatures and uses whichever
  the installed sbi accepts. This keeps the code forward-compatible for the
  sbi-0.26 follow-up without requiring it now.
- Added `pytest` to the CI workflow's install step — `pytest` is a dev tool, not
  a runtime dependency, so it has to be installed explicitly alongside
  `[pymc,sbi]` and `ruff`. The original CI workflow was missing it.
- Test updates in `tests/test_sbi_backend_extended.py`:
  - Rewrote `test_build_sbi_inference_falls_back_to_snpe` to use the realistic
    "old sbi" signal — `from sbi.inference import NPE` raises `ImportError`
    (NPE attribute absent), which is what actually triggers the SNPE path now.
  - Added `test_build_sbi_inference_uses_tracker_kwarg`: a fake NPE that only
    accepts the sbi-0.26-style `tracker` kwarg must still be constructed
    correctly. Locks the new kwarg-trying loop.
- Re-verification (after the fixes):
  - **Linux Docker** (`python:3.12` + `PYTENSOR_FLAGS=cxx=`, sbi 0.25.0): full
    `pytest -m "not slow" tests` green (only the 3 expected backend-deselected
    skips), `ruff check` clean, `bayesmm doctor` OK, `bayesmm setup
    --non-interactive --backend pymc,sbi` OK.
  - **Local `py312_bayesmm_sbi`** (sbi 0.25.0, torch 2.5.1, pymc 5.28.1, arviz
    0.23.4): full fast suite green (3 expected skips).
  - **Local `py314_bayesmm`** (python 3.14.3, no optional backends): full fast
    suite green (backend tests cleanly skip-deselected).
  - `ruff check src tests` + `ruff format --check src tests` clean on the main
    repo.

## Windows CI fix: cross-platform file lock (2026-05-15)
- The first CI matrix run on `claude/develop` had Linux + macOS green but
  Windows red at the test step. Root cause: `src/bayesian_metamodeling/storage/_filelock.py`
  did `import fcntl` unconditionally; `fcntl` is POSIX-only, so any module
  that touched the registry (run_store, surrogate_store, meta_store,
  meta/sampling) failed at import on Windows, killing pytest collection.
- Fix: cross-platform `_filelock.py` — `fcntl.flock(LOCK_EX/LOCK_UN)` on
  POSIX, `msvcrt.locking(LK_LOCK/LK_UNLCK, 1)` on Windows. The lock file is
  pre-seeded with one byte (Windows requires the locked region to actually
  exist; POSIX doesn't care). Each call opens its own fd, so threads inside
  one process are serialized too — matching the pre-existing
  `tests/test_storage_unit.py::test_locked_registry_concurrent_writes`
  contract.
- Audited the rest of the codebase for other Windows traps (POSIX-only
  imports, `os.fork`/`os.uname`, `shell=True` subprocess, `bash`
  invocations, residual `%%bash` notebook cells). `_filelock.py` was the
  only blocker.
- Re-verified `tests/test_storage_unit.py` (8/8 pass) on macOS POSIX.

## Windows CI fix #2: cross-platform storage.root absolute-path detection (2026-05-15)
- After the `_filelock` fix landed (66c7a6e) the windows-latest leg got past
  pytest collection but two tests failed: the `storage.root` validator's
  "rejects absolute path" check used `pathlib.Path(value).is_absolute()`,
  which on Windows treats `/tmp/absolute` as drive-relative (not absolute),
  so the test `payload["storage"]["root"] = "/tmp/absolute"` slipped through:
  - `tests/test_security_hardening.py::TestStorageRootTraversal::test_rejects_absolute_storage_root`
  - `tests/test_spec_edge_cases.py::test_modelspec_storage_root_rejects_absolute_path`
- Fix: `StorageSpec.check_not_absolute` now rejects absoluteness under EITHER
  convention by checking both `PurePosixPath(value).is_absolute()` and
  `PureWindowsPath(value).is_absolute()`, plus an explicit
  `value.startswith(("/", "\\"))` guard for drive-less rooted Windows paths
  (which pathlib doesn't classify as absolute). The `..` traversal check now
  splits on either separator. Truth-tabled against 9 inputs (POSIX-abs,
  Windows-abs, UNC, drive-rooted, traversal with either separator,
  plain relative).
- This is the platform-symmetric form of the same security intent: any
  attempt to escape the project root via an absolute path is rejected on
  every platform, regardless of which convention the path string uses.

## sbi 0.26+ tracker shim landed (2026-05-15)
- Added `_TrackerCompatWriter` in `src/bayesian_metamodeling/surrogates/backends.py`
  that adapts a `tensorboard.SummaryWriter` to expose `log_metric(name, value, step=...)`
  in terms of the legacy `add_scalar(name, value, step)` so a single writer
  satisfies both sbi <0.26 (uses `add_scalar`) and sbi >=0.26 (uses
  `log_metric`). `_make_sbi_summary_writer` now wraps the real writer; the
  `_NoOpSummaryWriter` fallback is already 0.26-safe via its blanket
  `__getattr__`. The kwarg-trying loop in `_build_sbi_inference` (added
  earlier) handles the corresponding `summary_writer` -> `tracker` rename.
- Relaxed `pyproject.toml` from `sbi<0.26` to `sbi<1` and rewrote the
  comment block above it.
- Three regression tests added in `tests/test_sbi_backend_extended.py`:
  `test_tracker_compat_writer_translates_log_metric_to_add_scalar`,
  `test_tracker_compat_writer_forwards_other_attrs`,
  `test_make_sbi_summary_writer_wraps_real_writer_with_tracker_compat`.
- Local re-verify on `py312_bayesmm_sbi`: full extended suite green
  (24 passed). CI matrix is the authoritative cross-version verification.

## Open issues
(Real, actionable items only. Items here become commits or are intentionally deferred.)
- **Tutorial 2 offline path**: `tutorials/Tutorial_2.ipynb` Step 2 depends on
  the BioModels HTTP download. The cache-search loop is partial and there is
  no `MM_BIOMODELS_OFFLINE`-style escape hatch. Plan: env-var honor in the
  adapter + optional `local_sbml_path` field on `ArtifactSpec` so a tutorial
  can ship a sample SBML; tutorial cell prints an actionable banner in
  offline mode instead of failing.
- **MPI integration test verification**: `tests/test_mpi_sweep_integration.py`
  exists, skip-safes correctly via `pytest.importorskip("mpi4py")` and
  `world_size < 2`, but no `mpirun -n 2` execution is recorded in the
  provenance log. Plan: run once, capture the run id + sweep CSV digest,
  add a 3-line "Optional: MPI execution" subsection to the README.
- **`tcr_signaling` Windows / cross-platform gaps**: the submodule needs CMake
  + a C++ toolchain; GPU kernel is Metal-only (macOS); build script is a
  Makefile. The submodule is read-only here, but the parent `README.md`
  doesn't mention any of this — surfacing it is a small parent-side doc fix.

## Designed behavior (skip-safe contract)
(Documenting intentional behavior so future readers don't reopen these as bugs.)
- PyMC backend tests skip via the `optional_backend` marker (in
  `tests/conftest.py` + `tests/backend_support.py`) when `pymc` is not
  importable.
- SBI backend tests skip via the same marker when `sbi`/`torch` are not
  importable.
- Slow BioModels test (`tests/test_biomodels_slow.py`) skips via
  `pytest.importorskip("roadrunner")` when `libroadrunner` is unavailable.
- Optional MPI integration test (`tests/test_mpi_sweep_integration.py`)
  skips when `mpi4py` is not importable or world size < 2.

## Local environment notes
(Per-developer machine state, not bugs.)
- Optional backends are intentionally not installed in the lean
  `py314_bayesmm` env; install them in `py312_bayesmm_pymc` /
  `py312_bayesmm_sbi` per `bayesmm setup` guidance, or attempt a single
  unified `py312_bayesmm` env (a tracked mac-specific experiment).
