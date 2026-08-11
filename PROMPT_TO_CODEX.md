# Prompt pack for Codex CLI

Codex should treat this repo as a staged engineering project with strict reproducibility constraints.
Primary governing files:
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/AGENTS.md`
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/PRD.md`
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/TechSpec.md`
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/CodeDesign.md`
- `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/Status.md`

## One-time local setup (human step)
1) Install Codex CLI:
- `npm i -g @openai/codex`
2) Run Codex with project home:
- `CODEX_HOME=$(pwd)/.codex codex`
3) Activate project hooks:
- `git config core.hooksPath githooks`

## Vocabulary used throughout this pack

Framework nouns — spec, design, design point, sweep, canonical, provenance, adapter,
surrogate, coupling, metamodel — are defined once in [README.md](README.md#terms).
The acronyms below appear in the prompt text and are **not** expanded at each use,
because the prompt blocks are meant to be pasted verbatim:

- **DOE** — *design of experiments*: the set of input points a model is run at. The code
  and specs call this the `design`; "DOE cardinality" means the number of design points.
- **IR** — *intermediate representation*: the metamodel written as plain data (variables
  and factors) in a form naming no particular sampling library, so one spec can target
  more than one backend.
- **PPL** — *probabilistic programming language*: the library that turns the IR into a
  runnable model and samples it (`pymc` or `numpyro` here).
- **NPE** — *neural posterior estimation*: the `sbi` package's density-estimator method,
  behind the `sbi_npe` surrogate backend.

## Global instruction block (prepend to every major prompt)
Use this block before task-specific requests:

You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Current backend/testing guardrails:
- Optional backend checks should run when dependencies are available.
- If PyMC is installed but local toolchain compilation is unavailable, treat it as a runtime constraint (skip/fallback with explicit reason) rather than a product regression.
- Keep SBI training summary logs under `tmp/sbi-logs/` (do not write `sbi-logs/` at repo root).

## Prompt sequence
### Prompt 0: scaffold and guardrails
Task:
1) Create package skeleton from TechSpec.
2) Add `pyproject.toml` and CLI entrypoint `mm`.
3) Ensure `make fmt`, `make lint`, `make fast`, `make slow`.
4) Implement git hooks in `githooks/` per README.
5) Ensure `tmp/` is ignored and used for temporary artifacts only.

Acceptance:
- Formatting/lint/fast tests run successfully.
- Status.md updated.
- Commit: `chore: scaffold repo`.

### Prompt 1: typed spec validation
Task:
- Implement `ModelSpec` and required nested specs with Pydantic v2.
- Emit JSON Schema artifact for external validation.
- Implement `bayesmm validate <spec>` with actionable errors.

Acceptance:
- Fast tests for valid and invalid specs.
- Status.md updated.
- Commit: `feat: modelspec validation`.

### Prompt 2: DOE planner
Task:
- Implement DOE strategies `grid` and `sobol`.
- Implement `bayesmm plan <spec>` with deterministic preview output.

Acceptance:
- Fast tests for bounds, point counts, and determinism.
- Status.md updated.
- Commit: `feat: doe planner`.

### Prompt 3: execution core
Task:
- Implement adapter base interface + registry.
- Implement local process runner.
- Implement run store with provenance and stdout/stderr persistence.
- Implement `bayesmm run <spec>`, `bayesmm runs list`, `bayesmm runs show <run_id>`.
- Add toy example E2E integration test (fast).

Acceptance:
- `make fast` passes.
- Status.md updated.
- Commit: `feat: local execution pipeline`.

### Prompt 4: BioModels milestone
Task:
- Implement BioModels SBML adapter baseline.
- Support fetch/cache/simulate/parse flow for selected variables.
- Add one `slow` integration test.

Acceptance:
- `make fast` passes and `make slow` includes BioModels test.
- Status.md updated.
- Commit: `feat: biomodels adapter milestone`.

### Prompt 5: surrogate placeholders with interfaces only
Task:
- Add typed interfaces and CLI placeholders for surrogate fit/eval and metamodel build.
- No production inference yet; only contracts, stubs, and tests for CLI wiring.

