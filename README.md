# Metamodeler

Metamodeler is a CLI-first framework for automated metamodeling:
- run heterogeneous source models from one typed spec,
- generate canonical datasets across DOE input plans,
- preserve full run provenance and logs,
- prepare clean inputs for surrogate and joint metamodel stages.

This repository is currently in planning/scaffold phase. The code implementation is intentionally staged.

## Documentation map
All paths are relative to the repo root.
- Product requirements: `PRD.md`
- Technical design: `TechSpec.md`
- Code design validation: `CodeDesign.md`
- Tutorial hub (notebook): `tutorials/Tutorial_0.ipynb`
- Tutorial sequence (notebooks): `tutorials/Tutorial_1.ipynb` ... `tutorials/Tutorial_9.ipynb`
- Tutorial folder index: `tutorials/README.md`
- Project execution status and decisions: `Status.md`
- Prompt workflow for Codex: `PROMPT_TO_CODEX.md`
- Agent operating constraints: `CLAUDE.md`

## Planned CLI flow (v1)
1) `bayesmm validate spec.json`
2) `bayesmm plan spec.json`
3) `bayesmm run spec.json`
4) `bayesmm runs list`
5) `bayesmm runs show RUN_ID`

## Centralized DOE Output
`bayesmm run` persists DOE numeric results in one centralized sweep artifact per run:
- `sweep_rows.csv`: one row per DOE point (`point_index`, inputs, flattened outputs, status/error/timing)
- `sweep_manifest.json`: sweep metadata, digests, and schema
- `sweep_logs.jsonl`: per-point stdout/stderr payloads

This is the canonical path for DOE sweep numeric results across:
- `runner.sweep_mode: "serial"`
- `runner.sweep_mode: "parallel_local"`
- `runner.sweep_mode: "mpi"` (single-writer on rank 0)

`bayesmm run` now writes centralized DOE sweep artifacts (one table per sweep):
- `sweep_rows.csv` (all grid/sobol points in one file),
- `sweep_manifest.json`,
- `sweep_logs.jsonl`.

## Examples (spec stubs)
- `examples/toy_program/spec.toy_program.json`: local CLI toy model.
- `examples/biomodels/spec.biomodels.json`: BioModels SBML model by BioModels id.
- `examples/surrogates/surrogate.toy.pymc_gp.json`: toy surrogate training spec.
- `examples/metamodels/metamodel.simple.json`: coupled metamodel spec for sampling flow.

## Install (cross-platform)

Runs on Python 3.12+ on Windows, macOS, and Linux. Clone the repo, then either:

**conda (recommended)** — `conda env create -f environment.yml && conda activate py314_bayesmm`

This is the main development environment: the framework, the tutorial stack,
and the dev tooling (`pytest`, `ruff`, `cmake`) that `make fast`, `make lint`
and the `githooks/` hooks all expect. The two surrogate backends live in their
own environments, because pinning PyMC, SBI and PyTorch in one solve is fragile:

| File | Environment | Use |
|------|-------------|-----|
| `environment.yml` | `py314_bayesmm` | main dev: build, test, tutorials |
| `environment-pymc.yml` | `py312_bayesmm_pymc` | PyMC GP surrogates |
| `environment-sbi.yml` | `py312_bayesmm_sbi` | SBI NPE surrogates |
| `environment-all.yml` | `py312_bayesmm_all` | **both backends — use this to work through the tutorials** (T2 also needs `environment-biomodels.yml`) |

The single-backend envs are deliberately single-backend: they mirror CI's per-backend
jobs, and their value is in what they *don't* have. But several tutorial steps need both
at once — Tutorial 6's Step 4 compares the GP surrogate against the neural posterior on
the same query points, and that is the cell where you can actually see what each buys
you. If you are learning rather than testing, create `py312_bayesmm_all`.

**pip + venv**:
```
python -m venv .venv
# bash/zsh:            source .venv/bin/activate
# Windows PowerShell:  .venv\Scripts\Activate.ps1
# Windows cmd:         .venv\Scripts\activate.bat
pip install -e ".[pymc,sbi]"
```

After install, verify your environment and get install hints with the configurer:
```
bayesmm doctor        # diagnose OS, Python, env, installed backends (--json for machine output)
bayesmm setup         # interactive; or: bayesmm setup --non-interactive --backend pymc,sbi
```

