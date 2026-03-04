# Verification Report

**Date**: 2026-03-04
**Scope**: Cross-check all project documents against implementation; verify internal document consistency.
**Baseline**: `make fast` — 67 passed, 8 skipped, 3 deselected in 0.99s (all green).

---

## 1. CLI Commands: Docs vs Implementation

### Ground truth (src/bayesian_metamodeling/cli/main.py)

| Command | Implemented |
|---|---|
| `bayesmm --version` | Yes |
| `bayesmm validate <spec>` | Yes |
| `bayesmm plan <spec>` | Yes |
| `bayesmm run <spec>` | Yes |
| `bayesmm runs list` | Yes |
| `bayesmm runs show <run_id>` | Yes |
| `bayesmm surrogate fit <spec>` | Yes |
| `bayesmm surrogate eval <spec> --inputs --n` | Yes |
| `bayesmm surrogate list` | Yes |
| `bayesmm meta build <spec>` | Yes |
| `bayesmm meta sample <spec> --draws --tune --chains --seed` | Yes |
| `bayesmm meta list` | Yes |
| `bayesmm tutorial` | Yes |

### Cross-check results

| Document | Claims | Status |
|---|---|---|
| **PRD.md** | "CLI commands: validate, plan, run, runs list/show" | **Consistent** — PRD explicitly scopes v1 CLI to these 5; surrogate/meta are Phase 3-5 roadmap items. |
| **TechSpec.md** | Lists validate, plan, run, runs list, runs show; defers `bayesmm surrogate *` and `bayesmm meta *` | **Consistent** — implementation went beyond v1 scope (surrogate/meta fully implemented), but TechSpec correctly labeled them as deferred. |
| **CLAUDE.md** | Lists all 13 commands | **Consistent** — matches implementation exactly. |
| **Status.md** | Documents surrogate/meta CLI additions in Prompts 7-10 | **Consistent**. |

**Finding**: No missing or phantom CLI commands. All documented commands exist; all implemented commands are documented somewhere.

---

## 2. Spec Schemas: Docs vs Pydantic Models

### 2a. extra="forbid" convention

| Spec file | extra="forbid" set? |
|---|---|
| `modelspec.py` (all models) | Yes |
| `surrogate.py` (SurrogateSpec) | Yes |
| `metamodel.py` (all models) | Yes |
| `meta/ir.py` (all IR models) | Yes |

**Finding**: **Consistent** with CLAUDE.md convention "Pydantic v2 with `extra="forbid"`".

### 2b. ModelSpec fields

TechSpec.md describes `ModelSpec` fields at a high level ("model artifact, runner settings, I/O schema, design strategy, adapter mapping, reproducibility, storage target"). The code matches this decomposition exactly with sub-specs: `ModelInfoSpec`, `RunnerSpec`, `IOSchemaSpec`, `DesignSpec`, `AdapterSpec`, `ReproducibilitySpec`, `StorageSpec`.

**Finding**: **Consistent**.

### 2c. MetamodelCouplingSpec.kind vs CouplingFactorIR.coupling_type

| Level | "deterministic" variant |
|---|---|
| `MetamodelCouplingSpec.kind` | `"deterministic"` |
| `CouplingFactorIR.coupling_type` | `"deterministic_transform"` |

**Finding**: **Minor naming gap** — the spec-level enum value `"deterministic"` is mapped to `"deterministic_transform"` in the IR. This is an intentional abstraction boundary (the IR is more explicit), but it is not documented anywhere. The builder code handles the mapping.
**Severity**: Low (correct behavior, undocumented mapping).
**Recommendation**: Add a note in TechSpec.md Layer 4 or CodeDesign.md about this mapping.

### 2d. SurrogateSpec outputs constraint

Code enforces `len(outputs) == 1` via validator. This is not visible from the type hint (`list[str]` with `min_length=1`).

**Finding**: **Consistent** with Status.md which documents "Surrogate learning currently supports exactly one output variable." Not explicitly stated in TechSpec.md.
**Severity**: Low.

---

## 3. Sweep Artifact Contract: Docs vs Storage Code

### 3a. sweep_rows.csv columns

| Source | Columns |
|---|---|
| TechSpec.md | `point_index`, input columns, flattened outputs (e.g. `y__0`, `y__1`), `status`, `error`, optional timing |
| CodeDesign.md | Same + explicitly names "status/error/timing columns" |
| Code (sweep_store.py) | `point_index`, `<inputs>`, `<flattened outputs>`, `status`, `returncode`, `error`, `duration_sec`, `started_at`, `finished_at` |

