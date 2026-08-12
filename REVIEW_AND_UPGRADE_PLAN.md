# Code Design & Security Review — Upgrade Plan

**Date:** 2026-08-12 · **Branch:** `feature/design-security-review` · **Status:** decisions taken, nothing implemented

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

## Decisions taken (2026-08-12)

| # | Question | Decision |
|---|---|---|
| Q1 | Is a spec trusted input? | **Trusted, stated loudly — plus show the command before running.** Document the boundary; make `bayesmm run` print the exact command and confirm when the entrypoint resolves outside the repo. Visibility, not containment, and labelled as such. |
| Q2 | The sbi pickle | **Fix properly now.** Replace pickle with `state_dict` + architecture config, load with `weights_only=True`. Existing `sbi_npe` artifacts must be refitted (none are in git). |
| Q3 | Appetite | **All three tiers.** |
| Q4 | DOE defaults | **Document + warn; do not change defaults.** Warn on non-power-of-2 Sobol `n`, validate grid values against `support`, teach both in Tutorial 4. `scramble` stays `False` so no existing numbers move. |
| Q5 | Supply chain | **Two-track, security-only alerts.** `environment.yml` untouched as the onboarding path; add generated `conda-lock` files for CI and opt-in exact reproduction; Dependabot in **security-only** mode; CI check that the lock matches the manifest. |

**Why Q1 and Q5 are separate axes.** The concern that prompted Q1 — "a package I imported put a
vulnerability in everything" — is a *dependency* compromise (event-stream, xz-utils, PyPI
typosquatting). That is Q5, not Q1. Measured on the default environment:

| | count |
|---|---|
| Packages declared by this project | 7 |
| Packages installed | 182 |
| Arrived as someone else's dependency | **175** |
| Pinned by lockfile or hash | **0** |

That is where the horror-story risk lives, and Q5 addresses it. Whether a *spec* is trusted is
a different question with a different answer, and conflating them in one document was a flaw
in the first draft of this review.

**Why "trusted spec" is not a security hole.** Every tool in this class executes commands named
in a config file: `make`, `npm run`, `docker build`, and — closest to what `bayesmm` is —
Snakemake, Nextflow and CWL. None of them sandbox. "Don't run a stranger's Makefile" is a
well-understood rule; "don't run a stranger's spec" is the same rule. The hole is not the trust
boundary, it is *claiming a sandbox that isn't there*, which is the current state (**S2**).

**Alert fatigue is the real UX risk in Q5, and it is avoidable.** Dependabot in version-update
mode on a 182-package tree means dozens of PRs a month, everyone stops reading them, and the
channel becomes worse than nothing. Security-only mode fires on published CVEs affecting the
pinned set — realistically a handful a year, each worth reading. A lockfile itself does **not**
slow onboarding: conda's slowest step is dependency solving, and installing from a lock skips
it entirely.

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

**Decided (Q1): trusted input, stated loudly — plus visibility.** Documenting the boundary
matches reality; pretending otherwise would mean building a sandbox this project has no reason
to build. On top of that, `bayesmm run` will show the command it is about to execute and
confirm when the entrypoint resolves outside the repo (**S2d**) — not a sandbox, and never to
be described as one, but it makes the moment of trust visible rather than implicit.

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

> **DECIDED: (a) — fix it properly now.** The correct end state, chosen deliberately over the
> staged route. Consequence to plan for: **every existing `sbi_npe` artifact must be refitted.**
> Nothing in git breaks (all tracked artifacts are `pymc_gp`), but any artifact in a student's
> local `tmp/` becomes unloadable, and Tutorial 6 must be re-run once. See *Student
> communication* in Part 4 — this is the item that needs a heads-up before it lands.

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

> **DECIDED: (b) + a new visibility feature.** Relabel the guard as a usability check (it does
> genuinely catch "I pointed at the wrong directory"), fix the Windows separator gap, and
> document the trust boundary in `README.md` and `CLAUDE.md`.
>
> **Additionally — new work item S2d, "show the command":** `bayesmm run` prints the exact
> command it is about to execute, and asks for confirmation when the entrypoint resolves
> outside the repo root. Roughly 30 lines.
>
> This is deliberately **not** containment and must never be described as such. It is the
> `bayesmm` equivalent of reading a Makefile before typing `make` — it converts "I ran it
> without realising what it does" into a deliberate act. Design notes for whoever implements
> it: it must be suppressible for non-interactive use (CI, sweeps, notebooks) via a flag or
> env var, it must not fire once per DOE point (once per sweep), and the suppression must be
> visible in the output so a silenced prompt is not mistaken for no prompt.

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

