# Status: Metamodeling Automation Framework

## High level state
- Stage: Prompt 2 implementation complete (DOE planner)
- Current focus: move to Prompt 3 (execution pipeline)

## Folder structure
- src/metamodeler/: library code
- examples/: example specs and toy models
- tests/: unit and integration tests
- tmp/: scratch and temporary files, not committed
- githooks/: git hooks that enforce formatting, lint, and fast tests

## Implemented
- Scaffold created:
  - Python package skeleton under `src/metamodeler/` including target subpackages from TechSpec.
  - `pyproject.toml` added with setuptools build, Python package metadata, and CLI entry point `mm`.
  - Minimal CLI scaffold at `src/metamodeler/cli/main.py`.
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
  - Added typed Pydantic v2 spec model hierarchy in `src/metamodeler/spec/modelspec.py`:
    - `ModelSpec`, `VariableSpec`, `AdapterSpec`, `RunnerSpec` and nested contract models.
  - Added schema export helper in `src/metamodeler/spec/schema.py`.
  - Added JSON schema artifact:
    - `src/metamodeler/spec/modelspec.schema.json`
  - Added `mm validate <spec>` command with actionable validation output in:
    - `src/metamodeler/cli/main.py`
  - Added fast tests in:
    - `tests/test_modelspec_validation.py`
  - Added shared test path setup in:
    - `tests/conftest.py`
- Prompt 2 implemented:
  - Added DOE planner module in:
    - `src/metamodeler/designs/planner.py`
  - Added strategy support:
    - `grid` cartesian product planning
    - `sobol` deterministic low-discrepancy planning with bounds scaling
  - Added `mm plan <spec>` CLI command with deterministic preview output.
  - Added fast tests in:
    - `tests/test_doe_planner.py`

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

## Next steps, ordered
1) Implement adapter registry + local runner + dataset store
2) Implement run registry CLI commands
3) Add toy-program fast end-to-end run test
4) Prepare BioModels adapter milestone as slow/integration path
5) Add surrogate/meta interface placeholders with CLI wiring

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

## Open issues
- Need final confirmation on first probabilistic backend target for post-v1 (`PyMC` candidate documented; benchmark gate pending).
- `mm` currently exposes scaffold help/version only; domain commands are pending by design.
- `py312` environment currently has dependency conflicts due direct `pip` install of `libroadrunner`; this was used for design verification only and should be isolated before production workflows.