Acceptance:
- Fast tests pass.
- Status.md updated.
- Commit: `feat: surrogate and meta interfaces`.

### Prompt 6: backend neutral IR for surrogates and metamodels
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: introduce backend neutral interfaces so we can later switch PyMC to NumPyro without changing user facing JSON.

Requirements:
1) Add SurrogateSpec fields:
   - kind: "conditional" | "joint"
   - inputs: list[str]
   - outputs: list[str]
   - backend: "pymc_gp" | "sbi_npe" | "numpyro_gp" (future, not implemented)
   - backend_config: dict
   - dataset_ref: run store query or path
   - seed
2) Implement a backend neutral SurrogateModel wrapper interface:
   - sample(inputs: dict, n: int, seed: int) -> numpy array or xarray
   - log_prob(inputs: dict, outputs: dict) -> numpy array
   - summary(inputs: dict) -> dict
3) Implement Metamodel IR:
   - variables: name, type, shape, support, units optional
   - factors: list of factor objects in backend neutral form
     - prior factors
     - coupling factors: equality soft constraint, Gaussian link, deterministic transform
     - surrogate likelihood factor: calls SurrogateModel.log_prob
4) Add compiler boundary:
   - compile_metamodel(ir, backend="pymc") implemented
   - compile_metamodel(ir, backend="numpyro") stub that raises NotImplementedError with clear message
5) Add CLI wiring stubs that operate on IR only:
   - `bayesmm meta build metamodel.json` must output an IR artifact to the run store
6) Tests, fast:
   - IR roundtrip serialization test
   - compile(IR, pymc) smoke test using a tiny synthetic IR with one Gaussian factor and one surrogate factor where surrogate is a mocked SurrogateModel returning a simple log_prob
   - Develop generic testing (doesn't depend on exact model) that show good fit between a learned surrogate model and the original model predictions, and several mock testsets with increasing challenge
7) Docs:
   - document the IR idea in README.md in a short section
   - update Status.md

Constraints:
- One commit only for this prompt.
Acceptance:
- `make fast` passes.
- Commit message: "refactor: backend neutral IR"


### Prompt 7: implement real surrogate learning backends behind the wrapper
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: implement actual surrogate learning for conditional surrogates p(B | X,Y,A) using backend selection, but keep the user interface generic.

Requirements:
1) Implement backend "pymc_gp" as SurrogateModel:
   - fit on tabular data where outputs are scalar or small vector
   - predict as a Normal predictive distribution
   - implement sample and log_prob via predictive mean and variance
2) Implement backend "sbi_npe" as SurrogateModel:
   - train a conditional density estimator for B given inputs
   - implement sample and log_prob using sbi posterior style API
   - persist model weights and config in the run store
3) Persist a backend neutral surrogate artifact:
   - artifact.json: backend, versions, spec digest, dataset digest, variable lists, seed
   - backend payload: saved model files for the chosen backend
4) CLI:
   - `bayesmm surrogate fit surrogate.json` trains and stores the artifact
   - `bayesmm surrogate eval surrogate.json --inputs <json> --n 1000` loads artifact and outputs samples plus summary stats
5) Dataset handling:
   - training data must be pulled from the run store canonical outputs
   - no implicit downsampling or thinning
   - if output B is high dimensional, add explicit summary configuration in SurrogateSpec and document it, default is no summaries
6) Tests, fast:
   - synthetic dataset test for pymc_gp: fit then sample shape checks, log_prob finite
   - synthetic dataset test for sbi_npe: minimal training steps, sample shape checks, log_prob finite
   - create refined tests for goodness of fits based on generic ones from Prompt 6 that are particulary tailored for testing things using pymc/sbi, with increasing difficulty
7) Docs and examples:
   - add examples/surrogates/ with one surrogate spec JSON for a toy model
   - update Status.md

Constraints:
- One commit only for this prompt.
Acceptance:
- `make fast` passes.
- Commit message: "feat: surrogate learning backends"

### Prompt 8: metamodel coupling and joint distribution sampling using PyMC compiler
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: implement coupling variables and joint distribution inference via metamodel IR compiled to PyMC.

