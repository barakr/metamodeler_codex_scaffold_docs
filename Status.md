# Status: Metamodeling Automation Framework

## High level state
- Stage: planning documents refined; implementation not started
- Current focus: approve docs baseline, then begin incremental implementation from Prompt 0

## Folder structure
- src/metamodeler/: library code
- examples/: example specs and toy models
- tests/: unit and integration tests
- tmp/: scratch and temporary files, not committed
- githooks/: git hooks that enforce formatting, lint, and fast tests

## Implemented
- Documentation baseline refinement only:
  - PRD rewritten with explicit v1 scope, functional/non-functional requirements, and acceptance metrics.
  - TechSpec expanded with architecture contracts, provenance requirements, and phased probabilistic package strategy.
  - README updated as project map and reliability contract.
  - PROMPT_TO_CODEX prompt sequence hardened for reproducibility and staged delivery.

## Next steps, ordered
1) Human review and approve updated PRD/TechSpec/Prompt pack
2) Prompt 0 implementation: scaffold, hooks, packaging, CI basics
3) Prompt 1 implementation: typed ModelSpec validation
4) Prompt 2 implementation: DOE planning
5) Prompt 3 implementation: adapter + local runner + run store
6) Prompt 4 implementation: BioModels adapter milestone
7) Prompt 5 implementation: surrogate/meta interface placeholders

## Decisions log
- 2026-02-11: Prioritize execution/reproducibility core before advanced Bayesian coupling.
- 2026-02-11: Freeze v1 to local runner + typed contracts + run provenance; defer full surrogate/meta inference.
- 2026-02-11: Enforce explicit no-downsampling policy in docs and prompt pack.

## Open issues
- Missing repository URL in AGENTS.md (`<PUT_GIT_REPO_URL_HERE>`).
- Need final confirmation on first probabilistic backend target for post-v1 (`PyMC` candidate documented; benchmark gate pending).
