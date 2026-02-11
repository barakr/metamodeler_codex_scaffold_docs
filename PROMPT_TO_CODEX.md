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

## Stop conditions
- If Codex proposes implicit downsampling or data reduction: reject and preserve full requested computation.
- If assumptions are needed for model semantics: pause and request clarification in Status.md and prompt output.