Requirements:
1) Define MetamodelSpec v1:
   - ppl_backend: "pymc" | "numpyro"
   - surrogate_refs: list of fitted surrogate artifact refs
   - variables: optional explicit declarations for X,Y,A,B,C
   - couplings: list of coupling factor specs
   - priors: list of prior specs
2) Implement `bayesmm meta build metamodel.json`:
   - loads surrogate artifacts
   - builds metamodel IR containing coupling and surrogate factors
   - stores IR artifact in the run store
3) Implement `bayesmm meta sample metamodel.json --draws D --tune T --chains C --seed S`:
   - compiles IR with backend selected in MetamodelSpec
   - for backend "pymc": run sampling and store ArviZ InferenceData plus a canonical xarray Dataset of samples
   - for backend "numpyro": raise NotImplementedError, clear message that Prompt 9 will add it
4) Coupling factor types to support in v1:
   - gaussian_link: target ~ Normal(f(source vars), sigma)
   - equality_soft: Normal(target - source, sigma)
   - deterministic: target = f(source vars), no randomness
5) Tests, fast:
   - train two tiny surrogates on synthetic data
   - build metamodel with one coupling variable C linking two surrogates
   - sample with small draws to validate shapes and that results are stored
6) Examples:
   - examples/metamodels/metamodel.simple.json that couples two surrogates
7) Status.md updates

Constraints:
- One commit only for this prompt.
Acceptance:
- `make fast` passes.
- Commit message: "feat: metamodel coupling and sampling"

### Prompt 9: add NumPyro mode without changing the user interface
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: implement compile_metamodel(ir, backend="numpyro") and enable `ppl_backend: "numpyro"` in MetamodelSpec with the same JSON interface.

Requirements:
1) Implement NumPyro compiler:
   - translate Gaussian factors to numpyro.sample with dist.Normal
   - translate soft constraints and surrogate factors to numpyro.factor using log_prob values
2) Implement sampling:
   - run NUTS, store posterior samples in the same canonical storage format as PyMC
3) Add fast tests:
   - same synthetic metamodel integration test as Prompt 8 but using ppl_backend="numpyro"
4) Docs:
   - README section: how to switch ppl_backend
   - record known numerical differences between backends
5) Status.md updates

Constraints:
- One commit only for this prompt.
Acceptance:
- `make fast` passes.
- Commit message: "feat: numpyro backend"

### Prompt 10: harden user facing UX and reproducibility
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: improve the user experience so a user can go from model spec to surrogates to a joint metamodel with minimal friction.

Requirements:
1) Add `bayesmm tutorial` that prints a short guided flow and points to examples
2) Add `bayesmm surrogate list` and `bayesmm meta list` commands that show stored artifacts
3) Add schema validation for SurrogateSpec and MetamodelSpec with actionable errors
4) Ensure every artifact has:
   - spec digest
   - dataset digest
   - dependency versions
   - random seed
5) Add docs:
   - examples end to end in README: run model, fit surrogate, build metamodel, sample joint
6) Status.md updates

Constraints:
- One commit only for this prompt.
Acceptance:
- `make fast` passes.
- Commit message: "chore: ux and reproducibility hardening"

### Prompt 11: implement real PyMC-backed surrogate learning (`pymc_gp`)
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: replace the current placeholder implementation for backend `pymc_gp` with a real model implemented using the `pymc` package.
Note: use modern `pymc` (PyMC v5, successor to PyMC3). Do not reintroduce legacy `pymc3` APIs.

Requirements:
1) Dependencies and configuration:
   - Add optional project extras for `pymc` backend dependencies in `pyproject.toml`.
   - Add clear runtime error messages when `pymc` is unavailable (how to install in conda env).
   - Keep `mm` interface unchanged.
2) Backend implementation:
   - Implement a real `pymc_gp` fit path in `src/bayesian_metamodeling/surrogates/backends.py`.
   - Use a probabilistic model in PyMC (minimum: Bayesian linear Gaussian; preferred: GP if feasible with current interface).
   - Preserve backend-neutral `sample`, `log_prob`, and `summary` behavior.
