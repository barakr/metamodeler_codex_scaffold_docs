# Tutorials — a self-contained mini-course

Twelve notebooks that take you from a 9-point toy sweep to a joint Bayesian metamodel
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
 T3        T4         T1/T2        T1              T5/T6       7a/7b/7c/T8
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
| 7a | What does it *mean* to couple two models? | Read a coupling as probability; tell propagation from inference | — |
| 7b | How is the coupled joint sampled, and can I trust it? | Sample it; check a sampler against pen and paper; read the two diagnostics that say whether to believe a run — effective sample size and r-hat | pymc (Steps 3-6) |
| 7c | What can I ask it, once coupled? | Condition on a measurement; infer across model boundaries; read a ridge | pymc |
| 8 | Does it generalise past two? | Couple three | pymc |
| 9 | Can I do it myself? | Build a pipeline unaided | pymc |

**Module 7 is three notebooks, not one.** Coupling is the concept the framework is named
for, and one 31-minute notebook was three questions wearing a trench coat. Each part is now
one sitting: **7a** needs no backend at all, so everyone can do the concept; **7b** and
**7c** need PyMC. 7c is where PyMC does the *sampling* rather than just the fitting, and
where you recover a hidden parameter from a measurement two models away.

## Environments

**Create one environment and you can do eleven of the twelve notebooks.**

| Env | Covers | Create with |
|---|---|---|
| **`py314_bayesmm`** | **everything except T2** — both surrogate backends included | `conda env create -f environment.yml` |
| `py312_bayesmm_biomodels` | T2 only | `conda env create -f environment-biomodels.yml` |
| `py312_bayesmm_pymc` | fallback, if SBI won't install for you | `conda env create -f environment-pymc.yml` |
| `py312_bayesmm_sbi` | fallback, if PyMC won't install for you | `conda env create -f environment-sbi.yml` |

The default environment carries both backends, so T5, T6 and 7b/7c work out of the box —
including **T6's Step 4**, which compares the two surrogates on the same query points and is
the one place in the series where you see them side by side. It used to print
`Step 4 SKIPPED` for everybody, because no shipped environment had both.

Tutorial 2 is the exception. Its simulator (`libroadrunner`) is published only on PyPI and
is the most platform-sensitive dependency in the project, so it stays in its own
environment: a failed install there costs you one notebook rather than all of them.

The two single-backend environments are kept for people whose platform fights one of the
backends, and because they reproduce CI's per-backend jobs — an "SBI" environment that
quietly also contained PyMC is what once hid a missing guard in T6.

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

`tests/test_tutorial_integration.py` executes all of them and checks each self-check
beacon. It is marked `slow`, so it is excluded from the default suite:

```bash
pytest -m slow tests/test_tutorial_integration.py
```

### Sampling budget

Tutorial 7c samples a coupled model several times, so it carries a knob:

```bash
MM_TUTORIAL_DRAWS=6000 jupyter lab      # default is 1500
```

The default is small on purpose — it has to finish on a student laptop and inside a CI
runner's per-cell timeout, and the notebook's claims are structural (a truth recovered, a
ridge present) rather than precision estimates. Raising it is a good exercise in its own
right: the posterior *means* barely move, the intervals narrow, and effective sample size
rises roughly in proportion.

Setting `REQUIRE_TUTORIAL_BACKENDS=1` turns any preflight skip into a failure — use
it when you intend to verify the science rather than the plumbing. The scheduled
`Deep CI` workflow runs exactly that, with every backend installed.