**Finding**: **Consistent**. Code adds `returncode`, `duration_sec`, `started_at`, `finished_at` which qualify as the "optional timing fields" mentioned in TechSpec.

### 3b. sweep_manifest.json fields

| Source | Fields |
|---|---|
| TechSpec.md | "spec digest, seed, DOE size, output schema, execution mode, completion status" |
| Code | `sweep_id`, `status`, `total_points`, `success_count`, `failed_count`, `seed`, `spec_digest`, `artifact_digest`, `execution_mode`, `row_columns`, `rows_path`, `logs_path`, `started_at`, `finished_at` |

**Finding**: **Consistent**. Code provides all TechSpec-described fields plus additional useful ones (`sweep_id`, `artifact_digest`, paths, timestamps, success/failed counts).

### 3c. sweep_logs.jsonl

| Source | Format |
|---|---|
| TechSpec.md | "per-point stdout/stderr references or inline payloads keyed by `point_index`" |
| Code | `{"point_index": int, "status": str, "returncode": int, "stdout": str, "stderr": str}` |

**Finding**: **Consistent**.

---

## 4. Surrogate Protocol: Docs vs Code

| Source | Methods |
|---|---|
| TechSpec.md / PROMPT_TO_CODEX.md | `sample(inputs, n, seed)`, `log_prob(inputs, outputs)`, `summary(inputs)` |
| Code (surrogates/base.py) | `sample(inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray`, `log_prob(inputs: dict[str, np.ndarray], outputs: dict[str, np.ndarray]) -> np.ndarray`, `summary(inputs: dict[str, np.ndarray]) -> dict` |

**Finding**: **Consistent**. Note: PROMPT_TO_CODEX.md mentioned "numpy array or xarray" for `sample` return; implementation chose `np.ndarray`. This is a valid simplification.

---

## 5. IR Schema: Docs vs Code

TechSpec.md Layer 4 describes surrogates/meta as "interfaces and placeholders only" for v1. The actual IR implementation (in `meta/ir.py`) is fully fleshed out with `VariableIR`, `PriorFactorIR`, `CouplingFactorIR`, `SurrogateLikelihoodFactorIR`, `MetamodelIR`.

PROMPT_TO_CODEX.md Prompt 6 requirements match the implementation:
- Variables with name, type, shape, support, units
- Factor types: prior, coupling (equality_soft, gaussian_link, deterministic_transform), surrogate_likelihood

**Finding**: **Consistent** with prompt requirements. TechSpec says "placeholder" but implementation went further per the prompt sequence.

---

## 6. Cross-Document Consistency

### 6a. PRD scope vs actual implementation state

**Gap found**: PRD.md "Out of scope for v1" says "Production-grade joint Bayesian inference" but the roadmap includes Phases 3-5 for surrogate/meta. Status.md shows Prompts 6-13 fully implemented surrogate and metamodel layers. The PRD roadmap is consistent (Phases 3-5 cover this), but the "Out of scope for v1" section could mislead readers.

**Recommendation**: Add a reconciliation note to PRD.md clarifying that Phases 3-5 have been implemented. **[FIX APPLIED]**

### 6b. TEST_PLAN.md markers vs pytest.ini

| Marker | In TEST_PLAN.md? | In pytest.ini? | In TechSpec.md? |
|---|---|---|---|
| `slow` | Implicit (slow tests section) | Yes | Yes |
| `integration` | No | Yes | Yes |
| `contract` | No | Yes | Yes |
| `optional_backend` | Partially (item 11 references concept) | Yes | No |
| `mpi` | Implicit (MPI test) | Yes | Yes |

**Gap found**: TEST_PLAN.md does not have a markers section. TechSpec.md lists `slow`, `integration`, `contract`, `mpi` but not `optional_backend`.

**Recommendation**: Add a markers reference section to TEST_PLAN.md. Add `optional_backend` to TechSpec.md markers list. **[FIX APPLIED]**

### 6c. AGENTS.md rules vs git hooks

| AGENTS.md rule | Hook enforcement |
|---|---|
| "Before any commit: run ruff format, ruff check, pytest -q -m 'not slow'" | `pre-commit` hook does exactly this |
| "If fast tests fail: do not commit" | `pre-commit` hook exits non-zero |
| "After each meaningful code change: update Status.md" | `pre-commit` hook checks Status.md staging when src/ or examples/ changed |