## Multi-output (joint) surrogates
`SurrogateSpec` accepts multiple outputs (`outputs: ["y1", "y2", ...]`). Set
`backend_config.output_correlation`:
- `"diagonal"` (default): independent per-output models — fast.
- `"full"`: joint covariance (PyMC: `LKJCholeskyCov` prior; SBI: a D-dim density estimator).

See `examples/surrogates/surrogate.toy.multi_output.json`.

## Optional Surrogate Backends
The surrogate interface is backend-neutral, but some backends require optional dependencies.

- Install PyMC backend support in the project conda environment:
  - `conda install -n <env_name> -c conda-forge pymc arviz`
  - or `pip install -e '.[pymc]'`
- Install SBI backend support in the project conda environment:
  - `conda install -n <env_name> -c conda-forge pytorch sbi`
  - or `pip install -e '.[sbi]'`
- Run `bayesmm doctor` any time to see exactly which backends are present.
- `pymc` is the modern package (PyMC v5), and is the supported successor to legacy `pymc3`.
- If `pymc_gp` is selected without PyMC installed, `bayesmm surrogate fit` raises an actionable install error.
- If `sbi_npe` is selected without `sbi`/`torch` installed, `bayesmm surrogate fit` raises an actionable install error.
- Real PyMC verification test:
  - `PYTHONPATH=src python -m pytest -q tests/test_surrogate_backends.py -k pymc_gp_backend_fit_sample_and_logprob`
  - In toolchain-limited environments, use:
    - `PYTENSOR_FLAGS='cxx=' PYTHONPATH=src python -m pytest -q tests/test_surrogate_backends.py -k pymc_gp_backend_fit_sample_and_logprob`
- Real SBI verification test:
  - `PYTHONPATH=src python -m pytest -q tests/test_surrogate_backends.py -k sbi_npe_backend_fit_sample_and_logprob`
- Optional backend fast-suite behavior:
  - optional-backend tests run when dependencies are installed and runtime-compatible.
  - if PyMC is installed but local toolchain compilation is unavailable, PyMC optional tests are skipped/fallback while SBI paths continue to run.
- Optional backend tests can be disabled explicitly:
  - `MM_SKIP_OPTIONAL_BACKEND_TESTS=1 PYTHONPATH=src python -m pytest -q`
- SBI training summary logs are written under:
  - `tmp/sbi-logs/`
- Tutorial 6 notebook commands are path-portable and can run from either repo root or `tutorials/`.

## Runner Execution Environment
- `runner.execution_env` is optional and defaults to `{}`.
- If set, supported keys are:
  - `conda_env`: run model commands via `conda run -n <conda_env> ...`.
- `runner.sweep_mode` controls local execution strategy for DOE sweeps:
  - `serial` (default)
  - `parallel_local` (uses `runner.workers`, defaults to `runner.resources.cpus`)
  - `mpi` (requires `mpi4py` + MPI launcher; rank 0 writes centralized sweep files)
- Example:
```json
{
  "runner": {
    "mode": "local_process",
    "resources": {"cpus": 1, "mem_gb": 1, "walltime_min": 5},
    "execution_env": {"conda_env": "py312_bayesmm_pymc"},
    "sweep_mode": "parallel_local",
    "workers": 4
  }
}
```

## Sweep Execution Modes
- `runner.sweep_mode` controls how DOE points are executed:
  - `serial` (default),
  - `parallel_local` (threaded local coordinator + single centralized writer),
  - `mpi` (rank 0 centralized writer).
- `runner.workers` is supported only with `runner.sweep_mode: "parallel_local"`.

Example:
```json
{
  "runner": {
    "mode": "local_process",
    "resources": {"cpus": 4, "mem_gb": 4, "walltime_min": 10},
    "sweep_mode": "parallel_local",
    "workers": 4
  }
}
```

MPI example (launch):
```bash
mpirun -n 4 PYTHONPATH=src python -m bayesian_metamodeling.cli.main run tutorials/specs/model.toy.grid.json
```