> **DECIDED: two-track, security-only alerts.** Four parts:
>
> 1. **`environment.yml` is untouched.** It remains the documented onboarding path — flexible,
>    solver-resolved, identical experience for a new student. This is non-negotiable: onboarding
>    must not regress.
> 2. **Generated `conda-lock` files** for macOS / Linux / Windows, used by CI and offered to
>    anyone who needs exact reproduction ("reproduce the 2024 figures"). Installing from a lock
>    is *faster* than solving, so this is not a tax on anyone who opts in.
> 3. **Dependabot in security-only mode.** Published CVEs against the pinned set only — a
>    handful a year. Explicitly **not** version-update mode: dozens of PRs a month on a
>    182-package tree would train everyone to ignore the channel, which is worse than having no
>    channel at all.
> 4. **A CI check that the lock matches the manifest**, so a dependency change with a stale lock
>    fails loudly instead of silently drifting. This is the same guard-against-silent-no-ops
>    discipline as the junit floor and the sanctioned-skip audit.
>
> Not chosen: `--require-hashes`. It is the only option that actually stops a tampered PyPI
> artifact, but with conda + torch across four environments the regeneration friction is high
> enough that it would rot. Revisit if the project is ever published for outside use.

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

> **DECIDED: document and warn; do not change defaults.**
>
> - **Do:** emit a warning when Sobol `n_points` is not a power of 2, explaining what balance
>   property is lost. Validate grid values against `io_schema` `support`, and cross-check grid
>   keys against declared input names so a typo fails at validation rather than mid-sweep.
> - **Do:** teach both points in Tutorial 4. The unscrambled-corner behaviour is unusually good
>   teaching material — "your first design point sits at every variable's minimum" is a concrete
>   way to explain what scrambling is *for*, and Tutorial 4 already exists to teach exactly this
>   choice.
> - **Do not:** flip the `scramble` default to `True`. It would be the methodologically tidier
>   default and would match scipy, but it changes which points get sampled, so every re-run
>   would produce numbers that differ from what the current tutorials show. Not worth it while
>   students are mid-course. Note in the docs that the default *differs from scipy's*, so a
>   reader who knows scipy is not surprised.

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

## Part 3 — Execution plan

All three tiers are approved, so the useful ordering is no longer "by risk appetite" but **by
blast radius and dependency order**. Four stages, each independently committable and each
leaving the repo green. Stage 1 can land today; stage 4 is the only one students must be told
about in advance.

### Stage 1 — Honest guards and cheap hardening · breaks nothing · ~half a day

Do this first because it removes the false assurance, which is the whole reason this review
exists. Every item is invisible to students.

| # | Item |
|---|---|
| S6 | `permissions: contents: read` in all 5 workflows |
| S3 | Validate `model.name` and `biomodels_id` charset (reuse the `conda_env` regex at `modelspec.py:75`) — stops an unvalidated name reaching an `rmtree`'d path |
| S1b | Delete the misleading comment on the torch guard; keep the `hasattr` check but relabel it as the corruption check it actually is |
| S2b | Relabel the entrypoint guard as a usability check; fix the Windows separator gap |
| S4a | Add the containment check to `find_latest_artifact_for_spec`, matching `show_registered_run` |
| D6 | Delete `_fit_linear` and the unused `sweep_id` parameter |
| — | Document the trust boundary in `README.md` + `CLAUDE.md` (Q1) |

**Test discipline:** `test_security_hardening.py` needs its
`test_rejects_object_without_posterior_interface` renamed and re-documented — it currently
reads as a security test for a control that isn't one. That rename is part of the fix, not
cosmetic.

### Stage 2 — Structure · breaks nothing student-visible · ~2–3 days

