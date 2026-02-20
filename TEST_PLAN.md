# Test plan

Fast tests (required, <30s):
1) Spec validation: valid spec passes
2) Spec validation: invalid spec fails with clear errors
3) DOE grid: count correct
4) DOE sobol: samples within bounds
5) Hashing/cache key changes on content change
6) Adapter contract: materialize creates run dir + provenance
7) Local runner smoke: run one design point end-to-end using toy_program
8) Centralized sweep sink: one DOE run writes one `sweep_rows.csv` with deterministic `point_index` ordering
9) Centralized sweep sink: serial and local-parallel modes produce equivalent rows for same seed/spec
10) Tutorial 1 processing: build two toy heatmap matrices (`sum`, `product`) from one centralized sweep CSV
11) Optional backend runtime resilience: if PyMC is installed but toolchain compile is unavailable, optional backend tests skip/fallback with explicit reason while SBI tests still execute
12) SBI logging path: backend training summary logs are created under `tmp/sbi-logs/` (not repo root)

Slow tests:
- BioModels integration: fetch and simulate at least one model id (marked slow)
- MPI integration (optional env): synchronized single-writer output to one centralized sweep CSV without row corruption
