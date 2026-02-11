# Codex instructions for this repository

Repo:
- Git: https://github.com/barakr/metamodeler_codex_scaffold_docs

Project docs (keep these accurate):
- PRD: ./PRD.md
- Tech Spec: ./TechSpec.md
- Status: ./Status.md
- User Guide: ./README.md
- Prompt pack: ./PROMPT_TO_CODEX.md

Non-negotiable rules
- Keep changes small and incremental; make frequent commits
- Keep code minimal: delete orphaned code after refactors
- Any temporary scripts or debugging artifacts: place under ./tmp and ensure tmp is gitignored
- If logic is used more than once: extract it into a function or module
- Prefer explicit typed interfaces over implicit conventions

Reliability rules for simulations, data, and ML
- Never downsample, subsample, or “optimize” computations unless explicitly requested and recorded in Status.md
- Never change dataset size, sampling frequency, or DOE settings without recording the decision in Status.md
- Always log seeds, spec digests, model artifact digests, and full run provenance
- Save stdout/stderr for every model run; never discard logs
- After each meaningful code change: update Status.md

Testing requirements (must be enforced by git hooks)
- Any non-trivial change must add or update tests
- Maintain a fast test suite: under 30 seconds locally
- Before any commit: run `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`
- If fast tests fail: do not commit

Safety for shell execution
- Default sandbox: workspace-write
- Approval policy: on-request
- Never run destructive commands (recursive delete, force pushes, history rewrites) without explicit user approval, and record in Status.md

Definition of done for a task
- Code compiles / runs
- Fast tests pass
- Status.md updated
- Changelog of decisions recorded in Status.md
