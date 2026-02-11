# Metamodeler

Metamodeler is a CLI-first framework for automated metamodeling:
- run heterogeneous source models from one typed spec,
- generate canonical datasets across DOE input plans,
- preserve full run provenance and logs,
- prepare clean inputs for surrogate and joint metamodel stages.

This repository is currently in planning/scaffold phase. The code implementation is intentionally staged.

## Documentation map
- Product requirements: `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/PRD.md`
- Technical design: `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/TechSpec.md`
- Project execution status and decisions: `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/Status.md`
- Prompt workflow for Codex: `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/PROMPT_TO_CODEX.md`
- Agent operating constraints: `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/AGENTS.md`

## Planned CLI flow (v1)
1) `mm validate spec.json`
2) `mm plan spec.json`
3) `mm run spec.json`
4) `mm runs list`
5) `mm runs show RUN_ID`

## Examples (spec stubs)
- `examples/toy_program/spec.toy_program.json`: local CLI toy model.
- `examples/biomodels/spec.biomodels.json`: BioModels SBML model by BioModels id.

## Reliability policy
- No silent downsampling/subsampling.
- Every run must store seed, spec digest, artifact digest, stdout, and stderr.
- Any major decision or scope shift is recorded in `Status.md`.