Optional: verify the MPI single-writer contract end-to-end:
```bash
mpirun -n 2 PYTHONPATH=src python -m pytest -q -m mpi tests/test_mpi_sweep_integration.py
```
Requires `mpi4py` and an MPI implementation (e.g. `mpich` or `openmpi`) — install
both via conda for self-contained dependencies:
`conda install -n <env_name> -c conda-forge mpi4py mpich`. The test runs a
2x2 grid sweep across two ranks and asserts that exactly one centralized
`sweep_rows.csv` is produced (rank 0 writer; rank 1 synchronizes via barrier).
The standard fast suite skips this test automatically when `mpi4py` is
unavailable or when launched without `mpirun`.

## Surrogate Troubleshooting
- `Surrogate fit failed: Invalid backend_config key...`
  - Your backend config includes unsupported keys for the selected backend.
  - See allowed keys in `SurrogateSpec` validation errors and `PROMPT_TO_CODEX.md`.
- `Surrogate eval failed: No surrogate artifact found...`
  - Run `bayesmm surrogate fit <spec>` first, or ensure `spec.name` matches a fitted artifact.
- `Surrogate eval failed: Surrogate backend mismatch...`
  - The latest artifact for that `spec.name` was trained with another backend.
  - Use a unique `spec.name` per backend, or refit with the intended backend.
- `Surrogate eval failed: ... input signature mismatch ...`
  - The requested spec inputs/outputs do not match the fitted artifact contract.
  - Keep input/output ordering and names identical between fit and eval specs.
- `Surrogate eval failed: --inputs must be a JSON object ...`
  - `--inputs` must be a dict keyed by input variable names, each value a numeric array.
  - Example: `--inputs '{"a":[0.1,0.2],"b":[1.0,1.5]}'`

## Optional case study: `projects/tcr_signaling`
The repo includes a real-world scientific reproduction (Neve-Oz, Sherman & Raveh
2024, *Frontiers in Immunology*) as a git submodule under `projects/tcr_signaling`.
It is **not** part of *this* repo's CI matrix — it has its own, so a submodule
failure never reddens the framework's status — but it is fully cross-platform:

- Native build: requires CMake ≥ 3.20 + a C++ compiler. Built and tested on
  **Windows (MSVC), macOS (Clang) and Linux (GCC)** by the submodule's `KS model
  CI`, on every push and daily. Build with `cmake -S . -B build && cmake --build
  build`; `make` is a Unix shorthand for the same thing. See the submodule's
  [build prerequisites](projects/tcr_signaling/README.md#build-prerequisites-windows-macos-linux)
  for the per-OS install commands.
- GPU kernel: the kinetic-segregation GPU path uses Apple Metal and is therefore
  macOS-only. CPU paths work everywhere and produce the same physics.
- The parent `pytest.ini` does NOT pick up the submodule (its custom
  `deterministic` marker is only registered inside the submodule).
- Treated as read-only by the parent repo's tooling — changes go through the
  submodule's own workflow.

If you cloned without `--recurse-submodules`, the submodule is empty and the
`bayesian_metamodeling` package is fully usable on its own. Only initialize the
submodule if you actually need the case study:
```bash
git submodule update --init projects/tcr_signaling
git submodule foreach 'git checkout main'   # see note below
cd projects/tcr_signaling/models/kinetic_segregation && make
cd projects/tcr_signaling && pytest -q
```

The `git checkout main` is a one-time step. Git's initial submodule checkout
always lands on a detached HEAD — it checks out the recorded commit before any
branch exists — so commits made there would belong to no branch. Running it once
attaches the submodule; `update = rebase` in `.gitmodules` keeps it attached
through every later `git submodule update` and `git pull`.

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
- `bayesmm meta build <metamodel.json>` validates spec input and writes an IR artifact to `tmp/metamodel_ir/`.

## Backend Selection (`ppl_backend`)
`MetaModelSpec` accepts:
- `ppl_backend: "pymc"`
- `ppl_backend: "numpyro"`

The same JSON interface is used for both backends (`bayesmm meta sample ...`).

Known numerical differences:
- The current baseline samplers may produce slightly different coupling-noise realizations between backends.
- Small posterior summary differences are expected due backend-specific sampling jitter and initialization.

## Sampling method (`--method`)

`bayesmm meta sample` takes `--method`, and the choice decides whether you get
inference or propagation. This is the single most consequential flag in the metamodel
layer, so it is worth reading before interpreting any output.

| | `propagate` (default) | `joint` |
|---|---|---|
| how draws are made | each variable from its prior, then coupled targets overwritten by `transform(source)` | Metropolis over the full joint log-density |
| surrogate likelihoods | **not evaluated** | evaluated — the surrogates are evidence |
| a coupling informs | its **target** only | **both** ends |
| honest name for the output | forward uncertainty propagation | posterior |

There is a third value, `--method nuts`. It samples **the same density as `joint`**, with
gradients instead of a random walk, by writing the model as a PyTensor graph. It applies
only when every surrogate in the model is `pymc_gp` — that backend is linear regression, so
its predictive density is symbolic — and falls back to `joint` with a printed reason
otherwise. `sbi_npe` is a torch normalizing flow whose gradients would need a custom
PyTensor `Op`, which is not written.

Measured on the TCR metamodel (14 variables, 4 fitted surrogates):

| method | worst-variable ESS | efficiency | diagnostics |
|---|---|---|---|
| `joint` | 10 / 1500 | 0.7% | accept_rate |
| `nuts` | 1744 / 3000 | **58%** | r-hat 1.0036, 0 divergences |

Prefer `nuts` when it applies. Keep `joint` in mind as the backend-neutral fallback: it is
the one verified against a closed-form Gaussian, and the only one that works when a
surrogate really is a black box.

```bash
bayesmm meta sample metamodel.json --draws 2000 --tune 1000 --seed 7 --method joint
```

Use `joint` when you have asked "how do I sample after declaring a coupling between
two models' variables?" — that is what it answers. Under `propagate`, declaring a
Gaussian coupling reshapes the target and leaves the source at exactly its prior, and
the surrogates in your spec are validated but never consulted.

Two practical notes:

- **It is gradient-free.** A fitted surrogate's `log_prob` is a black box, so the
  sampler is random-walk Metropolis. That costs efficiency, not correctness — but
  check the reported `accept_rate`, and treat effective sample size as something to
  measure rather than assume, especially in higher dimensions.
- **Cost is dominated by surrogate evaluations.** `sbi_npe.log_prob` measures ~23 ms
  per call against ~0.2 ms for `pymc_gp`, so an NPE-backed joint sample is roughly
  100x more expensive per step. Budget accordingly, and prefer fewer, longer chains.

`joint` needs real fitted surrogates: run `bayesmm surrogate fit` first.

## Conditioning on what you measured (`observed`)

A metamodel is usually built to answer *"given that I measured this, what does it imply
about everything else?"* Put the measurement in the spec:

```json
{
  "observed": {"contact_fraction": 0.30}
}
```

An observed variable is **clamped**: never drawn, never proposed, held at its value while
every factor that mentions it is evaluated there. It leaves the sample space, so the
sampler works in one fewer dimension.

- Under `--method joint` this is real conditioning — information flows to *every* variable
  connected to the observed one, upstream and downstream.
- Under `--method propagate` it only flows downstream, because propagation never looks
  upstream. That is a property of the method, not a bug, and both paths record `observed`
  in `inference_data.json` so a stored result says what it was conditioned on.

Observing the target of a `deterministic` coupling is refused: that variable is computed
from its source, so asserting a second value for it is a contradiction the sampler would
otherwise hide behind healthy-looking draws.

Before this existed the only way to fake an observation was a very tight prior. Avoid it —
it puts the posterior on a thin ridge, which is exactly the geometry the gradient-free
sampler cannot follow.
 If an artifact
is a placeholder without a `backend_payload`, the command says so and names the fix
rather than silently sampling something meaningless.

## End-to-End Quickstart
```bash
PYTHONPATH=src python -m bayesian_metamodeling.cli.main validate examples/toy_program/spec.toy_program.json
PYTHONPATH=src python -m bayesian_metamodeling.cli.main run examples/toy_program/spec.toy_program.json
PYTHONPATH=src python -m bayesian_metamodeling.cli.main surrogate fit examples/surrogates/surrogate.toy.pymc_gp.json
PYTHONPATH=src python -m bayesian_metamodeling.cli.main meta build examples/metamodels/metamodel.simple.json
PYTHONPATH=src python -m bayesian_metamodeling.cli.main meta sample examples/metamodels/metamodel.simple.json --draws 100 --tune 50 --chains 2 --seed 1
```

Utility commands:
- `bayesmm tutorial`
- `bayesmm surrogate list`
- `bayesmm meta list`