**Finding**: **Consistent**. AGENTS.md says "must be enforced by git hooks" and they are.

### 6d. Git hooks: hardcoded paths

**Issue found**: `githooks/pre-commit` and `githooks/pre-push` contain hardcoded fallback path `/Users/barak/miniconda3/envs/py314_bayesmm/bin/` (note: `/Users/barak/`, not `/Users/barakraveh/`). This path does not exist on the current machine.

**Severity**: Low — hooks try `PATH` first and only fall back to the hardcoded path. The hooks work correctly when tools are on PATH.
**Recommendation**: Document this in Status.md open issues or update paths.

### 6e. TechSpec.md: missing runner.execution_env

**Gap found**: TechSpec.md does not mention `runner.execution_env` or `conda_env` support. This was added post-TechSpec (documented in Status.md, 2026-02-12).

**Recommendation**: Add a note to TechSpec.md RunnerSpec section. **[FIX APPLIED]**

### 6f. TechSpec.md: missing optional_backend marker

**Gap found**: TechSpec.md Testing strategy lists markers `slow`, `integration`, `contract`, `mpi` but not `optional_backend`.

**Recommendation**: Add `optional_backend` to the markers list. **[FIX APPLIED]**

---

## 7. Example and Tutorial Spec Validation

All specs validated successfully with `bayesmm validate`:

| Spec | Result |
|---|---|
| `examples/toy_program/spec.toy_program.json` | Pass |
| `examples/biomodels/spec.biomodels.json` | Pass |
| `examples/biomodels/spec.model1907260003.json` | Pass |
| `examples/biomodels/spec.prompt4.model1907260003.json` | Pass |
| `tutorials/specs/model.toy.grid.json` | Pass |
| `tutorials/specs/model.toy.sobol.json` | Pass |
| `tutorials/specs/model.biomodels.quick.json` | Pass |

Surrogate and metamodel specs (`tutorials/specs/surrogate.*.json`, `tutorials/specs/metamodel.*.json`, `examples/surrogates/*.json`, `examples/metamodels/*.json`) are not ModelSpecs and cannot be validated with `bayesmm validate`, but they are exercised by the test suite.

---

## 8. Tutorial Notebook Spot-Check

All 10 tutorials (Tutorial_0 through Tutorial_9) were checked for:
- Python imports from `bayesian_metamodeling` — do referenced modules/functions exist?
- Spec file paths — do referenced JSON specs exist?

**All 5 unique bayesian_metamodeling imports resolve correctly:**

| Import | Source |
|---|---|
| `bayesian_metamodeling.cli.main.main` | `src/bayesian_metamodeling/cli/main.py` |
| `bayesian_metamodeling.tutorials.load_toy_heatmap_grids` | `src/bayesian_metamodeling/tutorials/toy_heatmap.py` |
| `bayesian_metamodeling.spec.SurrogateSpec` | `src/bayesian_metamodeling/spec/surrogate.py` |
| `bayesian_metamodeling.surrogates.eval_surrogate` | `src/bayesian_metamodeling/surrogates/service.py` |
| `python -m bayesian_metamodeling.cli.main` (subprocess) | `src/bayesian_metamodeling/cli/main.py` |

**All 8 unique spec files referenced exist** under `tutorials/specs/`.

**Issue found**: Tutorials 3, 4, 7, 8, and 9 hardcode `/Users/barak/Downloads/metamodeler_codex_scaffold_docs` in `%%bash` cells, rather than using dynamic root detection. These notebooks will fail if run from a different checkout location.
**Severity**: Medium — affects portability for new users.
**Recommendation**: Migrate these notebooks to use dynamic root detection (as Tutorials 0-2 do).

---

## 9. Optional Backend Environment Verification

### Environments created and tested

| Environment | Python | Backend | Packages |
|---|---|---|---|
| `py314_bayesmm` | 3.14.3 | (none) | Core deps only |
| `py312_bayesmm_pymc` | 3.12 | PyMC | pymc 5.28.1, arviz 0.23.4 |
| `py312_bayesmm_sbi` | 3.12 | SBI (+PyMC) | sbi 0.25.0, torch 2.5.1, pymc 5.28.1 (transitive) |

