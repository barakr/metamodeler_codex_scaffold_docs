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
- Tutorial hub (notebook): `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/tutorials/Tutorial_0.ipynb`
- Tutorial sequence (notebooks): `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/tutorials/Tutorial_1.ipynb` ... `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/tutorials/Tutorial_9.ipynb`
- Tutorial entry pointer: `/Users/barak/Downloads/metamodeler_codex_scaffold_docs/TUTORIAL.md`
  - includes guided onboarding text, auto-discovery of key artifacts, and visual checkpoints
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

## Install (cross-platform)

`metamodeler` runs on Python 3.11+ on Windows, macOS, and Linux.

**Recommended**: clone the repo, then either install with conda from `environment.yml`:
```
conda env create -f environment.yml
conda activate metamodeler
```
or with pip into a venv:
```
python -m venv .venv
# bash/zsh:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows cmd:
.venv\Scripts\activate.bat
pip install -e ".[pymc,sbi]"
```

After install, run:
```
mm doctor          # diagnose your env, list installed backends
mm setup           # interactive: suggest install commands & write defaults
```

## Optional Surrogate Backends
The surrogate interface is backend-neutral, but some backends require optional dependencies.

- PyMC: `pip install -e '.[pymc]'` or `conda install -c conda-forge pymc arviz`
- SBI: `pip install -e '.[sbi]'` or `conda install -c conda-forge pytorch sbi`
- `pymc` is the modern package (PyMC v5), and is the supported successor to legacy `pymc3`.
- If `pymc_gp` is selected without PyMC installed, `mm surrogate fit` raises an actionable install error.
- If `sbi_npe` is selected without `sbi`/`torch` installed, `mm surrogate fit` raises an actionable install error.
- Run `mm doctor` to see exactly which backends are present in your env.
- Real PyMC verification test:
  - `pytest -q tests/test_surrogate_backends.py -k pymc_gp_backend_fit_sample_and_logprob`
  - In toolchain-limited environments, use: `PYTENSOR_FLAGS='cxx=' pytest -q tests/test_surrogate_backends.py -k pymc_gp_backend_fit_sample_and_logprob`
- Real SBI verification test:
  - `pytest -q tests/test_surrogate_backends.py -k sbi_npe_backend_fit_sample_and_logprob`

## Multi-output (joint) surrogates
Surrogate specs may declare multiple outputs (`outputs: ["y1", "y2", ...]`). Use
`backend_config.output_correlation`:
- `"diagonal"` (default): independent per-output models. Fast; assumes outputs are uncorrelated given inputs.
- `"full"`: joint covariance (PyMC: LKJ prior on Cholesky; SBI: D-dim density estimator). Captures cross-output correlation.

See `examples/surrogates/surrogate.toy.multi_output.json` for a 2-output example.

## Surrogate Troubleshooting
- `Surrogate fit failed: Invalid backend_config key...`
  - Your backend config includes unsupported keys for the selected backend.
  - See allowed keys in `SurrogateSpec` validation errors and `PROMPT_TO_CODEX.md`.
- `Surrogate eval failed: No surrogate artifact found...`
  - Run `mm surrogate fit <spec>` first, or ensure `spec.name` matches a fitted artifact.
- `Surrogate eval failed: Surrogate backend mismatch...`
  - The latest artifact for that `spec.name` was trained with another backend.
  - Use a unique `spec.name` per backend, or refit with the intended backend.
- `Surrogate eval failed: ... input signature mismatch ...`
  - The requested spec inputs/outputs do not match the fitted artifact contract.
  - Keep input/output ordering and names identical between fit and eval specs.
- `Surrogate eval failed: --inputs must be a JSON object ...`
  - `--inputs` must be a dict keyed by input variable names, each value a numeric array.
  - Example: `--inputs '{"a":[0.1,0.2],"b":[1.0,1.5]}'`

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
After `pip install -e .` (or the conda env), the `mm` command works in any shell on any OS:
```
mm doctor                                                          # check env
mm validate examples/toy_program/spec.toy_program.json
mm run examples/toy_program/spec.toy_program.json
mm surrogate fit examples/surrogates/surrogate.toy.pymc_gp.json
mm meta build examples/metamodels/metamodel.simple.json
mm meta sample examples/metamodels/metamodel.simple.json --draws 100 --tune 50 --chains 2 --seed 1
```

If you have not installed the package and want to run from source:
- bash/zsh (macOS, Linux):
  `PYTHONPATH=src python -m metamodeler.cli.main validate examples/toy_program/spec.toy_program.json`
- Windows PowerShell:
  `$env:PYTHONPATH = "src"; python -m metamodeler.cli.main validate examples/toy_program/spec.toy_program.json`
- Windows cmd:
  `set PYTHONPATH=src && python -m metamodeler.cli.main validate examples/toy_program/spec.toy_program.json`

Utility commands:
- `mm doctor` (`--json` for machine-readable)
- `mm setup` (interactive) or `mm setup --non-interactive --backend pymc,sbi`
- `mm tutorial`
- `mm surrogate list`
- `mm meta list`
