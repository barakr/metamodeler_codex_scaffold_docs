# Status: Metamodeling Automation Framework

## Tutorial-stability hardening + post-mortem on missed T2 silent failure (2026-05-15, commits 28835b8..)

A previous verification commit (`61454b5`) reported "30/30 PASS" — 10 tutorials × 3 conda envs (`py312_bayesmm_sbi`, `py312_bayesmm_pymc`, `py312_bayesmm`). The user then opened Tutorial 2 manually in `py312_bayesmm_sbi` and saw `Run complete: 0 successful runs / 11/11 points failed`. The BioModels SBML sweep failed silently for every DOE point even though `libroadrunner 2.9.2` was installed in the kernel. **My verification reported PASS for a tutorial that did no useful work.**

Diagnosis surfaced THREE independent bugs:

1. **`runners/local_process.py:32` had a misguided `shutil.which("python") is None` guard.** The intent was to substitute `sys.executable` for bare `"python"` only when no `python` was on PATH. With base conda's `python` on PATH almost everywhere, the substitution NEVER fired — so worker subprocesses ran in PATH-`python` (typically base conda) instead of the kernel/CLI's env. When the kernel had libroadrunner but base didn't, every DOE point failed silently with `ModuleNotFoundError: No module named 'roadrunner'` recorded only in `sweep_logs.jsonl`. **Fix:** drop the guard; ALWAYS substitute `sys.executable` for bare "python" when no `conda_env` is set.

2. **`adapters/biomodels_sbml.py:101` hardcoded bare `"python"`** at command construction. Even with the runner's substitution as a backstop, the adapter's intent should be explicit at the source. Replaced with `sys.executable`.

3. **The BioModels download URL was broken.** The previous URL returned HTTP 200 with `text/html` (the BioModels web UI) instead of SBML XML. The adapter blindly cached the HTML as `<biomodels_id>.xml`; subsequent libroadrunner loads failed with "XML content is not well-formed". Fixed in three spec files; new URL verified to return `application/xml`. The adapter now also content-type-checks responses and raises a loud `RuntimeError` (with the bad content-type + URL + actionable instruction) instead of caching garbage.

### Post-mortem (constructive)

Three things went wrong, ordered by lesson value:

- **False success metric.** The verification used `jupyter execute` exit code as the criterion. T2's run cell calls `run_mm_cli("run", spec, check=False)` — non-zero CLI exit doesn't propagate to Python; the notebook completes "cleanly". The cell printed `Run complete with failures: 11/11 points failed` literally, but the harness never read cell outputs. The wrong question is "did the notebook crash?"; the right question is "did the notebook achieve what it claims to teach?". A test that asserts nothing meaningful is no test at all.
- **Verification was ad-hoc, not tracked.** A bash script in `/tmp/verify_tutorials.sh` doesn't get reviewed, doesn't accumulate per-tutorial knowledge of what success looks like, and won't be re-run by anyone else. A test in `tests/` would have forced rigorous success criteria upfront.
- **Pattern audit missed the second instance.** The same subprocess-env-leakage was already fixed once in `tutorial.py::run_tool` (~commit eb894ab). When fixing pattern X, grep the whole codebase for X — don't trust "I fixed the one that bit me".

### Hardening response (this commit series)

- **`tests/test_runner_subprocess_env.py`** + **`tests/test_adapters_no_bare_python.py`** (new): regression tests pinning the new always-substitute contract at both the runner and adapter layers. Belt + suspenders.
- **`tests/test_local_process_runner.py`** + **`tests/test_runner_unit.py`**: updated — the previous versions PINNED THE OLD BROKEN BEHAVIOR (`expected = "python" if shutil.which("python") else sys.executable`). Now anchored on the correct contract.
- **Per-tutorial self-check cells** appended to all 10 `tutorials/Tutorial_*.ipynb`: each notebook ends with a code cell that asserts the canonical scientific artifact (sweep_rows.csv has success rows, surrogate has posterior_draws calibrated to within tolerance, samples_dataset has the right variables and the coupling correlation, capstone composes end-to-end). Failures raise `AssertionError` → propagate through `jupyter execute` exit code → both interactive students AND CI/harness see them loudly. Two-tier for backend-gated tutorials (T2 / T6): if the optional dep is missing and preflight skipped, the assertion is "preflight banner was printed".
- **T2 preflight extended** with `LIBROADRUNNER_WORKER_OK`: in addition to checking that the kernel can `import roadrunner`, spawn a `[sys.executable, "-c", "import roadrunner"]` subprocess and verify it works too. Catches "half-installed env" cases where the bug recurs in some new way. New banner branch explains what's wrong + how to fix.

### Open follow-ups
- **Verification harness rewrite (`scripts/verify_tutorials.py`)**: tracked in plan file; defers to per-tutorial self-check cells (which now do the heavy lifting). Worth landing as a tracked test (`tests/test_tutorial_integration.py @pytest.mark.slow`) so CI's slow suite catches notebook regressions automatically.
- **Audit `subprocess.run()` calls across `src/`** for any other `python` vs `sys.executable` instances. Two were found and fixed (runner + biomodels adapter); a third (`tutorial.py::run_tool`) was already correct.



