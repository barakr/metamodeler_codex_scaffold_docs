# Code Design & Security Review — Upgrade Plan

**Date:** 2026-08-12 · **Branch:** `feature/design-security-review` · **Status:** proposal only, nothing implemented

**Scope reviewed:** `src/bayesian_metamodeling/` (47 files, 6,115 lines), the 5 CI workflows,
the 20 shipped specs, and the tracked surrogate artifacts. Not reviewed: the KS model's C/C++
core (separate repo, separate review), notebook prose.

**The constraint this plan is written under:** two students are using this now, twelve
tutorials depend on current behaviour, and 20 specs are committed. So every item below is
tagged with what it breaks. Most of the valuable work breaks nothing.

---

## Bottom line

The codebase is in good shape structurally. Contracts are typed, layers are clean, there is
no `eval`, no `shell=True`, no SQL, no secrets, and someone has already thought about path
traversal — there is a `tests/test_security_hardening.py` with 16 tests.

The problem is narrower and more interesting than "it's insecure":

> **Three security guards exist that cannot do what their comments say they do, and one of
> them has a passing test asserting that it works.**

That is the same failure mode as the CI work recorded in `Status.md` — a check that doesn't
run, reporting success — except here it is a check that *runs* and cannot *hold*. A reader
sees a guard and a green test and reasonably concludes the surface is defended.

Nothing here is on fire. No shipped artifact is exploitable today, and the realistic
attacker for a lab metamodeling tool is "a colleague sends me a file", not a targeted
adversary. But the false-assurance items are worth fixing precisely because this codebase's
own stated values are about not letting checks lie.

---

## Part 0 — The decision everything else hangs on: what is a spec?

Before any security item can be judged, one question has to be answered, and it is a
**policy** question, not a technical one.

**How the tool works today.** A `ModelSpec` is a JSON file. One of its fields is:

```json
"artifact": { "type": "local", "entrypoint": ["python", "models/lck_activity/run.py"] }
```

`entrypoint` is a command. `bayesmm run spec.json` executes it as a subprocess, once per
DOE point. This is not a flaw — it is *the composition mechanism*. It is what lets the KS
model be written in C++ and the Lck model in Python and still be swept by the same tool
(`projects/tcr_signaling/CLAUDE.md` calls this "the composition seam is a process boundary,
not a Python API"). Any design that runs heterogeneous source models has this property.

**The consequence:** running someone else's spec is equivalent to running their code.
`bayesmm run untrusted.json` can do anything you can do.

So the question is:

> **Is a spec trusted input (like a `Makefile`) or untrusted input (like an email
> attachment)?**

You cannot have it both ways, and right now the code implies "untrusted" — there is a guard
in `adapters/python_cli.py:24` trying to keep entrypoints inside the repo — while actually
being "trusted", because the guard is bypassable in four ways (see **S2**). That middle
position is worse than either endpoint, because it teaches the reader that specs are
sandboxed.

**This is decision Q1 below.** My recommendation is **trusted input, stated loudly** — it
matches reality, it is honest, and pretending otherwise would mean building a sandbox this
project has no reason to build.

---

## Part 1 — Security findings

Severity is *practical* severity for this project (a lab tool, run locally, by people who
already trust each other), not CVSS.

### S1 — `torch.load(weights_only=False)`: the guard cannot work · **HIGH (design), LOW (exposure today)**

**Where:** `src/bayesian_metamodeling/surrogates/backends.py:904-919`

**What it is.** When you fit an `sbi_npe` surrogate (Tutorial 6's backend — a neural
posterior estimator), the trained object is a live Python object, not just numbers. To save
it, the code pickles it via `torch.save` and base64s it into the artifact JSON. To load it:

```python
obj = torch.load(buffer, map_location="cpu", weights_only=False)
if not hasattr(obj, "sample") or not hasattr(obj, "log_prob"):
    raise ValueError("... Artifact may be corrupted or tampered with.")
```

The comment above it reads: *"We validate the loaded object conforms to the expected
posterior interface to guard against loading arbitrary objects from tampered artifacts."*

**Why it cannot work.** `weights_only=False` means pickle. Pickle executes code *while
deserialising* — a crafted payload runs at `torch.load(...)`, on the line before the check.
By the time `hasattr` is evaluated, anything that was going to happen has happened. The
guard filters the *return value* of an operation whose danger is its *side effects*. It
would stop a corrupted artifact; it cannot stop a malicious one.

**The test makes it worse.** `tests/test_security_hardening.py:205`
(`test_rejects_object_without_posterior_interface`) passes, and reads as though the
deserialisation path is defended. It verifies the `hasattr` check, which is real — it just
isn't a security control.

**Actual exposure today — this is the reassuring part.** I checked every artifact tracked in
git:

| Artifact | Backend | Contains pickle? |
|---|---|---|
| `examples/coupled/artifacts/surrogate_A.artifact.json` | `pymc_gp` | no |
| `examples/coupled/artifacts/surrogate_B.artifact.json` | `pymc_gp` | no |
| `tutorials/artifacts/surrogate_C.artifact.json` | `pymc_gp` | no |
| `projects/tcr_signaling/artifacts/*.artifact.json` (4) | `pymc_gp` | no |

**All seven are `pymc_gp`**, which serialises as plain JSON arrays of floats — no pickle, no
risk. The dangerous path only fires on an `sbi_npe` artifact, and none is shipped. It
triggers when a user loads an sbi artifact **they did not produce** — realistically, "here's
my trained surrogate, try it" between two students, or a future decision to commit one.

**Options:**

- **(a) Make it safe.** Stop pickling. Save the density estimator's `state_dict()` (tensors
  only) plus the architecture config needed to rebuild it, and load with
  `weights_only=True`. Cost: real work in `_fit_sbi_npe`/`load_backend_model`, and **every
  existing `sbi_npe` artifact must be refitted**. Since none is committed, the blast radius
  is whatever is in students' local `tmp/`.
