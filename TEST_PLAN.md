# Test plan

> **Vocabulary.** Framework nouns (spec, design, design point, sweep, surrogate, coupling)
> are defined in [README.md](README.md#terms).

Fast tests (required, <30s):
1) Spec validation: valid spec passes
2) Spec validation: invalid spec fails with clear errors
3) `grid` design: count correct
4) `sobol` design: samples within bounds
5) Hashing/cache key changes on content change
6) Adapter contract: materialize creates run dir + provenance
7) Local runner smoke: run one design point end-to-end using toy_program
8) Centralized sweep sink: one sweep writes one `sweep_rows.csv` with deterministic `point_index` ordering
9) Centralized sweep sink: serial and local-parallel modes produce equivalent rows for same seed/spec
10) Tutorial 1 processing: build two toy heatmap matrices (`sum`, `product`) from one centralized sweep CSV
11) Optional backend runtime resilience: if PyMC is installed but toolchain compile is unavailable, optional backend tests skip/fallback with explicit reason while SBI tests still execute
12) SBI logging path: backend training summary logs are created under `tmp/sbi-logs/` (not repo root)

Slow tests:
- BioModels integration: fetch and simulate at least one model id (marked slow)
- MPI integration (Message Passing Interface; optional env): synchronized single-writer output to one centralized sweep CSV without row corruption

## Test markers (registered in pytest.ini)

| Marker | Meaning |
|--------|---------|
| `slow` | Tests that may exceed 30 seconds (BioModels, MPI) |
| `integration` | End-to-end tests across multiple components |
| `contract` | Interface contract tests for adapters and runners |
| `optional_backend` | Tests requiring optional backend dependencies (pymc and/or sbi); skipped gracefully when missing or when `MM_SKIP_OPTIONAL_BACKEND_TESTS=1` is set |
| `mpi` | Tests requiring an MPI launcher and mpi4py |