## High level state
- Stage: Prompt 17 implementation complete
- Current focus: validating centralized sweep output behavior across tutorial and optional MPI environments

## Decision Log

### 2026-08-07: Framework bug — a shared store broke every surrogate fit

`_load_from_centralized_sweeps` globs every `sweep_rows.csv` under the store and
indexed the surrogate's input columns on each row, so a store holding more than
one model's sweeps raised `KeyError: '<input>'` on the first foreign row. Fitting
ANY surrogate therefore broke as soon as a second model had been swept.

That is not an exotic layout — it is what "centralized sweep store" means, and it
is exactly how `projects/tcr_signaling` is arranged: four partial models sharing
one `store/`. It is why the surrogates there had never been fitted, and why
`metamodel.tcr_signaling.json` referenced four artifacts that did not exist.

Fix: skip sweeps whose header does not provide this surrogate's inputs, and if
nothing matches, say so — naming the inputs sought and how many foreign sweeps
were passed over, so the skip cannot become silent.

`tests/test_dataset_multi_model_store.py` pins all three edges: a foreign sweep
is ignored, a store with only foreign sweeps still raises with a useful message,
and the status filter was not loosened in the process. Verified bidirectional —
the first test raises `KeyError: 'a'` without the fix.

With this and the run-directory fix, `projects/tcr_signaling` notebooks 01-04
execute end to end for the first time (~3 min), and the metamodel samples:
14 variables, 16 factors, 2000 draws.

### 2026-08-07: Framework bug — a relative `storage.root` silently lost every output

`_run_single_point` built its run directory as `Path(spec.storage.root)/...`,
which is relative. The adapter hands that to the model as `--run-dir`, but the
model subprocess runs with `cwd=REPO_ROOT` — not the cwd of whoever invoked
`bayesmm`. The two therefore resolved to different directories: the model wrote
its outputs under REPO_ROOT while `parse_outputs` looked under the invoking cwd.
Every point failed with "Output parsing failed: No such file or directory". The
outputs existed; nobody looked where they were.

It hid because every test and example invoked the CLI **from the repo root**,
where the two paths coincide. It surfaced only when the `projects/tcr_signaling`
notebooks ran it from the submodule root — 21/21 and 64/64 points failing, with
the summary line reporting nothing more useful than a failure count.

Fix: resolve the run directory to an absolute path. Verified both ways —
21/21 successful from the submodule root, 21/21 from the parent root.

`tests/test_run_dir_cwd_independence.py` pins the property rather than the
implementation: a sweep must succeed when invoked from an arbitrary cwd.
Confirmed bidirectional — it passes with the fix and fails with "9/9 points
failed" without it. That the whole existing suite passed while this was broken
is the point: the tests all ran from the one directory where it worked.

### 2026-08-07: Pin `sbi<0.27`; reconcile conda envs; repair submodule + hook setup
- **CI had been red since 2026-05-15 without anyone noticing.** The last green
  run was `a34b3e0`; no runs happened between then and 2026-08-06, so the break
  was pure PyPI drift, not a code change. `src/` and `tests/` were untouched.
- **`sbi` pinned to `>=0.22,<0.27`.** On sbi 0.27.0 the NPE trainer no longer
  converges within its default 100 epochs on the test problems and warns
  "Maximum number of epochs ... reached"; `filterwarnings = error` escalates
  that to hard failures in 5 tests. `pyproject.toml` already documented the
  supported range as 0.22..0.26, so 0.27 was never validated. Reproduced in a
  clean venv matching CI's install, and verified green after the pin (sbi
  resolves to 0.26.1). Lift once 0.27+ is checked against the surrogate suite —
  `backends.py::max_num_epochs` (default 120) is the likely knob.
- **Conda env files reconciled with the documented three envs.** README and
  `tutorials/README.md` told users to create `bayesian-metamodeling`, while
  CLAUDE.md, the submodule docs and both githooks reference `py314_bayesmm` /
  `py312_bayesmm_pymc` / `py312_bayesmm_sbi`. The hooks fall back to
  `~/miniconda3/envs/py314_bayesmm/bin/{ruff,pytest}` **by name**, so an env
  built from the old file could not satisfy them. `environment.yml` now builds
  `py314_bayesmm` and carries `pytest`/`ruff`/`cmake` (previously absent — so
  `make fast` and `make lint` could not run in it); backends split into
  `environment-pymc.yml` and `environment-sbi.yml`.
- **`python_abi=*_cp314` pinned** in `environment.yml`: conda-forge resolves a
  bare `python=3.14` to the free-threaded build, under which `import _brotli`
  raises a GIL `RuntimeWarning` that `filterwarnings = error` turns into a
  collection error — the suite cannot even start.