- **(b) Make it honest.** Keep pickle, delete the misleading comment and the guard's
  security framing, and add a loud docstring + `bayesmm` warning: *sbi artifacts are
  executable; only load ones you fitted yourself.* Optionally add a digest recorded at fit
  time and verified at load (stops accidental corruption and casual tampering, not a
  determined attacker, and **say so**).
- **(c) Both, staged** — (b) now, (a) when convenient.

**My recommendation: (c).** (b) is an hour and removes the false assurance immediately;
(a) is the correct end state but is the only item in this review that forces a refit.

---

### S2 — The entrypoint guard is bypassable four ways · **MEDIUM (false assurance), LOW (real risk)**

**Where:** `src/bayesian_metamodeling/adapters/python_cli.py:22-27`

```python
# Security: entrypoint is user-controlled by design (CLI-first tool where user
# controls the spec). Validate that path-like entrypoints don't traverse outside repo.
if len(command) > 1 and "/" in command[1]:
    ep_path = Path(command[1]).resolve()
    if not ep_path.is_relative_to(repo_root.resolve()):
        raise ValueError(f"Entrypoint path must be within repo root: {command[1]}")
```

**The four bypasses:**

1. **It only inspects `command[1]`.** `entrypoint: ["/bin/sh", "-c", "..."]` — element 0 is
   never checked, and element 2 is never checked.
