# Status: Metamodeling Automation Framework

## High level state
- Stage: scaffold baseline implemented (Prompt 0 scope)
- Current focus: verify scaffold guardrails and start typed ModelSpec validation (Prompt 1)

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

## Next steps, ordered
1) Implement typed `ModelSpec` + nested specs and validation CLI (`mm validate`)
2) Add JSON schema artifact generation for ModelSpec
3) Add fast tests for valid/invalid spec behavior
4) Implement DOE planner (`grid`, `sobol`) with deterministic preview
5) Implement adapter/runner/store execution path

## Decisions log
- 2026-02-11: Prioritize execution/reproducibility core before advanced Bayesian coupling.
- 2026-02-11: Freeze v1 to local runner + typed contracts + run provenance; defer full surrogate/meta inference.
- 2026-02-11: Enforce explicit no-downsampling policy in docs and prompt pack.
- 2026-02-11: Scaffold step implemented with strict hooks and no modeling logic added.
- 2026-02-11: Main-branch commit blocking hook includes explicit override (`ALLOW_MAIN_COMMIT=1`) to support controlled bootstrap commits.

## Open issues
- Need final confirmation on first probabilistic backend target for post-v1 (`PyMC` candidate documented; benchmark gate pending).
- `mm` currently exposes scaffold help/version only; domain commands are pending by design.