- **Ruff scoped to the framework.** `ruff check .` from the root reported 46
  errors, all inside `projects/tcr_signaling`, which root config does not
  govern. Added `projects/` and `*.md` to `extend-exclude` (this ruff formats
  fenced code blocks, so the hook's in-place `ruff format .` was silently
  rewriting `CodeDesign.md`). CI was unaffected — it already scoped to
  `src tests`.
- **`githooks/pre-commit` Status.md gate was dead.** It called `rg`, which is
  not installed; inside an `if` condition exit 127 reads as false, so the hook
  reported success while enforcing nothing. Switched to POSIX `grep`.
- **Submodule now tracks `main` over HTTPS.** `tcr_signaling` `main` was 19
  commits stale; fast-forwarded to the `feature/ks-metamodel-sweep` tip and
  deleted the four fully-merged branches. The SSH remote authenticates as
  `ravehlab`, which has no push access to `barakr/tcr_signaling`. Added
  `update = rebase` to `.gitmodules` — it had been in `.git/config`, which is
  never cloned, so every fresh clone still landed in detached HEAD.
- **Three independent CI signals, deliberately not merged.** `CI` (here) =
  framework broken; `KS model CI` (tcr_signaling repo) = KS model broken;
  `Interface CI` (here) = the two no longer fit. Keeping them separate avoids
  a submodule toolchain failure colouring the framework's status.
- **Interface contract tests added** (`tests/test_submodule_interface.py`).
  Nothing tested the framework against the case study before: the framework
  suite never checks out the submodule (`submodules: false` in CI) and the
  submodule suite imports no framework code, so a change to `spec/*.py` could
  invalidate all 9 case-study specs unnoticed. Validates each spec against the
  schema its filename prefix selects, plus schema_version presence and
  metamodel→surrogate name references. Pure pydantic — no CMake, no Metal.
- **`Interface CI` runs on every push, not `paths: projects/**`.** The contract
  breaks from either side and the framework side is likelier; a path filter on
  `projects/` would never fire for a `src/spec/` edit. Path filters fail open —
  when wrong they give silence, not an error.
- **`REQUIRE_SUBMODULE_INTERFACE=1`** makes "submodule absent" a failure rather
  than a skip in that job, so it cannot pass green having run nothing. Same
  concern as the KS suite's skip guard.
- Note: `bayesmm validate` only ever applies `ModelSpec`. Pointing it at a
  surrogate or metamodel spec reports a misleading "Extra inputs are not
  permitted" that looks like spec rot but is not — the interface tests
  dispatch on the filename prefix instead.

### Tutorial review (2026-08-07)

- **T5 and T9 crashed in `py314_bayesmm`, the documented main env.** Both call
  `bayesmm surrogate fit` with the `pymc_gp` backend and had no preflight, so a
  missing PyMC produced a mid-notebook `RuntimeError` rather than a skip. T6
  already solved this for SBI; its idiom was applied verbatim. All ten now pass
  in the main env, degrading with an actionable banner.
- **The tutorial integration test had never run in CI.** It is marked `slow`,
  and CI runs `-m "not slow"` — which is why the T5/T9 breakage survived. Added
  the `Deep CI` workflow (weekly + manual) to run the slow suite with every
  backend installed.
- **`REQUIRE_TUTORIAL_BACKENDS=1` added.** Every backend-gated tutorial degrades
  to a clean "SKIPPED" path and still reports its self-check OK — correct for a
  learner, worthless as verification, and the same false-success shape as the
  original post-mortem. The flag makes any preflight skip a failure. Verified:
  with pymc+sbi installed locally, exactly one tutorial fails under the flag —
  T2, because `libroadrunner` is in no conda env. Deep CI installs `[biomodels]`
  to close that, so T2's BioModels sweep gets exercised for the first time since
  it was fixed.
- **Verified for real, not just for exit code**: 10/10 in `py314_bayesmm` (37s,
  backend steps skipped), 10/10 in `py312_bayesmm_pymc` (235s) and
  `py312_bayesmm_sbi` (237s). The 6× runtime difference is the evidence that GP
  fitting actually ran rather than being skipped.
- **Pedagogical audit — first pass was wrong.** A keyword scan reported
  objectives 3/10 and recap 4/10; the notebooks use "Learning aims" and
  "Scientific checkpoint", so the real figures were 9/10 and 8/10. The material
  was already substantially pedagogical (T1 in particular has a
  predict-then-verify exercise and plants a question T5 answers). Corrected
  before acting on it — the flawed measurement would have justified a needless
  rewrite of all ten notebooks.
- **Real gaps closed** (~20 markdown cells, additive; no existing cell altered):
  troubleshooting 2→9 (T0 excepted, being orientation), predict-before-you-run
  5→9, inter-tutorial threading 6→10, recap 7→10, objectives 9→10.
