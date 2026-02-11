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
- Implement `mm validate <spec>` with actionable errors.

Acceptance:
- Fast tests for valid and invalid specs.
- Status.md updated.
- Commit: `feat: modelspec validation`.

### Prompt 2: DOE planner
Task:
- Implement DOE strategies `grid` and `sobol`.
- Implement `mm plan <spec>` with deterministic preview output.

Acceptance:
- Fast tests for bounds, point counts, and determinism.
- Status.md updated.
- Commit: `feat: doe planner`.

### Prompt 3: execution core
Task:
- Implement adapter base interface + registry.
- Implement local process runner.
- Implement run store with provenance and stdout/stderr persistence.
- Implement `mm run <spec>`, `mm runs list`, `mm runs show <run_id>`.
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
   - `mm meta build metamodel.json` must output an IR artifact to the run store
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
   - `mm surrogate fit surrogate.json` trains and stores the artifact
   - `mm surrogate eval surrogate.json --inputs <json> --n 1000` loads artifact and outputs samples plus summary stats
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
2) Implement `mm meta build metamodel.json`:
   - loads surrogate artifacts
   - builds metamodel IR containing coupling and surrogate factors
   - stores IR artifact in the run store
3) Implement `mm meta sample metamodel.json --draws D --tune T --chains C --seed S`:
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
1) Add `mm tutorial` that prints a short guided flow and points to examples
2) Add `mm surrogate list` and `mm meta list` commands that show stored artifacts
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

## Stop conditions
- If Codex proposes implicit downsampling or data reduction: reject and preserve full requested computation.
- If assumptions are needed for model semantics: pause and request clarification in Status.md and prompt output.