3) Artifact persistence:
   - Persist backend payload in a stable format (JSON/NPZ/etc.) and include dependency/version metadata.
   - Ensure loading works across CLI sessions (`bayesmm surrogate eval` after `bayesmm surrogate fit`).
4) Tests:
   - Add focused tests for real PyMC fit/eval behavior.
   - Tests must skip gracefully when `pymc` is not installed, not fail.
   - Keep tests deterministic with explicit seeds.
   - Add a real-learning quality assertion (not only shape/finite checks): predictive mean must match a known synthetic mapping within a bounded error.
   - Add an explicit verification command path and run it at least once in an environment where `pymc` is installed:
     - `pytest -q tests/test_surrogate_backends.py -k pymc_gp_backend_fit_sample_and_logprob`
     - if the environment lacks a local C++ toolchain, run with `PYTENSOR_FLAGS='cxx='` so PyMC/PyTensor uses non-C fallback for verification.
     - Record the executed command, environment details, and pass/fail result in `Status.md`.
5) Docs:
   - Update `README.md` and `tutorials/Tutorial_0.ipynb` with PyMC backend usage and install notes.
   - Update `Status.md`.

Constraints:
- One commit only for this prompt.
Acceptance:
- `make fast` passes.
- Real PyMC verification test executed at least once in a PyMC-capable env and logged in `Status.md`.
- Commit message: "feat: real pymc surrogate backend"

### Prompt 12: implement real SBI-backed surrogate learning (`sbi_npe`)
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: replace the current placeholder implementation for backend `sbi_npe` with a real implementation using the `sbi` package.

Requirements:
1) Dependencies and configuration:
   - Add optional project extras for `sbi`/`torch` backend dependencies in `pyproject.toml`.
   - Add explicit runtime error messages when dependencies are missing.
   - Keep user-facing JSON schema unchanged.
2) Backend implementation:
   - Implement real `sbi_npe` fit path using `sbi` NPE training API.
   - Implement backend-neutral `sample`, `log_prob`, and `summary` using trained posterior/density estimator.
   - Keep deterministic seeding where supported and document any unavoidable stochasticity.
3) Artifact persistence:
   - Persist model payload (state dict/config/scalers) so `bayesmm surrogate eval` can load without retraining.
   - Record dependency versions in surrogate artifact metadata.
4) Tests:
   - Add focused tests for `sbi_npe` fit/eval behavior.
   - Tests must skip gracefully when `sbi`/`torch` are not installed.
   - Add at least one synthetic quality check (finite log_prob + reasonable predictive mean error).
   - Add an explicit verification command path and run it at least once in an environment where `sbi` and `torch` are installed:
     - `pytest -q tests/test_surrogate_backends.py -k sbi_npe_backend_fit_sample_and_logprob`
     - Record the executed command, environment details, and pass/fail result in `Status.md`.
5) Docs:
   - Update `README.md` and `tutorials/Tutorial_0.ipynb` with SBI backend usage and install notes.
   - Update `Status.md`.

Constraints:
- One commit only for this prompt.
Acceptance:
- `make fast` passes.
- Real SBI verification test executed at least once in an SBI-capable env and logged in `Status.md`.
- Commit message: "feat: real sbi surrogate backend"

### Prompt 13: backend integration hardening and CLI validation
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: harden backend selection and artifact compatibility across `pymc_gp` and `sbi_npe`.

Requirements:
1) Validation:
   - Validate backend-specific `backend_config` keys with actionable errors.
   - Fail fast when artifact backend and requested backend mismatch.
2) CLI robustness:
   - Improve `bayesmm surrogate fit` / `bayesmm surrogate eval` error messages for missing artifacts, missing dependencies, and malformed input payloads.
   - Keep command signatures unchanged.
3) Compatibility checks:
   - Ensure artifacts include enough metadata to prevent wrong-input ordering or output-name mismatch.
   - Add strict checks for `inputs`/`outputs` list compatibility at load/eval time.
4) Tests:
   - Add fast tests for mismatch/error paths and artifact compatibility guards.
   - Add one optional integration test path that runs both backends when dependencies are present.