- **`tutorials/README.md` rewritten.** It claimed troubleshooting in every
  notebook (there were two) and a visual checkpoint in every notebook (T3 had
  none). Now states the course arc, the per-tutorial question/capability table,
  and the env matrix.

#### Sanctioned-skip registry, and a coverage gap it exposed (2026-08-07)

- **Every skip in Deep CI is now classified** against a registry of sanctioned
  reasons and rendered in the job summary as `verdict | test | reason | why
  that's OK`. Unsanctioned skips emit an annotation and fail the job. The `full`
  job is strict: with everything installed the only defensible skips are the
  three external constraints below.
- **mpi4py installed, and the test actually launched.** `test_mpi_sweep_integration`
  had never run anywhere — mpi4py was in no conda env and no CI job. Installing
  it was necessary but not sufficient: the test needs >=2 ranks, so under a
  plain `pytest` it skips regardless. The full job now also runs it under
  `mpirun --oversubscribe -n 2`.
- **The strict check immediately caught two skips I had not sanctioned** — the
  MPI rank requirement and the BioModels 403 — which is the check working, not
  failing. Both are external constraints rather than missing dependencies, so
  both are now sanctioned with written justifications.
- **Gap found and NOT papered over: `notebooks/01-04` run in no CI job.** They
  drive `ks_gpu` by subprocess, so they need the submodule's compiled native
  model *and* the framework, and they run real sweeps (>10 min locally). An
  attempt to run them from Interface CI was reverted: building the KS model
  there would cross the submodule boundary that workflow exists to police, and
  would turn a seconds-long per-push signal into a minutes-long one. The
  submodule's own CI covers `notebooks/models/kinetic_segregation/KS_*`, a
  different set. Closing this needs a deliberate choice about which side pays
  (parent builds KS, or submodule installs the framework); until then the skip
  is sanctioned with that reason rather than pretended away.

#### Policy: no silent no-ops; dev envs must match what CI installs (2026-08-07)

- **Rule 12 added to CLAUDE.md** — "a gate that can skip must be able to fail for
  skipping" — with a *Guarding against silent no-ops* section listing the five
  instances found today and a table of the mechanisms that already exist, so the
  next suite reuses them rather than reinventing. The test to apply: *if every
  step silently did nothing, would this still be green?*
- **Conda env pins replaced with pyproject's ranges.** The exact pins were not
  cosmetic drift, they were the mechanism: `sbi==0.23.3` lists `pymc>=5.0.0` as a
  HARD dependency, so `py312_bayesmm_sbi` always contained PyMC and was never
  sbi-only. It structurally could not reproduce CI's sbi-only job — which is
  exactly why Tutorial 6's missing PyMC guard was invisible locally and only
  surfaced in CI. From 0.26 pymc is an optional extra. Rebuilt: sbi 0.26.1,
  torch 2.13.0, pymc absent — identical to what CI resolves, and T6 now
  reproduces the CI behaviour locally (skips Step 4, self-check green).
  Trade-off accepted: exact pins give reproducibility, ranges give fidelity to
  what users actually get; for a *dev* env fidelity wins, and exact versions
  behind a published result belong in that project's own Status.md.
- **Notebook tooling added to both backend env files.** Without nbclient,
  `pytest -m slow tests/test_tutorial_integration.py` importorskips and reports
  green having run nothing — rule 12 applied to the envs themselves.
- **CI trigger paths documented as a future consideration, not a rule.** Deep CI
  is the only workflow using `paths:` and it is now correct. Recorded that path
  filters fail open, that the filter must cover everything the job executes, and
  that the escape hatch is simply to drop them (Actions minutes are free on
  public repos).

#### Deep CI's first matrix run found three real bugs (2026-08-07)

The matrix and the REQUIRE flag were justified on the argument that a single
all-backends job hides env-specific breakage. Its first run substantiated that
immediately — none of the three reproduced on macOS.

- **T6 needed PyMC as well as SBI.** Step 4 compares the SBI surrogate against
  T5's `pymc_gp` surrogate but guarded only on `SBI_AVAILABLE`, so the sbi-only
  job raised. Same unguarded-backend bug as T5/T9. Now detects PyMC separately
  and skips only the comparison.
- **`test_biomodels_slow` asserted a column that never existed.** It read
  `time_series__json`; `_flatten_nested` only emits a whole-payload blob when a
  member cannot be flattened, and here every member can, so the data lands in
  `time_series__{n_points,t0,t1,columns__N,rows__json}`. The assertion had never
  passed — the test needs libroadrunner (installed in no env until now) and is
  `slow`, so it was excluded from every CI run. Rewritten against the real
  schema and against values, including a check that not every species is zero,
  so a hollow simulation cannot pass.
