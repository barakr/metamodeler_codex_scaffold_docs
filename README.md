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
- Code design validation: `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/CodeDesign.md`
- User tutorial: `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/TUTORIAL.md`
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
- `examples/surrogates/surrogate.toy.pymc_gp.json`: toy surrogate training spec.
- `examples/metamodels/metamodel.simple.json`: coupled metamodel spec for sampling flow.

## Optional Surrogate Backends
The surrogate interface is backend-neutral, but some backends require optional dependencies.

- Install PyMC backend support in the project conda environment:
  - `conda install -n py314_metamodeling -c conda-forge pymc arviz`
  - or `pip install -e '.[pymc]'`
- If `pymc_gp` is selected without PyMC installed, `mm surrogate fit` raises an actionable install error.

## Reliability policy
- No silent downsampling/subsampling.
- Every run must store seed, spec digest, artifact digest, stdout, and stderr.
- Any major decision or scope shift is recorded in `Status.md`.

## Backend-Neutral IR
Metamodeler now builds a backend-neutral metamodel IR before inference/runtime execution.
- Variables and factors are serialized in a backend-independent schema.
- Coupling factors and surrogate-likelihood factors are represented uniformly.
- Compiler boundary:
  - `compile_metamodel(ir, backend=\"pymc\")` is available.
  - `compile_metamodel(ir, backend=\"numpyro\")` is available.
- `mm meta build <metamodel.json>` validates spec input and writes an IR artifact to `tmp/metamodel_ir/`.

## Backend Selection (`ppl_backend`)
`MetaModelSpec` accepts:
- `ppl_backend: "pymc"`
- `ppl_backend: "numpyro"`

The same JSON interface is used for both backends (`mm meta sample ...`).

Known numerical differences:
- The current baseline samplers may produce slightly different coupling-noise realizations between backends.
- Small posterior summary differences are expected due backend-specific sampling jitter and initialization.

## End-to-End Quickstart
```bash
PYTHONPATH=src python -m metamodeler.cli.main validate examples/toy_program/spec.toy_program.json
PYTHONPATH=src python -m metamodeler.cli.main run examples/toy_program/spec.toy_program.json
PYTHONPATH=src python -m metamodeler.cli.main surrogate fit examples/surrogates/surrogate.toy.pymc_gp.json
PYTHONPATH=src python -m metamodeler.cli.main meta build examples/metamodels/metamodel.simple.json
PYTHONPATH=src python -m metamodeler.cli.main meta sample examples/metamodels/metamodel.simple.json --draws 100 --tune 50 --chains 2 --seed 1
```

Utility commands:
- `mm tutorial`
- `mm surrogate list`
- `mm meta list`