| # | Item | Note |
|---|---|---|
| D1 | Extract the sweep engine from `cli/main.py` into a typed `run_sweep(...)` API | The highest-value item in the review. Do it before D3, since it is where store paths are threaded through |
| D2 | Split `backends.py` (1,112 lines) into a package, re-exporting from `__init__` | Do it before S1a — the pickle fix lands in a much smaller file afterwards |
| D7 | Typed artifact model on the read path | |
| S4b | Verify digests on load; **warn**, don't fail | |
| S2d | "Show the command" before running (Q1) | Needs the non-interactive suppression path — see S2 |

### Stage 3 — DOE and spec validation · may reject existing specs · ~1 day

| # | Item | Consequence |
|---|---|---|
| D4 | Type `design.sobol`, `extra="forbid"` | **Rejects both research specs** until the unread `ranges` key is removed or made authoritative. Decide which — my read is that `ranges` is the more natural place for a spec author to look, so making it authoritative and deriving `support` from it may be the better design |
| D5 | Warn on non-power-of-2 Sobol `n`; validate grid values against `support`; cross-check grid keys against input names | Check all 20 shipped specs pass *before* making it an error |
| D5 | Teach both DOE points in Tutorial 4 | Prose only |

### Stage 4 — The disruptive one · tell the students first · ~2 days

| # | Item | Consequence |
|---|---|---|
| S1a | Re-do sbi serialisation: `state_dict` + config, `weights_only=True` | **Existing `sbi_npe` artifacts stop loading.** Nothing in git breaks; local `tmp/` artifacts do |
| D3 | Explicit, configurable store roots; stop hardcoding `tmp/` | Artifacts move. Needs a migration note, and ideally a one-shot `bayesmm migrate` or a clear error pointing at the old location |
| D8 | Drop v1 artifact support (~80 lines, 3 classes) | Only after confirming no v1 artifact survives — check both students' checkouts first |
| S7 | Two-track locks + security-only Dependabot + lock-vs-manifest CI check | Onboarding path unchanged |

**Ordering constraint:** S1a and D3 both invalidate stored artifacts. Landing them in the same
stage means students refit **once**, not twice. Do not split them across releases.

### Explicitly *not* proposed

- Sandboxing model execution. Contradicts the tool's purpose (see Part 0).
- Renaming `pymc_gp`. Already considered and rejected in `backends.py`'s docstring for good
  reasons (breaks every spec and artifact); the docs carry the correction instead.
- Rewriting the adapter/runner protocols. They are clean and correctly factored.
- Touching the KS model's native code. Separate repo, separate review.

---

## Part 4 — Consequences to manage

### Student communication

Exactly one stage requires warning people in advance. Everything before it is invisible.

**Before stage 4 lands**, both students need to know:

1. **Any `sbi_npe` surrogate they have fitted locally will stop loading**, and must be refitted
   by re-running Tutorial 6 (or `bayesmm surrogate fit`). This costs minutes, not hours. Nothing
   they have committed is affected — all seven artifacts in git are `pymc_gp`.
2. **Stored artifacts may move** when store roots become explicit (D3). The failure mode to
   avoid is a silent "no artifact found"; the error must name the old location.

A good forcing function: land stage 4 at a natural break in whatever they are working through,
not mid-tutorial.

### Two decisions deferred to implementation time

These do not block the plan, but should not be made silently by whoever writes the code:

1. **D4 — what happens to `ranges`?** Both research specs declare `design.sobol.ranges`, which
   the planner never reads; bounds come from `io_schema.inputs[].support`. They agree today.
   Either delete `ranges` from the two specs, or make it authoritative and derive `support`
   from it. The second is arguably the better design — `ranges` is where a spec author would
   naturally look — but it is a larger change. **Do not "fix" this by making the validator
   tolerate the unread key**; that preserves exactly the silent-divergence trap the item exists
   to close.
2. **D8 — do any v1 artifacts survive?** Check both students' checkouts before deleting the v1
   loading path, not after.

### What this plan does not cover

- The KS model's C/C++ core (`projects/tcr_signaling/models/kinetic_segregation/`) — separate
  repository, separate review, and it has its own reference-value and portability test
  discipline already.
- Notebook prose quality, beyond the DOE teaching points in D5.
- Any framework capability work. This is a hardening and structure pass only.

### Status tracking

`Status.md` gets an entry per stage as it lands, not now — the decisions above are a plan, and
recording them as decisions in `Status.md` before any code moves would misrepresent the state
of the repository. This document is the record until then.

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