- **biomodels.org returns 403 to GitHub runner IPs.** T2 failed 11/11 DOE points
  in CI while passing locally. Not a code bug: the service refuses cloud address
  ranges. The `403` was only visible after adding a step that surfaces
  `sweep_logs.jsonl` as annotations — Actions *logs* need an authenticated token
  to fetch, but *annotations* do not, so a red run was otherwise undiagnosable
  from its URL.
  - Fix: vendored `examples/biomodels/MODEL1907260003.xml` (40K). Tests pin
    `local_sbml_path` at it, so CI verifies parse/simulate/mapping/flattening.
    T2 keeps fetching by default — that is part of what it teaches — and probes
    the URL first, falling back to the vendored copy when offline or blocked.
    The fetch is covered by a *separate* test, `test_biomodels_adapter_fetch_slow`,
    which calls the adapter directly (not via a sweep, where a failed download
    surfaces as "N/N points failed" with the cause buried in sweep_logs.jsonl) and
    skips with an explicit HTTP-code reason where the service refuses. So the
    download IS tested on a developer machine and only unverifiable on hosted CI.
    First attempt got this wrong: pinning `local_sbml_path` in the one existing
    test made the fetch untested *everywhere*, not just in CI.

#### Decisions taken with the user (2026-08-07)

- **Deep CI runs nightly, not weekly** (03:00 UTC). Tutorials are user-facing; a
  break sitting for a week would be found by a learner before CI found it.
- **Deep CI runs a 4-way matrix mirroring the documented envs**, not one
  all-backends job. T5/T9 crashed *only* in the backend-less main env, which a
  single full-install job would never have caught. The three partial jobs prove
  tutorials DEGRADE correctly (skips allowed); the `full` job sets
  `REQUIRE_TUTORIAL_BACKENDS=1` and proves the science RUNS (no skips allowed).
- **Fourth env added: `environment-biomodels.yml` → `py312_bayesmm_biomodels`.**
  libRoadRunner/tellurium are heavy and PyPI-only and only T2 needs them, so
  they do not belong in `environment.yml`; but leaving them installed nowhere
  meant T2 could only ever be debugged through CI logs — which is the condition
  that let its silent failure survive. Own env, symmetric with pymc and sbi.
- **T0 troubleshooting and T3 plot added** (reversing the earlier call to leave
  them). T0's table covers the kernel-vs-env mismatch that causes most newcomer
  failures, and is arguably the highest-value one in the course despite T0
  running no models. T3's figure is a ModelSpec anatomy map showing which error
  each block raises and marking the two cross-block contracts — which is where
  the confusing errors come from, since the reported `loc` is often not the
  field just edited. Every notebook now has a plot and a troubleshooting table,
  so the README needs no exceptions.

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

## MPI verification + tcr_signaling parent-README note (2026-05-15)
- Executed `tests/test_mpi_sweep_integration.py` end-to-end under
  `mpirun -n 2` for the first time. Found and fixed a latent test bug:
  `pytest.importorskip("mpi4py")` returns the package without auto-importing
  the `MPI` submodule, so `mpi4py.MPI.COMM_WORLD` raised `AttributeError`.
  Switched to `MPI = pytest.importorskip("mpi4py.MPI")`. After the fix,
  both ranks pass — 4/4 DOE points executed, exactly one centralized
  `sweep_rows.csv` produced (rank 0 writer; rank 1 synchronizes via barrier).
- Parent `README.md` extended with two new subsections:
  - "Optional: verify the MPI single-writer contract end-to-end" — gives
    the exact `mpirun -n 2 python -m pytest -q -m mpi …` command and the
    `conda install … mpi4py mpich` self-contained install path.
  - "Optional case study: `projects/tcr_signaling`" — surfaces the
    submodule's CMake / toolchain / Metal-only / Makefile-only / read-only
    constraints so a Windows user who clones with `--recurse-submodules`
    knows what to expect (the submodule is intentionally outside the parent
    CI matrix).
- MPI provenance:
  - mpi4py 4.1.1 / MPICH (Hydra 5.0.0), env `py312_bayesmm_sbi`.
  - Test session token: `4642208cf3934d1e97077da606240761`.
  - Sweep id: `262588341e8942399f217ebfa4a28228`; 4/4 successful points.
  - SHA256 `sweep_rows.csv`: `d491b0bde8e04187dc3f85c0ee8f5c952dcd31d765d05ffd078036b8f792a5ff`
  - SHA256 `sweep_manifest.json`: `90aed85cb7059bd86859bf7a7ec370d57237b6fde6a08968095f9c3c902e43ee`
  - Logs: `tmp/mpi_verify_2026-05-15/pytest.log`

## Tutorial 2 offline path landed (2026-05-15)
- New env var `MM_BIOMODELS_OFFLINE`: when set truthy and the SBML cache is
  empty, the adapter (`adapters/biomodels_sbml.py`) raises a clear
  `RuntimeError` mentioning the missing cache path and a `curl` recipe
  instead of attempting an HTTP fetch. Used by tutorial / CI / sandboxed
  workflows where the network is unavailable.
