# Tutorials — a self-contained mini-course

Ten notebooks that take you from a 9-point toy sweep to a joint Bayesian metamodel
over coupled models. They are designed to be worked **in order**: each one answers a
question the previous one raised, and several plant a question answered two
tutorials later.

Start with **`Tutorial_0.ipynb`** — it is orientation only (no model runs) and takes
about ten minutes, but it defines the vocabulary and the data-flow diagram every
later notebook assumes.

## The arc

Every tutorial is a zoom-in on one arrow of the same pipeline:

```
Spec  →  DOE plan  →  Sweep  →  sweep_rows.csv  →  Surrogate  →  Metamodel
 T3        T4         T1/T2        T1              T5/T6         T7/T8
                                                                    ↓
                                                        T9 composes all of it
```

| # | Question it answers | What you can do afterwards | Needs |
|---|---|---|---|
| 0 | What is a metamodel, and what will I install? | Read the map; check your kernel | — |
| 1 | What does the whole loop look like on something trivial? | Drive `validate → plan → run` | — |
| 2 | Does a real published model look different? | Recognise the same contract on real SBML | biomodels |
| 3 | What do I do when a spec is wrong? | Read a validation error and fix it | — |
| 4 | How do I choose where to sample? | Pick `grid` vs `sobol` deliberately | — |
| 5 | How do I replace an expensive model with a cheap one? | Fit a GP; read predictive uncertainty | pymc |
| 6 | Is the GP the only option? | Swap backends behind one contract | sbi |
| 7 | How do two models constrain each other? | Couple two surrogates | pymc |
| 8 | Does it generalise past two? | Couple three | pymc |
| 9 | Can I do it myself? | Build a pipeline unaided | pymc |

## Environments

Backends are **per-tutorial, not prerequisites** — you can start immediately and
install as needed. The main env deliberately ships without them.

| Env | Covers | Create with |
|---|---|---|
| `py314_bayesmm` | T0, T1, T3, T4 (+ all others in skip mode) | `conda env create -f environment.yml` |
| `py312_bayesmm_pymc` | T5, T7, T8, T9 | `conda env create -f environment-pymc.yml` |
| `py312_bayesmm_sbi` | T6 | `conda env create -f environment-sbi.yml` |
| `py312_bayesmm_biomodels` | T2 | `conda env create -f environment-biomodels.yml` |

Tutorial 2's simulator deps are PyPI-only (not on conda-forge), which is why they
get their own env rather than weighing down the main one.

Check what your kernel has with `bayesmm doctor`; `bayesmm setup` prints
OS-correct install commands.

**Running a notebook without its backend is safe.** A preflight banner names what is
missing and how to get it, the backend-specific steps skip, and the rest still runs.
The banner is not an error — but note that a tutorial in skip mode has not
demonstrated its science, only its plumbing.

## Cross-platform

Every notebook opens with a bootstrap cell that finds the repo root and puts `src/`
on `sys.path`. There are no `%%bash` cells and no `PYTHONPATH=` prefixes, so they run
identically on Windows cmd, Windows PowerShell, macOS and Linux.

## What each notebook contains

- Prerequisites, estimated time, learning aims and success criteria
- A **predict-before-you-run** moment — commit to an answer, then check it
- A recap of the load-bearing ideas
- A troubleshooting table
- At least one plot or diagram
- A self-check cell printing `[T<N> self-check OK]`, asserting the tutorial's
  scientific artifact actually exists and is non-trivial

## Verifying the whole set

`tests/test_tutorial_integration.py` executes all ten and checks each self-check
beacon. It is marked `slow`, so it is excluded from the default suite:

```bash
pytest -m slow tests/test_tutorial_integration.py
```

Setting `REQUIRE_TUTORIAL_BACKENDS=1` turns any preflight skip into a failure — use
it when you intend to verify the science rather than the plumbing. The scheduled
`Deep CI` workflow runs exactly that, with every backend installed.