5) Docs:
   - Update troubleshooting section in `README.md`.
   - Update `Status.md`.

Constraints:
- One commit only for this prompt.
Acceptance:
- `make fast` passes.
- Commit message: "chore: surrogate backend hardening"

### Prompt 14: build modular tutorial curriculum (9 parts, package-first + science-second)
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: replace the single tutorial flow with a modular learning path that is practical for package users and scientifically informative without becoming theory-heavy.

Requirements:
1) Create a `tutorials/` subfolder with:
   - `Tutorial_0` as the main hub and serial table-of-contents.
   - `Tutorial_1` through `Tutorial_9` with progressively harder tasks.
2) Every tutorial must include:
   - Primary learning aim focused on package usage (`mm` commands, specs, artifacts).
   - Secondary learning aim focused on scientific/computational intuition.
3) Ordering constraints:
   - Tutorial 1 must be quick, fun, and produce a real model result.
   - BioModels example must appear early (by Tutorial 2) and later tutorials may build on it.
   - Tutorials 5 and 6 must explicitly explain the underlying fitting ideas:
     - PyMC path: priors, posterior, posterior predictive.
     - SBI path: simulator-based inference, neural posterior estimation.
4) Decoupling constraints:
   - Tutorials should be mostly standalone.
   - Each tutorial must state whether it can run independently and, if needed, provide fallback bootstrap commands to recreate missing artifacts from prior tutorials.
5) Notebook support:
   - Provide at least a notebook entrypoint for the modular track (`Tutorial_0.ipynb`).
6) Documentation wiring:
   - Update tutorial entry docs (`README.md`, `tutorials/README.md`) to point to `tutorials/Tutorial_0`.
7) Add/update tutorial-specific example specs or artifact stubs if needed to keep tutorials runnable.
8) Update `Status.md` with tutorial architecture decisions and what remains open.

Constraints:
- One commit only for this prompt.
Acceptance:
- Modular 9-part tutorial track exists and is discoverable from README.
- Tutorial 0 provides clear serial roadmap and execution-mode guidance (standalone vs serial).
- Status.md updated.
- Commit message: "docs: modular tutorial track"

### Prompt 15: convert tutorial system to pure Jupyter onboarding track
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: convert the modular tutorial content to notebook-only delivery and improve onboarding quality for lab members with general programming + biological background.

Requirements:
1) Tutorial format:
   - Deliver tutorials as pure Jupyter notebooks:
     - `tutorials/Tutorial_0.ipynb`
     - `tutorials/Tutorial_1.ipynb` ... `tutorials/Tutorial_9.ipynb`
   - Remove/retire Markdown tutorial duplicates (`tutorials/Tutorial_*.md`).
2) Onboarding quality:
   - For each tutorial include:
     - estimated time,
     - prerequisites/dependencies,
     - clear success criteria,
     - runnable steps and checkpoints,
     - short troubleshooting/fallback guidance.
3) Learning design:
   - Keep dual aims in each notebook:
     - primary package-use objective,
     - secondary scientific/computational objective.
   - Keep BioModels early and retain explicit PyMC/SBI conceptual mini-lessons.
4) Documentation updates:
   - Update `README.md` and `tutorials/README.md` to notebook-only links.
   - Update `PRD.md`, `TechSpec.md`, `CodeDesign.md`, and `Status.md` to reflect notebook-first onboarding architecture.
5) Prompt/doc synchronization:
   - Record this as Prompt 15 completion in `Status.md`.

Constraints:
- One commit only for this prompt.
Acceptance:
- Tutorials are notebook-only in `tutorials/`.
- Onboarding structure is explicit and usable by new lab members.
- Project docs and prompt pack are synchronized with tutorial architecture.
- Commit message: "docs: notebook-only tutorial onboarding"

### Prompt 16: tutorial execution hardening + guided pedagogy enrichment
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: run the tutorial flow yourself, fix execution blockers, and improve tutorial learning quality.