- New optional field `model.artifact.local_sbml_path` on `ArtifactSpec`: a
  spec-relative path to a local SBML file. When set, the adapter copies the
  local file into the per-spec cache (resolved against `repo_root` so the
  spec stays portable) — no network either way. Letting a tutorial ship its
  own sample SBML in-tree is now a one-field change.
- `tutorials/Tutorial_2.ipynb` updated: the bootstrap cell detects
  `MM_BIOMODELS_OFFLINE` + cache presence and prints an actionable banner
  with the exact cache path + `curl` recipe; Step 2 (the `bayesmm run`
  cell) now short-circuits cleanly in offline mode instead of failing. The
  heatmap analysis cells were already skip-safe ("no sweeps yet").
- 5 regression tests in `tests/test_biomodels_adapter_offline.py`:
  offline-env blocks download, offline-env uses existing cache,
  local_sbml_path seeds the cache (no network), local_sbml_path with
  missing file errors clearly, and a sanity check that existing example
  specs (without `local_sbml_path`) still validate.
- Local verify:
  - `pytest -q tests/test_biomodels_adapter_offline.py`: 5/5 pass.
  - `pytest -q -m "not slow" tests`: full fast suite green.
  - `MM_BIOMODELS_OFFLINE=1 jupyter execute tutorials/Tutorial_2.ipynb`:
    notebook completes end-to-end with the offline banner + Step 2 skip,
    no crashes (`tmp/tutorial2_offline_verify/Tutorial_2.executed.ipynb`).
- Schema artifact regenerated: `src/bayesian_metamodeling/spec/modelspec.schema.json`.

## Pedagogical pass on Tutorial_0..9 (2026-05-15, 11 commits)

Mechanically the tutorials were already clean (cross-platform helpers,
offline-aware T2, no `%%bash`). A pedagogical review (lab-manager voice,
applied best practices) found that they didn't actually **teach** —
they were a clean *demonstration sequence* with three structural failures
(T0 had no biology + a fake complexity plot; T7 + T8 were skeletal
coupling demos that never explained coupling; T9 was a CI checklist
masquerading as a capstone) and six cross-cutting issues (boilerplate
"Why this tutorial matters" cell duplicated verbatim across 7 notebooks;
no shared glossary; generic biology motivation; no predict-before-you-run
prompts; no anticipated-misconceptions callouts; stale `$ mm` outputs in
T1 from before the package rename).

This commit series fixed all of that across 11 commits, one per notebook
plus this Status.md summary, each independently revertible:

- **`762c1c5` — T0**: Rewrote opening with TCR-signaling running example;
  added shared glossary cell (referenced from later tutorials, single
  source of truth); replaced fake `complexity = [1,2,2,3,...]` plot with
  a real markdown ASCII pipeline diagram
  (`Spec → DOE plan → Sweep → CSV → Surrogate → Metamodel → Joint posterior`)
  showing which tutorials cover each segment; rewrote tutorial map as
  outcome table; expanded tips with time-sink warnings.

- **`e00672b` — T1**: Replaced boilerplate Why; added `validate` vs
  `plan` callout, "predict before you run" before the dual heatmap, and
  a "you can skim this" banner above the 50-line auto-selection cell;
  added a forward-link to T5 in the scientific checkpoint; re-executed
  to refresh stale `$ mm` outputs to `$ bayesmm` (the actual mechanical
  fix the agent flagged).

- **`352b14b` — T2**: Named MODEL1907260003 as Lever, Maini, van der
  Merwe & Dushek 2014 (citation verified via the BioModels API, PubMed
  25145757); added a `k_on` biological callout (forward association
  rate constant for `L+R→LR`, units `1/(M·s)`, ±20% sweep around the
  published parameter); added "you can skim this" above the 70-line
  CSV+timeseries parser; added a "Common confusion" callout in the
  scientific checkpoint connecting T2 → T5/T6.

- **`5e10c27` — T3**: Replaced boilerplate Why; added Step 4 second
  error type — inverted `support: [max, min]` (a per-input contract
  violation the validator catches with the exact field path
  `io_schema.inputs.0.support`); reframed the scientific checkpoint
  around per-input contract reasoning; deleted the fake importance-
  weights bar chart and replaced with a real markdown table listing
  spec sections + one sentence each on what they contract for. (Also
  attempted-and-abandoned: an input-name mismatch test — `design.grid`
  keys aren't cross-checked against `io_schema.inputs` names today,
  which is a real validator gap noted but out of scope for this
  notebook-only pass.)

- **`1d02642` — T4**: Replaced boilerplate Why with budget framing;
  added a CLI `bayesmm run` for the Sobol spec BEFORE the comparison
  scatter (the single biggest fix in T4 — previously the scatter showed
  "No Sobol runs yet" placeholder ~100% of the time because the spec
  was planned but never run); added "predict before you run" + a real
  curse-of-dimensionality table (4ⁿ vs Sobol counts at 2D-6D);
  augmented the scientific checkpoint with a Sobol-determinism note.