Note: `requires-python >= 3.14` in `pyproject.toml` prevents `pip install -e .` on py312 envs. Tests run via `PYTHONPATH=src:tests` instead.

### Test results

**py314_bayesmm (core, no optional backends)**:
- Fast suite: **67 passed, 8 skipped**, 3 deselected (0.99s)
- Optional backend tests correctly skipped

**py312_bayesmm_pymc**:
- Optional backend tests: **2 passed, 2 skipped** (SBI tests skipped — not installed in this env)
- Full fast suite: **74 passed, 1 skipped**, 3 deselected (9.90s)

**py312_bayesmm_sbi** (also has PyMC via transitive deps):
- Optional backend tests: **4 passed, 0 skipped** (both PyMC and SBI tests run)
- Full fast suite: **75 passed**, 3 deselected (14.41s)

### Findings

- All optional backend tests pass when the relevant backend is installed.
- Skip behavior is correct: tests skip gracefully with clear reason when backend is missing.
- The `MM_SKIP_OPTIONAL_BACKEND_TESTS=1` flag mechanism was not separately tested but is implemented in `tests/conftest.py`.
- The SBI env inadvertently includes PyMC (transitive dependency through arviz/xarray chain), so all 4 optional_backend tests run there.

---

## 10. Environment Setup Finding

**Issue**: The `py314_bayesmm` conda environment referenced in CLAUDE.md, Status.md, and git hooks did not exist on this machine. It was created during this verification session.

**Severity**: Medium — without it, `make fast` cannot run and git hooks fail (though they fall back gracefully when tools are on PATH).

---

## Summary of Findings

| # | Area | Status | Severity |
|---|---|---|---|
| 1 | CLI commands: docs vs code | Consistent | — |
| 2 | Spec schemas: extra="forbid" | Consistent | — |
| 3 | ModelSpec fields | Consistent | — |
| 4 | CouplingSpec.kind vs IR.coupling_type naming | Minor gap (undocumented mapping) | Low |
| 5 | SurrogateSpec single-output constraint | Consistent (documented in Status.md) | — |
| 6 | Sweep CSV columns | Consistent | — |
| 7 | Sweep manifest fields | Consistent | — |
| 8 | Sweep logs format | Consistent | — |
| 9 | SurrogateModel protocol | Consistent | — |
| 10 | MetamodelIR structure | Consistent | — |
| 11 | PRD v1 scope vs implementation | Gap — surrogate/meta implemented beyond v1 | Low |
| 12 | TEST_PLAN.md missing markers section | Gap | Low |
| 13 | TechSpec.md missing optional_backend marker | Gap | Low |
| 14 | TechSpec.md missing runner.execution_env | Gap | Low |
| 15 | Git hooks: hardcoded stale paths | Issue | Low |
| 16 | py314_bayesmm env missing | Issue | Medium |
| 17 | Example/tutorial spec validation | All pass | — |
| 18 | Tutorial imports and spec refs | All valid | — |
| 19 | Tutorials 3-9: hardcoded checkout paths | Issue | Medium |
| 20 | PyMC optional_backend tests (py312_bayesmm_pymc) | 2 passed, 2 skipped | — |
| 21 | SBI optional_backend tests (py312_bayesmm_sbi) | 4 passed | — |
| 22 | Full fast suite in PyMC env | 74 passed, 1 skipped | — |
| 23 | Full fast suite in SBI env | 75 passed | — |

## Fixes Applied

1. **TEST_PLAN.md**: Added markers reference section with all 5 markers.
2. **TechSpec.md**: Added `optional_backend` to markers list; added `runner.execution_env` note; added spec-to-IR `deterministic` → `deterministic_transform` mapping note (Layer 4).
3. **PRD.md**: Added reconciliation note clarifying Phases 3-5 implementation status.
4. **githooks/pre-commit**, **githooks/pre-push**: Replaced hardcoded `/Users/barak/miniconda3/...` fallback paths with `${HOME}/miniconda3/...` for portability.
5. **Tutorials 3, 4, 5, 7, 8, 9**: Replaced all 20 hardcoded `/Users/barak/Downloads/metamodeler_codex_scaffold_docs` paths with dynamic root detection (matching the pattern already used in Tutorials 0, 1, 2, 6).

## Post-Fix Verification

`make fast` passes after all changes (67 passed, 8 skipped — unchanged from baseline).
