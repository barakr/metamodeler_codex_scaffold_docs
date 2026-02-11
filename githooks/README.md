# Git hooks (must be enforced)

These hooks enforce the same workflow discipline you used with Claude Code hooks, but using git hooks.
Make them executable and activate them via:

- `git config core.hooksPath githooks`

Hooks to implement (scripts live in this folder):

1) pre-commit
- Block commits on main/master
- Run: `ruff format .`, `ruff check .`, `pytest -q -m "not slow"`
- Fail if Status.md was not updated when src/ or examples/ changed

2) pre-push
- Run: `pytest -q -m "not slow"`
- Optionally run a deeper suite on CI only

3) commit-msg (optional)
- Enforce conventional commits
- Example: "feat: ...", "fix: ...", "chore: ..."

Notes:
- Store any hook logs under tmp/hook_logs
- Hooks must be deterministic and fast