- **`3f58fda` — T5**: Replaced boilerplate Why with a surrogate
  definition + an explicit T1 callback ("at the bottom of T1 you held a
  question — would you trust a surrogate at `a=0.5, b=0.5`? This is
  where you answer it"); **moved the prior/posterior/posterior-predictive
  mini-lesson BEFORE the plot** (the single highest-value move in T5);
  augmented the errorbar plot with a 9-point training overlay, the
  analytical truth `y = a + b` as a dotted reference line, and an
  annotation showing the actual std value (~`1e-6`); added a "Common
  confusion: errorbars ≠ confidence intervals" callout; demoted the
  pytest call to an optional appendix.

- **`4651363` — T6**: Replaced boilerplate Why with PyMC-vs-SBI framing;
  simplified `cell-8` path detection (the bootstrap helper had already
  established `repo_root`); **added a Step 4: explicit T5-vs-T6
  comparison cell** that loads both surrogates, evaluates on the same 4
  query points, plots both errorbar series on shared axes with the
  analytical truth, and prints a numeric comparison (`PyMC mean vs SBI
  mean vs truth, PyMC std vs SBI std`) — the central comparison the
  curriculum was missing; added a "Common confusion: SBI doesn't have
  priors in the PyMC sense" callout; reframed the closing mini-lesson
  with three concrete decision rules for "what to do when PyMC and SBI
  disagree on a real model"; demoted pytest call.

- **`3d4288b` — T7**: 15-minute source dive (in this commit) into
  `meta/builder.py` + `compiler.py` + `sampling.py` confirmed that
  `equality_soft` (T7's spec) and `gaussian_link` (T8's spec) compile to
  the **same Gaussian-noise primitive** — the only special-cased coupling
  kind is `deterministic` (which gets a sharp `_DETERMINISTIC_PENALTY`).
  Aligned T7's spec to use `gaussian_link` consistently with T8.
  Sharpened secondary aim around induced joint posterior shape; replaced
  boilerplate Why with the concept introduction T7 needed; added a
  "What surrogates are we coupling?" callout naming the pre-built
  `surrogate_A` and `surrogate_B` honestly; added a "Coupling kinds"
  callout naming the `gaussian_link` vs `deterministic` distinction;
  added "Predict before you sample"; **augmented the scatter into a
  side-by-side prior-vs-posterior plot** with numeric output showing
  `corr(y, C)` jump from ~0 (no coupling) to ~0.99 (with coupling) and
  `std(y - C) ≈ σ`; rewrote scientific checkpoint as an active-learning
  σ exercise (vary 0.15 → 0.5 → 1.0, observe). Also fixed a latent
  bug in the registry-lookup logic (`sorted(payload.keys())[-1]` sorts
  UUID hex alphabetically — random; replaced with sort-by-`created_at`
  + filter-by-required-vars).

- **`bed47c9` — T8**: Sharpened learning aims around uncertainty
  propagation; replaced boilerplate Why with noise-budget framing for
  the chain `y → C → z → w` and the σ values along it; added "Predict
  before you sample" walking the chain step by step; **replaced the
  overlapping translucent histograms with a violin plot** of `y, z, w`
  side-by-side, std annotated above each, plus a numeric noise budget
  printout that makes the lesson quantitative
  (`std(z) = std(C) ≈ std(y); std(w) ≈ sqrt(std(z)^2 + 0.25^2)`,
  agreement within sampling noise IS the lesson — quadrature addition
  holds); rewrote scientific checkpoint as four active-learning prompts
  (verify quadrature, predict-then-test what doubling σ does, recognize
  the deterministic surprise, connect to real models). Same registry-
  lookup fix as T7.

- **`00b76b1` — T9**: **Capstone fully rewritten** from the CI checklist
  ("ruff format --check, ruff check, pytest, hardcoded `[1,1,1,0.5,0.5]`
  bar chart") to four student-driven steps (each with explicit
  `# === EDIT ME ===` markers): (1) Pick your DOE — student sets a 5x5
  grid, the cell builds a temporary spec at
  `tmp/tutorials/specs/capstone.grid.json`, validates / plans / runs;
  (2) Fit a PyMC surrogate on the student's sweep; (3) Evaluate at
  NEW points the student picks; (4) Visualize with training overlay +
  analytical truth + numeric summary. Replaced the deliverable template
  with a fill-in markdown the student literally edits. Added a closing
  forward-pointer to `projects/tcr_signaling/` ("the real version of
  T7-T8-T9 composed at full scale on four real biological models"
  with the four model names and the Frontiers in Immunology 2024
  paper). Demoted the original quality gate to an optional appendix
  (with `check=False` so it doesn't fail the notebook). Pragmatic
  deviation from the plan: the original Step 3 said "swap a
  `surrogate_refs` entry in T7's spec to point at the capstone surrogate"
  — but T7's example surrogates have a 1D-1D shape contract while the
  capstone surrogate is 2D-1D, so a direct swap would have required
  spec engineering bigger than a notebook lesson should have. Kept
  the spec composition lesson as a forward pointer rather than a
  half-working demonstration.

Verification approach (per-commit + final):
- Each commit re-executed its notebook with `jupyter execute --inplace`
  in `py312_bayesmm_sbi`. T2 used `MM_BIOMODELS_OFFLINE=1` so the
  offline path is exercised. T6 uses both PyMC and SBI artifacts;
  needs both backends in the env.
- Final suite-level smoke: all 10 notebooks re-executed end-to-end,
  including T0's bootstrap + `bayesmm doctor` preflight, T1's CLI
  loop + dual heatmap, T2's offline-mode banner + skip, T3's break/fix
  cycles, T4's grid+sobol comparison scatter, T5's surrogate fit + eval
  + augmented plot, T6's T5-vs-T6 comparison plot, T7's prior-vs-
  posterior scatter, T8's violin + noise budget, T9's full capstone
  pipeline.
- `ruff check src tests` + `ruff format --check src tests` clean
  throughout (notebooks aren't linted but if a stray Python file got
  touched it'd surface here).

Explicitly out of scope (locked decisions, recorded so they don't get
re-litigated):
- No standalone Bayesian primer notebook — T5's mini-lesson (now moved
  before the plot) is enough at the moment students need it.
- No `ipywidgets` — notebook-only delivery + cross-platform.
- No tutorial renumbering — stable links matter more than aesthetic
  numbering.
- No T7/T8 merge — the 2→3-model progression is the lesson; both
  notebooks now teach distinct concepts (induced joint shape vs
  uncertainty propagation along a chain).
- No CLI / spec changes beyond the T7 spec vocabulary alignment
  (`equality_soft` → `gaussian_link`, same primitive). The
  input-name-mismatch validator gap surfaced during T3's commit is a
  real follow-up; tracked here, not fixed.
- No re-running the cross-platform CI matrix per commit — tutorials
  aren't part of CI's fast suite.

## Open issues
(Real, actionable items only. Items here become commits or are intentionally deferred.)

- **Validator gap surfaced during the T3 pedagogical commit (5e10c27)**:
  `design.grid` keys are not cross-checked against `io_schema.inputs`
  names. A spec with `design.grid["alpha"]` but `io_schema.inputs[0].name
  == "a"` validates green today; the runner downstream then errors with a
  less-clear message. The T3 tutorial works around this by using inverted
  `support: [max, min]` as the second-error-type example instead. Adding
  the cross-check is one Pydantic `model_validator` on `ModelSpec`; out
  of scope for the notebook-only pedagogical pass but worth fixing
  before the next pedagogical iteration so T3 can teach the more common
  bug directly.

_All previously-tracked open issues from the cross-platform verification pass
are now resolved. Subsequent work (mac-specific unified `py312_bayesmm` env
attempt) is tracked separately under "Local environment notes" below._

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
  `py312_bayesmm_sbi` per `bayesmm setup` guidance, OR use a single
  unified `py312_bayesmm` env (mac, verified 2026-05-15, see below).

### Unified `py312_bayesmm` env on macOS arm64 (2026-05-15, mac-specific)
- Goal: one conda env with **both** `pymc` and `sbi` working in the same
  Python interpreter so the full fast suite passes without backend-tag
  swapping. Useful for local iteration; project CI keeps the existing
  matrix and per-backend pins.
- Recipe (the entire repo's `environment.yml` already has the right pins;
  just install it under a different name):
  ```bash
  conda env create -f environment.yml -n py312_bayesmm
  conda run -n py312_bayesmm pip install -e . --no-deps
  # Optional: MPI integration test support (cf. tests/test_mpi_sweep_integration.py)
  conda install -n py312_bayesmm -c conda-forge -y mpi4py mpich
  ```
- Verified versions in this env (macOS arm64): Python 3.12.13,
  `pymc 5.28.0`, `arviz 0.23.4`, `pytorch 2.10.0`, `sbi 0.26.1`,
  `pydantic 2.13.4`, `mpi4py 4.1.1` + MPICH (Hydra 5.0.0).
- Verification: `pytest -q -m "not slow" tests` -> full suite GREEN
  (3 expected backend-deselected skips). Optional backends both used.
- **Critical pin discovered during this experiment**: `arviz>=0.17,<1`.
  Letting conda pull the latest arviz (1.x) breaks PyMC 5.x with
  `cannot import name 'concat' from 'arviz'` because arviz 1.0 removed
  `InferenceData` and `concat` from the top-level module. The
  `environment.yml` already pins this correctly; an ad-hoc
  `conda create ... pymc arviz` does NOT, since the conda solver picks
  the newest of each individual package.
- This experiment also surfaced the sbi 0.26 prior-support `UserWarning`
  that broke green CI on `eb894ab`; fixed in `c0fec53` by extending the
  `_sbi_warnings_filtered()` context to all five sbi entry points
  (training prep, training, build_posterior, posterior.sample,
  posterior.log_prob).
