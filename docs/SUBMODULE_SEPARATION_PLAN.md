# Submodule Documentation Separation Plan

**Authors**: DevOps Lead + Project Manager (joint session)
**Date**: 2026-03-05
**Status**: Implementing

---

## Problem Statement

We have a mono-repo feel in a multi-repo reality. The root project
(`metamodeler_codex_scaffold_docs`) is the **framework** — it provides the
`bayesian-metamodeling` package. The submodule at `projects/tcr_signaling` is an
**independent research project** that *uses* the framework as a dependency.

Right now the boundaries are blurred:

| Symptom | Impact |
|---------|--------|
| Root `Status.md` contains TCR-specific decision log entries (KS model MC loop fixes, grid_size changes, per-point seed derivation) | AI agents (Claude) and developers confuse framework status with project status |
| Root `CLAUDE.md` has no mention that `projects/tcr_signaling` is a separate Git repo with its own lifecycle | Claude treats the submodule as part of the framework and applies framework rules (ruff, make fast, Status.md updates) to submodule code |
| Submodule has no `CLAUDE.md` | When Claude works *inside* the submodule, it has no project-specific instructions and falls back to the root ones, which don't apply |
| Submodule has no `Status.md` | TCR-specific decisions get logged in the wrong place |
| No `.claude/` settings in the submodule | No way to give Claude submodule-scoped instructions |

## Design Principles

1. **Each Git repo owns its own docs.** If it has its own `.git`, it gets its own
   `CLAUDE.md`, `Status.md`, and `README.md`.
2. **The root only describes the framework.** It acknowledges submodules exist
   under `projects/` but does not track their internal status or decisions.
3. **Submodule docs describe the research project.** They reference the framework
   as an external dependency (`bayesian-metamodeling`) — same as any user would.
4. **Claude context isolation.** When working in `projects/tcr_signaling/`, Claude
   should load the submodule's `CLAUDE.md` as its primary guide. The root
   `CLAUDE.md` applies only when working on framework code.

## Action Items

### Phase 1: Submodule gets its own identity (this PR)

| # | Action | Owner | File |
|---|--------|-------|------|
| 1 | Create `projects/tcr_signaling/CLAUDE.md` with TCR-specific dev guide | DevOps | submodule |
| 2 | Create `projects/tcr_signaling/Status.md` seeded with TCR entries migrated from root | PM | submodule |
| 3 | Update root `CLAUDE.md` to add a "Submodule Boundary" section explaining the separation | DevOps | root |
| 4 | Clean root `Status.md` — move TCR-specific entries to submodule, leave a migration note | PM | root |

### Phase 2: Enforcement (follow-up)

| # | Action | Owner |
|---|--------|-------|
| 5 | Add a `.claude/settings.json` in the submodule pointing to its own `CLAUDE.md` |
| 6 | Update root git hooks to skip `ruff`/`make fast` for paths under `projects/` |
| 7 | Submodule gets its own `Makefile` or `justfile` for lint/test/fmt |
| 8 | Consider whether submodule tests should still be discoverable from root pytest |

## File Ownership Matrix

| File | Lives in | Tracks |
|------|----------|--------|
| `CLAUDE.md` | root | Framework dev guide, coding conventions, CLI, architecture |
| `Status.md` | root | Framework implementation progress and decisions |
| `PRD.md`, `TechSpec.md`, `CodeDesign.md` | root | Framework requirements and design |
| `CLAUDE.md` | `projects/tcr_signaling/` | TCR project dev guide, model descriptions, workflows |
| `Status.md` | `projects/tcr_signaling/` | TCR project progress, model-specific decisions |
| `README.md` | `projects/tcr_signaling/` | TCR project overview (already exists) |

## How Claude Should Behave

**When working on framework code** (`src/`, `tests/`, `examples/`, root files):
- Follow root `CLAUDE.md` rules
- Update root `Status.md`
- Run `make fmt && make lint && make fast`

**When working on TCR signaling** (`projects/tcr_signaling/**`):
- Follow submodule `CLAUDE.md` rules
- Update submodule `Status.md`
- Run submodule-specific test commands
- Treat `bayesian-metamodeling` as an external package

**Boundary signal**: If a task touches both, update both Status files. The root
entry should say *what framework change was needed*; the submodule entry should
say *what project change motivated it*.