2. **It only fires when `command[1]` contains `/`.** On Windows, `..\..\thing.py` contains
   none. (Note `spec/modelspec.py:202-223` validates `storage.root` against *both*
   separators, deliberately and with a comment explaining why — so the project already knows
   this. The knowledge just didn't reach here.)
3. **It's per-adapter.** `biomodels_sbml` has no equivalent check.
4. **The command is the point.** Even a fully-contained path runs arbitrary code, because
   running the model is the feature.

**Framing.** Bypass 4 is the real one: this guard cannot succeed at its stated goal, because
the goal contradicts the tool's purpose. It should either be deleted with a clear statement
of the trust model, or kept as a *typo-catcher* and relabelled as such — it does genuinely
catch "I pointed at the wrong directory".

**Options:** **(a)** delete it, document the trust model (pairs with Q1 = trusted);
**(b)** keep, relabel as a usability check, fix the Windows separator gap;
**(c)** make it real — allowlist of interpreters + resolve every path-like argument. Only
coherent if Q1 = untrusted, and it is a lot of work for a threat this project probably
doesn't have.

**My recommendation: (b).** Cheap, honest, keeps the accident-catching value.

---

### S3 — `model.name` reaches a path that gets `rmtree`'d · **MEDIUM**

**Where:** `src/bayesian_metamodeling/cli/main.py:216`, `:225`, `:277`

```python
run_label    = f"{spec.model.name}_{point_index + 1}"
temp_run_dir = (Path(spec.storage.root) / "_active" / run_token / run_label).resolve()
temp_run_dir.mkdir(parents=True, exist_ok=True)
...
finally:
    shutil.rmtree(temp_run_dir, ignore_errors=True)
```

`model.name` is validated only as `min_length=1` (`spec/modelspec.py:42`). It is
interpolated into a path, `.resolve()` collapses any `..`, the directory is created, and in
the `finally` block it is **recursively deleted**.

A name like `../../../../some/dir` produces an `rmtree` outside the store. The same pattern
exists for `biomodels_id`, which is unvalidated and used as
`cache_dir / f"{biomodels_id}.xml"` (`adapters/biomodels_sbml.py:35`).

**Why I rate this MEDIUM and not HIGH:** a hostile spec already has arbitrary code execution
via `entrypoint`, so this grants an attacker nothing new. The realistic failure is
**accidental** — a model named `lck/activity` or `topography (v2)` silently writing and
deleting somewhere unintended. `rmtree` in a `finally` is a bad place to discover that.

**Fix (small, breaks nothing):** validate `model.name` and `biomodels_id` with the same
character discipline already applied to `conda_env` (`spec/modelspec.py:75` uses
`^[a-zA-Z0-9][a-zA-Z0-9._-]*$`), or sanitise at the point of path construction. All 20
shipped specs already use plain names, so this is invisible to students.

---

### S4 — Provenance is recorded but never verified · **LOW–MEDIUM**

Artifacts carry `spec_digest` and `dataset_digest` (`storage/surrogate_store.py:67-68`), and
runs carry `spec_digest`/`artifact_digest` (`storage/run_store.py:87-88`). **Nothing ever
checks them.** They are written and never read back for comparison.

Related inconsistency: `show_registered_run` (`run_store.py:56-60`) *does* verify that a
registry entry points inside the project before reading it —
`find_latest_artifact_for_spec` (`surrogate_store.py:92-105`) does not.

Given `CLAUDE.md` rule 3 ("Full provenance"), the gap is between *recording* provenance and
*enforcing* it. Cheap fix: verify the digest on load and warn (not fail) on mismatch; add
the containment check to the surrogate path for symmetry.

---

### S5 — Unbounded, unvalidated network fetch · **LOW**

**Where:** `adapters/biomodels_sbml.py:69-99`

`source_url` comes from the spec, is used verbatim, any scheme or host, redirects followed,
and `response.content` is read with **no size limit** — a wrong URL can exhaust memory. The
good parts: `timeout=60`, `verify=True`, and a content-sniffing check that catches BioModels
returning HTML.

Cheap hardening: default-deny to `https://` + `ebi.ac.uk` unless an explicit override flag
is set, cap the response at a few MB, and stream rather than buffer.

---

### S6 — No `permissions:` block in any workflow · **LOW**

All 4 parent workflows (and the submodule's) run with the repository-default `GITHUB_TOKEN`
permissions. Standard hardening is one line per workflow:

```yaml
permissions:
  contents: read
```

`ci.yml` and `interface.yml` also carry `pull_request:` triggers, so a fork PR can run them.
This is the cheapest item in the review and breaks nothing.

---

### S7 — No dependency lockfile · **LOW (security), MEDIUM (reproducibility)**

`pyproject.toml` pins ranges (`pydantic>=2,<3`, `pymc>=5,<6`, …), not versions. For a
published scientific method, "which pymc produced this figure?" is answerable only from
`dependency_versions` recorded inside each artifact — which is actually a nice touch, but
after the fact. A lockfile or a `constraints.txt` for the tutorial environments would make
a student's run reproducible a year from now.

Deliberately flagged as a **judgement call, not a recommendation** — lockfiles add
maintenance, and four conda environments already exist.

---

## Part 2 — Design findings

### D1 — The sweep engine lives inside the CLI · **the most consequential design item**

`cli/main.py` (739 lines) contains not just argument parsing but the entire execution
engine: `_execute_design_point` (:205), `_run_serial` (:294), `_run_parallel_local` (:309),
`_run_mpi` (:342).

**Consequences:**

1. **There is no library API for running a sweep.** A student in a notebook must either
   shell out to `bayesmm run`, or import underscore-prefixed functions out of a CLI module.
   For a project whose tutorials are notebooks, that is backwards.
2. **These functions are untyped.** `def _run_serial(spec, points: ...)` — `spec` has no
   annotation, in four places. `CLAUDE.md` rule 8 is "Typed contracts first".
3. The layering documented in `TechSpec.md` (spec → design → adapter → runner → storage)
   has no home for orchestration, so it landed in the CLI by default.

**Proposal:** extract a `sweep/` (or `execution/`) module exposing something like
`run_sweep(spec, *, mode=...) -> SweepResult`. `cli/main.py` becomes argument parsing and
printing. **Breaks nothing** — pure move plus a new public entry point. This is the single
change that most improves the project for its actual users.

### D2 — `surrogates/backends.py` is 1,112 lines

It holds five model classes, both fitting paths, serialisation, base64/torch plumbing, two
SBI version-compatibility shims (`_NoOpSummaryWriter`, `_TrackerCompatWriter`), and version
lookup. Natural split: `backends/pymc_gp.py`, `backends/sbi_npe.py`, `backends/_payload.py`,
`backends/_compat.py`. Mechanical, breaks nothing if `__init__` re-exports.

### D3 — Storage paths are CWD-dependent module constants

```python
REGISTRY_PATH           = Path("tmp/run_registry.json")        # storage/run_store.py:21
SURROGATE_REGISTRY_PATH = Path("tmp/surrogate_registry.json")  # storage/surrogate_store.py:15
artifact_dir            = Path("tmp/surrogate_artifacts") / artifact_id   # :49
```

Two problems: (1) run `bayesmm` from a different directory and you silently get a *different*
registry — a student who runs from `tutorials/` will wonder where their runs went;
(2) sweeps honour the configurable `spec.storage.root`, but **surrogate artifacts ignore it**
and hardcode `tmp/`. Same concept, two rules.

### D4 — `design.sobol` is the one untyped spec object, and it hides a silent-ignore

Everything in `spec/` is Pydantic with `extra="forbid"` — except:

```python
sobol: dict[str, Any] | None = None   # spec/modelspec.py:150
```

The planner reads only `n_points`, `scramble`, `seed` (`designs/planner.py:56-62`). Both
research specs contain a **`ranges`** key:

```json
"sobol": { "n_points": 64, "ranges": { "contact_radius": [0.5, 2.0], ... } }
```

**`ranges` is never read.** The actual bounds come from `io_schema.inputs[].support`. I
checked all 8 variables across both specs — **they currently agree**, so no sweep has been
wrong. But nothing enforces agreement: edit `ranges` (the obvious-looking place) and the
sampling silently does not change. That is a `Status.md`-grade trap.

Fix: make `sobol` a typed model with `extra="forbid"`, and either delete `ranges` from the
specs or make it authoritative. Note this **would reject the two research specs as written**
— see the compatibility table.

### D5 — DOE rigor, in a project that teaches DOE

Verified empirically against the installed scipy:

| Issue | Evidence | Consequence |
|---|---|---|
| Sobol `n` not a power of 2 | `tutorials/specs/model.toy.sobol.json` uses `n_points: 9`; scipy emits *"The balance properties of Sobol' points require n to be a power of 2"* | Tutorial 4 teaches Sobol using a configuration scipy warns about |
| `scramble` defaults to `False` | `planner.py:60` — **scipy's own default is `True`** | Unscrambled, the first point is exactly `[0,0]` → the corner of the box, i.e. every variable at its minimum |
| Grid values never checked against `support` | `plan_grid_points` never consults `io_schema` | A grid can silently sample outside the declared domain |
| Grid keys never checked against input names | same | A typo'd variable fails later, in the adapter, as "Missing input variable" |

The research specs use `n_points: 64` (a power of 2) and the tutorial spec sets
`scramble: true` explicitly, so **no committed result is affected**. The exposure is to the
next person who writes a spec, which for this project is a student.

### D6 — Dead code (rule 7 says delete it)

- `_fit_linear` (`backends.py:414`) — **no caller anywhere in `src/`**; only 2 test
  references keep it alive.
- `persist_sweep(..., sweep_id=None)` (`run_store.py:122`) — **no caller passes it**.

### D7 — Artifacts are read as raw dicts

Specs get Pydantic validation with `extra="forbid"`; artifacts get `json.loads` and
`.get()` (`meta/builder.py:19-31`, `surrogate_store.py:97`). A truncated or hand-edited
artifact fails deep in numpy instead of at the boundary with a clear message. An
`ArtifactModel` would make the read path as typed as the write path.

### D8 — v1/v2 payload duality

`LinearGaussianModel` + `PymcGPSurrogateModel` + `SbiNPESurrogateModel` exist solely to load
legacy v1 artifacts (`backends.py:1050`, `:1080`). Worth asking whether any v1 artifact
still exists; if not, this is ~80 lines and three classes of removable complexity.

---

## Part 3 — Proposed plan, tiered by risk to students

### Tier 0 — invisible to students, no behaviour change (~half a day)

| # | Item | Breaks |
|---|---|---|
| S6 | Add `permissions: contents: read` to 5 workflows | nothing |
| S3 | Validate `model.name` + `biomodels_id` charset | nothing (all 20 specs pass) |
| S1b | Delete the false comment/framing on the torch guard; add an honest warning | nothing |
| S2b | Relabel the entrypoint guard as a typo-catcher; fix the Windows separator gap | nothing |
| D6 | Delete `_fit_linear` and the unused `sweep_id` parameter | nothing |
| S4 | Add the containment check to `find_latest_artifact_for_spec` | nothing |

### Tier 1 — internal refactors, public behaviour unchanged (~2-3 days)

| # | Item | Breaks |
|---|---|---|
| D1 | Extract the sweep engine out of `cli/main.py`; add typed `run_sweep(...)` | nothing; **adds** the API notebooks want |
| D2 | Split `backends.py` into a package | nothing if re-exported |
| D3 | Make store roots explicit and configurable; stop hardcoding `tmp/` | changes where artifacts land → **needs a migration note** |
| D7 | Typed artifact model on the read path | nothing |
| S4 | Verify digests on load, warn on mismatch | nothing |

### Tier 2 — needs your decision, has visible consequences

| # | Item | Breaks |
|---|---|---|
| D4 | Type `design.sobol` with `extra="forbid"` | **rejects the 2 research specs** until `ranges` is removed or implemented |
| D5 | Sobol: warn on non-power-of-2, flip `scramble` default to `True` | **changes sampled points** → any re-run produces different numbers than the current tutorials show |
| D5 | Validate grid values against `support` | may reject existing specs — needs a check first |
| S1a | Re-do sbi serialisation without pickle | **existing `sbi_npe` artifacts must be refitted** |
| S7 | Lockfile / constraints for tutorial envs | new maintenance burden |
| D8 | Drop v1 artifact support | breaks v1 artifacts if any survive |

### Explicitly *not* proposed

- Sandboxing model execution. Contradicts the tool's purpose (see Part 0).
- Renaming `pymc_gp`. Already considered and rejected in `backends.py`'s docstring for good
  reasons (breaks every spec and artifact); the docs carry the correction instead.
- Rewriting the adapter/runner protocols. They are clean and correctly factored.
- Touching the KS model's native code. Separate repo, separate review.

---

## Part 4 — Open decisions (details in the questions I'll ask alongside this doc)

- **Q1. Trust model.** Is a spec trusted input? Gates S1, S2, and how loudly the docs speak.
- **Q2. The sbi pickle.** Fix properly (refit required), make honest (docs + digest), or both
  staged?
- **Q3. Appetite.** Tier 0 only / Tier 0+1 / all three, given two students mid-course.
- **Q4. DOE defaults.** Leave the numbers alone and only document, or fix the defaults and
  accept that tutorial outputs shift?

---

## Appendix — what I checked and found clean

So the plan isn't mistaken for a complete inventory of risk:

- **No `eval`, `exec`, or `os.system`** anywhere in `src/`.
- **No `shell=True`** — `subprocess.run` is always called with a list.
- **No SQL, no secrets, no credentials** in the codebase or workflows.
- **Coupling transforms dispatch on string comparison** (`compiler.py:35`,
  `sampling.py:42`), not dynamic lookup — a hostile `kind` value cannot execute anything.
- **`storage.root` validation is genuinely good** — rejects absolute and traversal paths
  under both POSIX and Windows conventions, with a comment explaining each case.
- **`conda_env` is regex-validated** before reaching `conda run`.
- **`_resolve_dataset_root`** blocks `..` (absolute paths are allowed deliberately).
- **`requests.get`** uses `timeout=` and `verify=True`.
- **Output-mapping paths are containment-checked** against the run directory
  (`python_cli.py:52-54`).
- **CI has no `pull_request_target` or `workflow_run`** — the two triggers that make fork
  PRs dangerous.
- **Actions are current** (`checkout@v7`, `setup-python@v7`, bumped today).