Requirements:
1) Execute tutorial command paths and record pass/fail findings.
2) Fix blocking issues discovered during execution (example: surrogate dataset parsing mismatch).
3) Add regression tests for discovered blockers.
4) Improve tutorial notebooks:
   - richer verbal guidance and “why this matters” framing,
   - remove manual placeholders (auto-select IDs/artifacts where possible),
   - add helpful graphics/plots in each tutorial.
5) Ensure quality gate remains green:
   - handle notebook lint strategy explicitly (e.g., ruff config for `.ipynb` docs).
6) Update docs to reflect the hardening pass:
   - `Status.md`, `PRD.md`, `TechSpec.md`, `CodeDesign.md`, `README.md`, `tutorials/README.md`.

Constraints:
- One commit only for this prompt.
Acceptance:
- Tutorial 5/6 surrogate flow no longer blocked by toy-output envelope mismatch.
- Fast suite passes.
- Tutorial notebooks contain guided explanatory content and graphics.
- Status.md includes concrete execution findings and remaining environment-dependent limitations.
- Commit message: "docs: harden and enrich tutorial notebooks"

### Prompt 17: centralized DOE sweep output + synchronized serial/parallel/MPI writer
You are Codex working in this repository.
Read AGENTS.md and follow it strictly.
Do implementation in small, reviewable commits.
Never change sampling resolution, dataset size, DOE cardinality, or runtime shortcuts unless explicitly requested.
Always persist run provenance including seed, spec digest, artifact digest, stdout, and stderr.
After each meaningful change: update Status.md with what changed, why, and decision notes.
Before commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`.
If fast tests fail, do not commit.

Task: replace per-point numeric output scattering for DOE sweeps with one centralized tabular output artifact, and upgrade Tutorial 1 to consume it.

Requirements:
1) Centralized sweep sink:
   - Add a sweep artifact writer that emits:
     - `sweep_rows.csv` (one row per DOE point),
     - `sweep_manifest.json`,
     - `sweep_logs.jsonl` (per-point stdout/stderr references or payload snippets).
   - `sweep_rows.csv` must include:
     - deterministic `point_index`,
     - input columns,
     - flattened numeric output columns (e.g., `y__0`, `y__1`),
     - status/error/timing fields.
2) Execution modes and synchronization:
   - Extend run execution mode handling to support:
     - `serial`,
     - `parallel_local`,
     - `mpi`.
   - Synchronization contract:
     - one writer process/rank writes the centralized files,
     - worker processes/ranks send row/log payloads to that writer,
     - finalize step enforces deterministic row ordering by `point_index`.
3) Provenance compatibility:
   - Keep existing reproducibility/provenance guarantees (seed/spec/artifact digests, stdout/stderr persistence).
   - Keep existing run registry flows functional (`bayesmm runs list/show`), while exposing sweep artifact paths.
4) Tutorial 1 upgrade:
   - Update `tutorials/Tutorial_1.ipynb` to read centralized `sweep_rows.csv` (no per-run folder traversal).
   - Plot two heatmaps from toy outputs:
     - `sum` (`y__0`),
     - `product` (`y__1`).
   - Keep notebook robust to running from repo root or `tutorials/`.
5) Tests (must be updated):
   - Fast:
     - centralized CSV schema/row count/order checks,
     - serial vs local-parallel equivalence on toy sweep,
     - Tutorial 1 data-loading logic from centralized CSV.
   - Slow/optional:
     - MPI synchronized writer integration test (single output file, no row corruption).
6) Docs:
   - Update `README.md`, `PRD.md`, `TechSpec.md`, `CodeDesign.md`, `TEST_PLAN.md`, and `Status.md`.
   - Ensure docs explicitly state that centralized sweep output is the canonical path for DOE numeric results.

Constraints:
- One commit only for this prompt.
- Do not downsample or alter DOE cardinality.

Acceptance:
- Fast suite passes.
- Tutorial 1 produces both heatmaps from one centralized CSV output.
- MPI path is tested or clearly skipped with actionable reason in test output.
- Commit message: "feat: centralized sweep output and synchronized execution modes"

## Stop conditions
- If Codex proposes implicit downsampling or data reduction: reject and preserve full requested computation.
- If assumptions are needed for model semantics: pause and request clarification in Status.md and prompt output.
