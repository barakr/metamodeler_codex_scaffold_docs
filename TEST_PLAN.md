# Test plan

Fast tests (required, <30s):
1) Spec validation: valid spec passes
2) Spec validation: invalid spec fails with clear errors
3) DOE grid: count correct
4) DOE sobol: samples within bounds
5) Hashing/cache key changes on content change
6) Adapter contract: materialize creates run dir + provenance
7) Local runner smoke: run one design point end-to-end using toy_program

Slow tests:
- BioModels integration: fetch and simulate at least one model id (marked slow)
