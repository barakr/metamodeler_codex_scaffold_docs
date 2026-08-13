# Status: Metamodeling Automation Framework

## KNOWN-GOOD CHECKPOINT — `checkpoint/2026-08-13-review-verified` (a6f9d7a)

**If later work goes wrong, this is the commit to return to.** It is an annotated git tag on
branch `feature/design-security-review`, chosen because every signal was green on it at once —
which is not true of most commits, and is the whole point of marking it.

| Verified on this commit | |
|---|---|
| `CI` (3 OSes) | success |
| `Interface CI` | success |
| `Deep CI` — main / pymc / sbi / full | success |
| `make fast` | green |
| `pytest -m slow tests/test_tutorial_integration.py` | **12/12** |
| `MM_STRICT_ARTIFACTS=1` on fast **and** slow suites | green |

That last row is worth its own sentence: it proves the repository never depends on the legacy
pickled-artifact path, rather than assuming it.

**To come back:**

```bash
git checkout checkpoint/2026-08-13-review-verified          # look around
git reset --hard checkpoint/2026-08-13-review-verified      # on a branch you own
git tag -n99 -l 'checkpoint/*'                              # read the full tag message
```

**Two user-visible behaviour changes are already baked in at this point**, so returning here
does *not* undo them: stricter spec validation (a grid naming an undeclared variable, or
straying outside its declared `support`, is rejected at `validate` instead of failing
mid-sweep), and the v3 sbi artifact format (older artifacts still load, with a warning). To get
behind those, go back to `develop` at `faa39b9`.

Work after this point — `S7` locks, `D8` v1 loader removal, `D2` backends split, `D3` store
roots — is recorded in `REVIEW_AND_UPGRADE_PLAN.md` and lands in commits above this tag.


## sbi artifacts no longer store a pickled object (2026-08-13)

`S1a`, the security headline of the review, with the backward compatibility the user asked
for. All suites green, including a strict-mode run.

**The problem.** `sbi_npe` surrogates were saved by pickling the live posterior and loaded
with `torch.load(weights_only=False)`. Pickle executes code *while deserialising*, so opening
someone's surrogate was equivalent to running their program. The `hasattr(obj, "sample")`
check beside it could not help — it inspected the return value of an operation whose danger is
its side effects.

**v3 stores weights.** The density estimator's `state_dict` (tensors only), plus the recipe to
rebuild the architecture: the estimator name and the two dimensions. Loading uses
`weights_only=True`, so `torch.load` refuses anything that is not a plain tensor container.
A test pins that directly by feeding a pickled object into the v3 slot and requiring a refusal
— the security property is *tested*, not inferred from the format.

**Backward compatible, deliberately.** v2 artifacts still load, so nothing fitted before this
breaks. But never silently: they emit `LegacyPickleArtifactWarning` naming the risk and the
fix, and `MM_STRICT_ARTIFACTS=1` turns it into an error. That is what lets CI prove the
repository itself never needs the unsafe path — verified by running both the fast and slow
suites with the flag set.

**The prior question, settled by measurement rather than assumption.** `_fit_sbi_npe` passes
no prior, so sbi derives an `ImproperEmpirical` one and the rebuild needs *something*. I had
assumed recording it would shift fitted results, which would have been a real trade-off
against the "don't move the numbers" decision taken on DOE. Measured on sbi 0.26.1:

- the derived prior is improper and flat — `log_prob` is `0.0` even at theta = 1e6;
- `log_prob` and `sample` are **bit-identical** when it is rebuilt from wildly different
  moments, or from an arbitrary two-point sample;
- only its *dimension* matters, and a degenerate zero-variance placeholder is rejected by
  sbi's own transform check.

So the artifact carries no training data, and nothing moves. A full fit → save → load
round-trip reproduces `log_prob` and `sample` exactly (`np.array_equal`, not `allclose`),
for both single-output and multi-output `diagonal` fits.

**Tests updated rather than weakened (rule 7).** Four files asserted the v2 payload shape;
they now assert v3, and the two corruption-check tests additionally assert the new
deprecation warning — so the announcement cannot quietly disappear.

## A contaminated local tutorial run now fails instead of passing (2026-08-13)

The process fix for how this branch got pushed red. Chosen over "write it down" because the
problem was never that the rule was unknown — it was that the local check gave a **confident
wrong answer**.

**What it does.** `tests/test_tutorial_integration.py` refuses to run when `tmp/tutorials/`
already contains data from an earlier session, and **fails** rather than skips. The message
names what it found, how to clear it, and the override
(`MM_ALLOW_DIRTY_TUTORIAL_STORE=1`) for anyone who knowingly wants a weaker result. CI runs on
a clean checkout and never needs it.

**Why this and not a hook.** A pre-push hook running the slow suite would catch the *incomplete*
half and add minutes to every validation push. It would not touch the half that actually cost the
time here: `Tutorial_5` **passed locally while failing in CI**, because this machine had a store
`Tutorial_1` should have produced and hadn't. That is the repo's own defect class — a check that
cannot fail — and it is fixed by making the contaminated case impossible to mistake for a good
one. The gate rule is documented in `CLAUDE.md` as well, so both halves are covered.

**A bug in the guard, caught while writing it.** The first version checked per-test. That is
self-defeating: `Tutorial_1` *creates* the directory being guarded, so tutorials 2-12 would have
failed in every CI run, on a clean checkout. It is now an import-time snapshot — the question is
only ever "was the store dirty when this session started". `tests/test_tutorial_store_hygiene.py`
pins that, and the fail-not-skip property, in the **fast** suite: a guard nobody exercises is the
next thing to rot. It also caught a second bug of mine, a `relative_to` that raises when the
store sits outside the repo root.

Verified both directions: the guard fires against this machine's real store, and the full
tutorial suite still passes 12/12 with the override set.

## Tutorials 3 and 4 rewritten; all twelve green locally (2026-08-13)

Completes the tutorial repair. `pytest -m slow tests/test_tutorial_integration.py` passes
12/12 — the gate that should have run before the first push.

**T4** taught that grid levels are never checked against `support`. Its demo built levels at
-50 and 99 against `[0, 2]` and concluded "nothing checks it, at plan time or at run time".
Now it shows three things instead of one: the rogue grid is rejected at `validate`; the *same*
grid with `support` removed validates and plans all nine points, because the check can only
compare against a bound you declared; and sobol still refuses outright without support. The
closing text separates the **syntactic** guarantee (your design is inside the numbers you
wrote) from the **scientific** one (those numbers are the regime your model is valid in).

**T3** was the large one — its thesis was "validation is per-section, nothing spans two
sections". That is now false in exactly one place, so the notebook teaches the boundary rather
than the absence: *one* root-level rule (`check_design_against_io_schema`) ties `design` to
`io_schema`, and everything touching `adapter` is still unenforced.

Step 5 moved the typo to where silence still lives — `adapter.input_mapping[0].var` — and the
resulting lesson is better than the one it replaces:

| | old break (`design.grid` rename) | new break (`adapter` rename) |
|---|---|---|
| validate | passed | passes |
| plan | passed, printing `alpha` — reading it saved you | passes, printing `a`/`b` — **reading it cannot save you**, the design is correct |
| run | `KeyError: 'a'` from `run_store.py` after the sweep | all 9 points fail with `Missing input variable 'alpha'` |
| data | **lost entirely**, 0 files | **kept**, 9 failed rows + the message in `sweep_logs.jsonl` |

So the habit T3 teaches moved with the bug: "read `plan`'s keys" is now done for you by the
validator, and what catches the surviving break is "when a run reports failures, read
`sweep_logs.jsonl` before re-running". Step 6 became "`support` is a claim, **and now also a
fence**", keeping the scientific half that no checker can ever hold.

**Two guards fired on me while doing this, both correctly.**

1. `EXPECTED_DIAGNOSTIC_MARKERS` — the harness scans notebook output for failure markers, and
   the new Step 5 legitimately prints `Run complete with failures` / `0 successful runs`. The
   old break never printed a summary because it died before writing one. Both markers are now
   registered, with the reason.
2. My own new assertion `n_mismatch_sweeps == 1` failed on the second local run, because that
   store accumulates. Relaxed to `>= 1` with the reasoning inline — the claim is "the sweep
   survives", and the *content* is pinned separately. An exact count would have passed on a
   fresh checkout and failed for any student who ran the notebook twice: the same
   stale-state trap that made my earlier local T5 run misleadingly green.

**Lesson carried forward:** for changes touching spec validation, `make fast` is not a gate —
only the slow suite executes notebooks, and only a clean checkout is honest.

## Deep CI went red on the branch — the tutorials taught the gaps I closed (2026-08-12)

Stages 1-3 are green on `make fast` and red on Deep CI. The cause is the inverse of a bug, and
it is worth recording carefully.

**Four tutorials deliberately DEMONSTRATE the validation gaps stage 3 closed.** Tutorial 1 said
outright: *"There is no cross-block validator in `ModelSpec` -- every rule lives inside one
sub-block"*, then built a spec with an undeclared grid key to prove it validated. Tutorial 3's
entire thesis is *"validation is per-section"*; it has a Step 5 titled **"A break the validator
does not catch"**. Those breaks are now caught, so the demonstrations raise.

**Tutorial 3 had already built the tripwire for this exact day.** Its self-check reads:

> `"{label} now FAILS validation. Good news about the framework, bad news about this notebook:`
> `Steps 5-6 and the 'Why this matters' cell..."`

Whoever wrote that anticipated the framework outgrowing the lesson and left instructions. It
worked exactly as intended.

**Two failure modes, and only one is visible.** A 12-agent audit of all twelve notebooks (saved
as `TUTORIAL_IMPACT_MAP.md`) found 40 affected cells, of which only 3 *raise*. The other 37
still run and now **teach something false** -- prose asserting a limitation that no longer
exists. Nothing will ever fail to report those, which is why the audit covered all twelve
notebooks rather than the four that went red. Eight notebooks are genuinely unaffected.

**Tutorial 5's failure is a cascade, not a break.** It has zero static findings. Its surrogate
reads `tmp/tutorials/toy_store`, which Tutorial 1 *writes*; T1 crashing left that store absent in
a fresh checkout, so T5 fitted on inadequate data and its "parameter uncertainty grows away from
the data" assertion failed.

**The process failure is mine, and it is the interesting one.** I ran `make fast` and called the
branch stable. `make fast` cannot execute notebooks -- only the slow suite does. Worse, when I
did run Tutorial 5 locally it **passed**, because `tmp/tutorials/toy_store` already existed from
earlier runs. So the local check was not merely incomplete, it was *actively misleading*: stale
shared state made a broken tutorial look fine. A clean checkout is the only honest run, which is
what Deep CI gives. For any change touching spec validation, `make slow` belongs in the gate.

**State:** Tutorial 1 rewritten and passing. The new lesson is better than the one it replaces --
of the three cross-block breaks T1 listed, two are now caught and one (`adapter.input_mapping`
naming an undeclared variable) still is not, so the notebook now teaches the *boundary* of the
validator's guarantees using a live example rather than asserting it has none. Tutorials 3, 4
and 2 remain; the map has cell-level findings and suggested fixes for each.

## Security review, stage 3: the design and the I/O schema now have to agree (2026-08-12)

`D4` + `D5`. All 11 shipped ModelSpecs still validate unchanged, and no sampled point moves.

**`design.sobol` was the one untyped object in the spec tree** — `dict[str, Any]`, read with
three `.get()` calls. Everything else in `spec/` is Pydantic with `extra="forbid"`. It is now
`SobolDesignSpec`.

The clearest evidence of what that cost: `tests/test_spec_edge_cases.py::test_design_sobol_valid`
asserted that `sobol={"n": 16}` was **valid**. `n` is not a key the planner reads. The test was
encoding the bug. It now asserts the opposite, with the history in its docstring.

**The `ranges` trap, resolved differently from what the plan proposed.** Both research specs
carry `design.sobol.ranges`; the planner takes bounds from `io_schema.inputs[].support` and has
never read `ranges`. The plan offered "delete it from the specs" or "make it authoritative".
Both are wrong here: those specs live in **`projects/tcr_signaling`, a separate repository**, so
forbidding the key would redden another repo's specs from this one, and honouring it would leave
two sources of truth for one number.

Instead, `ranges` is accepted and **cross-checked against `support`**. Agreement is now
enforced; divergence fails at validation with a message saying which one the planner actually
samples. Nothing needed to change in the submodule, the trap is closed, and a spec author who
edits the natural-looking place is told rather than ignored.

**Also connected, for the first time:** grid keys must name declared inputs (previously a typo
surfaced mid-sweep as "Missing input variable", once per point), and grid values must lie inside
the declared support (previously a spec could sample outside its own stated domain in silence).

**Sobol balance.** `plan_points` now warns when `n_points` is not a power of 2 — the property
Sobol is chosen for — and names the neighbouring powers. Tutorial 4's spec uses `n_points: 9`,
so the tutorial that teaches DOE was demonstrating the case scipy itself warns about. scipy's
own warning is suppressed by exact message, since ours states the same fact with the fix
attached; any other scipy warning still gets through. That also keeps planning usable under
`-W error`, which this project's `pytest.ini` sets.

**`scramble` still defaults to `False`** (Q4): flipping it to match scipy would change which
points get sampled and therefore every number the tutorials show. The divergence from scipy's
default is documented instead, and a test pins the consequence — unscrambled, design point 1 sits
at every variable's *minimum*, the corner of the box. That is good teaching material rather than
a defect.

## Security review, stage 2b: provenance that is actually checked (2026-08-12)

`D7` + `S4b`. Artifacts have always recorded `spec_digest` and `dataset_digest`, and nothing
ever read them back. Recording provenance without comparing it is book-keeping, not
provenance (rule 3).

**Now:** `storage/artifact.py` holds a typed `SurrogateArtifact` read model, and
`_load_and_validate_artifact` compares the recorded spec digest against the current spec.
`digest_surrogate_spec` is public so fit and load compute it *the one way it is defined* — if
each rolled its own they would eventually disagree, and a check that cries wolf is a check
people learn to ignore.

**Drift warns; it does not refuse.** Editing a spec and re-evaluating before re-fitting is an
ordinary mid-workflow state, and refusing to load would make edit-and-retry unusable. But it
cannot be silent, or a number gets attributed to a model that never produced it. The warning
names the fix (`bayesmm surrogate fit`), and a test asserts it does.

**`extra="allow"` on the artifact model, unlike every spec model.** Artifacts are *data at
rest* written by older versions of this package. Forbidding unknown keys would make every
field ever added a breaking change for existing stores — the opposite of what a provenance
record is for. Missing *required* keys still fail loudly, naming the file, instead of failing
several frames deep inside numpy.

## Security review, stage 2a: the sweep engine is a library, not a CLI internal (2026-08-12)

`D1` from `REVIEW_AND_UPGRADE_PLAN.md`, the highest-value item in the review. No behaviour
changes; `bayesmm run` prints exactly what it printed before.

**The problem.** `_execute_design_point`, `_run_serial`, `_run_parallel_local` and `_run_mpi`
lived inside `cli/main.py`. The only supported way to run a sweep was therefore to invoke the
CLI — so a student wanting to sweep from a notebook cell had to shell out to `bayesmm run`, or
import underscore-prefixed functions out of a CLI module and hope they kept working. For a
project whose tutorials *are* notebooks, that is backwards. `TechSpec.md` describes
spec → design → adapter → runner → storage and has no home for *orchestration*, which is why
it landed in the CLI by default.

**Now:** `bayesian_metamodeling/execution/` is that home.

```python
from bayesian_metamodeling.execution import run_sweep
outcome = run_sweep(spec)                      # silent; returns per-point results
outcome = run_sweep(spec, on_progress=print)   # or narrate
outcome, stored = run_sweep_to_store(spec, spec_payload=payload)   # run and persist
```

`cli/main.py` drops 739 → 622 lines and is now argument parsing and printing.

**Three deliberate changes in the move**, everything else byte-identical:

1. **Typed.** All four functions took a bare, unannotated `spec`; they take `ModelSpec` now
   (rule 8).
2. **Printing became a callback.** A library that prints to stdout cannot be used by a
   notebook rendering its own progress, and cannot be tested without capturing output.
   `on_progress` defaults to silent; the CLI passes `print`. Pinned by a test asserting
   `run_sweep` emits nothing by default.
3. **MPI rank handling became explicit.** `SweepOutcome.is_writer` is `False` on non-root
   ranks instead of that being implied by an early `return [], 0`. Exit-code broadcasting
   stayed in the CLI, because an exit code is a command-line concern — the library returns
   results.

**What did not change, on purpose.** The per-point payload stays a `dict[str, Any]` rather
than becoming a dataclass: it is `persist_sweep`'s input contract and the `sweep_logs.jsonl`
schema, so promoting it would either duplicate that schema or force a storage change. Neither
belongs in a refactor whose entire value is that behaviour does not move.

**Test-modification note (rule 7).** Two test files imported `_execute_design_point` from
`cli.main` and patched `cli.main.resolve_adapter`. Both were repointed at the new module —
a rename with the function, not a weakened assertion. `tests/test_execution_api.py` is new
and covers what the extraction actually buys.


## Security review, stage 1: guards that now say what they do (2026-08-12)

First of four stages from `REVIEW_AND_UPGRADE_PLAN.md`, on branch
`feature/design-security-review`. Nothing here changes behaviour a student would notice.

**The finding this stage exists for.** Three guards claimed protection they could not
provide, and one had a *passing test* asserting it worked. That is this repo's recurring
defect — a check that reports success without being able to hold — appearing in security
code rather than in CI:

| Guard | Claimed | Actually |
|---|---|---|
| `_deserialize_torch_object`'s `hasattr` check | "guard against loading arbitrary objects from tampered artifacts" | runs *after* `torch.load(weights_only=False)` has already unpickled — pickle executes during load, so it inspects the return value of an operation whose danger is its side effects |
| `python_cli` entrypoint check | "validate that path-like entrypoints don't traverse outside repo" | inspected `command[1]` only, only when it contained `/`, so `["/bin/sh","-c",…]` and every Windows-style path passed untouched |
| `test_rejects_object_without_posterior_interface` | read as a security test | pins a corruption check, which is worth having and is not a security control |

All three now say what they are. The torch check is documented as a **corruption** check
with an explicit "only load `sbi_npe` artifacts you fitted yourself"; the entrypoint check
is documented as a **typo** check; the test is renamed with the reasoning attached.
Replacing the pickle entirely is stage 4.

**`model.name` reached a path that gets `rmtree`'d.** `cli/main.py` builds
`<storage.root>/_active/<token>/<name>_<i>` and recursively deletes it in a `finally`.
`name` was validated only as `min_length=1`. Now `model.name`, `biomodels_id` and
`local_sbml_path` are validated with the same rule already applied to `conda_env`. The
realistic failure was never an attack — a spec already names the command to run — it was a
model called `lck/activity` silently writing, then deleting, somewhere nobody looked. All
11 shipped ModelSpecs validate unchanged.

**A real bug the new tests caught, worth recording.** The first version of the entrypoint
fix checked for `\` as a separate separator. On POSIX that does nothing: `..\..\x.py` is a
single *filename* containing backslashes, resolves happily inside the repo, and passes.
Specs are portable JSON shared between machines, so both adapters now normalise `\`→`/`
before judging, matching what `storage.root` has always done. The test asserting the
Windows gap was closed failed on macOS until this was fixed — which is exactly why it was
written as a test rather than assumed.

**Trust boundary, now stated.** `README.md` gains *"Specs are trusted input — treat one
like a Makefile"*: running a spec runs its author's code, because `entrypoint` naming a
command is the composition mechanism that lets a C++ model and a Python model be swept by
one tool. Every comparable tool behaves this way (`make`, `npm run`, Snakemake, Nextflow,
CWL) and none sandbox. The decision was to say so rather than imply a containment that
does not exist.

**New, and deliberately not containment:** `bayesmm run` prints the entrypoint before
executing, and refuses to run non-interactively when it resolves outside the repository
unless `--yes` / `MM_ASSUME_YES=1` is given. Once per sweep, not once per point — a prompt
that fires 64 times is a prompt nobody reads. When suppressed it *says* it was suppressed,
so a silenced prompt is never indistinguishable from no prompt.

**A second latent bug, found the same way.** Adding the registry-containment check that
`run_store.show_registered_run` always had to `surrogate_store.find_latest_artifact_for_spec`
immediately reddened six unrelated tests — because `SURROGATE_REGISTRY_PATH` was overridable
while `persist_surrogate_artifact` hardcoded `Path("tmp/surrogate_artifacts")`. Relocate the
registry and the two ended up in **different roots**, with nothing to notice. Both now derive
from `_store_root()`, so they agree by construction; with the default registry the resolved
paths are byte-identical to before. This is the first piece of D3, and it is a good
advertisement for the check: the guard's first act was to expose a real incoherence rather
than a hypothetical attack.

**Also:** least-privilege `permissions: contents: read` on all four workflows; `_fit_linear`
deleted (zero callers — an earlier note that tests referenced it was wrong, those tests use a
same-named local helper) and `persist_sweep`'s unused `sweep_id` parameter removed.

**Process note.** `pytest … | tail` reports *tail's* exit code, so a run with four failures
looked like a pass. Every gate in this stage was re-run redirecting to a file and checking
`$?` directly. Worth remembering: it is the same class of mistake as everything else in this
entry — a check that cannot fail is not a check.


## GitHub Actions bumped to Node 24 — `checkout@v7`, `setup-python@v7` (2026-08-12)

Every job in all five workflows was emitting the same deprecation notice: `actions/checkout@v4`
and `actions/setup-python@v5` are built on **Node.js 20**, which GitHub has retired. The runner
was force-running them on Node 24 anyway, so nothing was broken — but that grace period is
exactly the kind of thing that ends without warning, and it would end in all five workflows at
once. Bumped now, while it is a two-line edit rather than an outage.

**Which versions, and why not the minimum.** Node 24 arrives at `checkout@v5` and
`setup-python@v6`, so those would have silenced the warning. Took the current majors instead —
`v7` and `v7` — after checking that neither's breaking changes reach us:

| Release | Breaking change | Our exposure |
|---|---|---|
| `checkout@v6` | credentials persisted to a separate file | none — plain token checkout, incl. `submodules: true` |
| `checkout@v7` | blocks fork-PR checkout under `pull_request_target` / `workflow_run` | **none — we use neither trigger** |
| `setup-python@v6` | Node 24 | — |
| `setup-python@v7` | the `pip-install` input was removed | **none — we pass only `python-version`** |

Both call sites are as plain as they get: `checkout` with `submodules:` true or false, and
`setup-python` with `python-version` alone. No `cache:`, no credentials handling of our own.
Verified by grep before editing rather than assumed. Going to the minimum would have bought a
second bump in a few months for no reduction in risk.

`setup-python@v7` also fixes a detail that matters here specifically: it classifies stderr
warnings as *warnings* rather than errors in annotations. `Deep CI`'s skip audit reads
`::error::` annotations as its failure signal, so a dependency spuriously emitting errors is
noise in the one channel that is supposed to be quiet.

**Scope: all 10 usages, across two repositories.** The four parent workflows went first
(`2352487`). The two in `projects/tcr_signaling/.github/workflows/ci.yml` are a **separate
repository**, so they needed their own commit and push there (`87dd84e`) before the parent's
gitlink could move — a sequence that is never automatic (rule 9) and was authorised
explicitly. Order was deliberate: all four parent workflows had to come back green before
anything was pushed to the submodule, so that a bad `v7` would have cost one revert in one
repo rather than two.

**Coverage note.** `Submodule notebooks CI` is the job most exposed to a checkout regression
— it is the only one that checks out the submodule *and* builds its native model — and it is
scheduled weekly, so the assumption was that this change would go a week unverified there.
It did not: the workflow also triggers on changes to its own file, so it ran on this commit
and passed. `Interface CI` independently covers `submodules: true` on every push. Both green,
so the submodule-checkout path under `checkout@v7` is verified now rather than on Sunday.


## Tutorial 7c blew Deep CI's cell timeout — the cause was `PYTENSOR_FLAGS: cxx=` (2026-08-12)

Three Deep CI runs failed the same way after 7c landed: `Tutorial_7c.ipynb` hit the
notebook runner's **600s per-cell timeout** in `full` and `pymc env`, while
`main env (no backends)` passed — the clue, since only a job *with* PyMC could run the cell
at all.

**It was never the draw count.** Reducing 3000 → 1500 did not fix it, and reproducing CI's
condition locally showed why: **even 400 draws exceeded 10 minutes**. All three workflows
set `PYTENSOR_FLAGS: cxx=`, which makes PyTensor evaluate its graphs in pure Python. That is
harmless for the fast suite's small linear fits, and pathological for 7c: `sample_nuts`
builds a graph whose surrogate term is a **several-hundred-component Gaussian mixture**
(one component per posterior draw), evaluated at *every leapfrog step*. The cost is
per-evaluation, not per-draw, so no draw budget rescues it.

**Fix:** `slow.yml` no longer sets `cxx=`. `CI` and `Submodule notebooks CI` keep it — their
workloads are fine without a compiler and the flag protects them from BLAS variation. With
compilation, 7c runs in ~97s locally. If a runner ever lacks a compiler PyTensor falls back
to the Python path by itself, so the job would be slow rather than wrong.

**Also fixed, from the same run:** `test_an_sbi_surrogate_falls_back_rather_than_being_mis_sampled`
asserted `"pymc_gp" in reason`, but in an sbi-only env `nuts_supported` checks for PyMC first
and returns `"PyMC is not installed"` without reaching the surrogate. Both are correct
refusals; the test now asserts the refusal itself everywhere and the specific wording only
when PyMC is present. `sbi env` is green again.

**Kept:** the `MM_TUTORIAL_DRAWS` knob (default 1500) added while diagnosing this. It did not
solve the timeout, but it is worth having on its own terms — measured at 1500 vs 4000, the
means are identical (`log_decay` 6.00, `depletion` 220), r-hat improves 1.0032 → 1.0016, and
the ridge is unchanged, which is exactly what the notebook tells the reader to expect.

**Lesson worth carrying:** a workflow-level environment variable set defensively years ago
silently defined what kind of computation the tutorials were allowed to contain. It cost
three red runs to find, because the flag lives in CI config and the symptom appeared in a
notebook.


## Deep CI red on three jobs — two distinct causes, both mine (2026-08-12)

The nightly `Deep CI` failed on `full`, `pymc env` and `sbi env`. `main env (no backends)`
passed, which was itself the clue: both faults needed a backend to appear.

**1. `sbi env` — an over-specific assertion.**
`test_an_sbi_surrogate_falls_back_rather_than_being_mis_sampled` asserted
`"pymc_gp" in reason`. In an sbi-only environment `nuts_supported` checks for PyMC *first*
and returns early with `"PyMC is not installed"`, never reaching the surrogate. Both are
correct refusals; only one wording was allowed for. The test now asserts the contract that
holds everywhere — **the refusal itself** — and checks the specific wording only when PyMC
is present. Verified in `py312_bayesmm_sbi` (the job that failed) and in the default env.

**2. `full` and `pymc env` — Tutorial 7c hit the 600s per-cell timeout.**
Its Step 2 cell fitted three surrogates and ran two NUTS chains at 3000 draws / 1500 tune ×
2 chains. Comfortable here, over the limit on a CI runner. Reduced to 1500/750 and the fits
to 300 draws: **97s locally**, and the science is unchanged or slightly better —
`log_decay` 6.001 ± 0.164 against a truth of 6.0, `depletion` 219.6 ± 23.8 against 220,
ridge `sd(combo)` 0.33 vs 0.91/0.88, r-hat 1.0032, 0 divergences.

### Sampling budget is now a knob, not a hard-coded number

Rather than pick one number for every machine, 7c reads `MM_TUTORIAL_DRAWS` (default 1500).
Deliberately one env var in one notebook — the two others that sample are already cheap
enough — because a per-machine auto-tuning scheme would be more machinery than the problem
deserves.

The default has to finish on a student laptop and inside a CI runner's per-cell timeout,
and the notebook's claims are structural (a truth recovered, a ridge present) rather than
precision estimates. Raising it is a real exercise, and the numbers back the prose —
measured at 1500 vs 4000 draws:

| | means | r-hat | ridge sd(combo) vs individual |
|---|---|---|---|
| 1500 (default) | `log_decay` 6.00, `depletion` 220 | 1.0032 | 0.33 vs 0.91 / 0.88 |
| 4000 | `log_decay` 6.00, `depletion` 220 | 1.0016 | 0.33 vs 0.88 / 0.88 |

Means barely move; r-hat improves; the structural claim is identical. Documented in
`tutorials/README.md`.

Verified: `tests/test_nuts_sampling.py` green in both `py312_bayesmm_sbi` and the default
env; 7c executes in 97s at the default and passes its self-check at 1500 and at 4000; fast
suite green; `ruff format --check` and `ruff check` clean on 111 files.


## The default environment now carries both surrogate backends (2026-08-11)

`environment.yml` (`py314_bayesmm`) gains pymc, arviz, pytorch and sbi;
`environment-all.yml` is deleted. Three environments remain: the default, two
single-backend fallbacks, and the Tutorial-2-only biomodels env.

**Why, and it is not tidiness.** `CI`'s fast job installs `.[pymc,sbi]` and runs the whole
`not slow` suite against it. A backend-free development environment therefore ran a
*different suite* from CI — optional-backend tests skipped locally and executed in CI. That
gap hid a real bug, found within minutes of putting the backends in:
`sample_joint_to_store` wrote registry entries with **no `backend` key**, while
`bayesmm meta list` and `test_metamodel_sampling_numpyro` both index `entry["backend"]`.
Reproducing it needed a joint sample → a fitted surrogate → an optional backend, which the
default env did not have. Fixed, and pinned by `tests/test_meta_sample_registry_schema.py`,
which asserts *schema agreement between the two writers* rather than one key, and which was
checked by removing the fix and confirming it fails.

**The old objection no longer holds.** The env files claimed "pinning PyMC, SBI and PyTorch
together in one solve is fragile". Verified false today: conda-forge ships py314 builds of
pymc 5.28.5, pytensor 2.38.3 and pytorch 2.13.0, and sbi 0.26.1 installs on top by pip with
`pip check` clean. **Python 3.14 is kept** — no downgrade was needed, which was the main
risk going in.

**One trap worth recording**, because it cost an environment. Installing the backends
*incrementally* into the existing env produced `OMP: Error #15` — pip pulled PyTorch from
PyPI (bundling its own `libomp`) alongside conda's, giving three OpenMP runtimes. The
recipe avoids it by taking `pytorch` from conda-forge *before* pip sees `sbi`, so pip finds
torch already satisfied. If you hit this, rebuild rather than patch:
`conda env remove -n py314_bayesmm && conda env create -f environment.yml`.

**What it costs.** With both backends installed the `not slow` suite does ~80s of work
rather than ~7s, nearly all of it `import pymc` / `import torch` rather than test bodies —
the same cost CI has always paid. CLAUDE.md's budget line now states the rule as
*test-time*, not wall-clock, and says why uninstalling backends is the wrong way to make
the number smaller.

*(Measured today at 19 minutes wall for 64s of CPU — that is three Claude sessions sharing
one machine, load average ~15, contending on PyTensor's compile lock. Not a property of
the suite.)*

**Kept deliberately:** the single-backend envs, on Python 3.12. They reproduce CI's
per-backend jobs — an "sbi" env quietly containing PyMC is what once hid Tutorial 6's
missing guard — they are the fallback when one backend will not install, and their 3.12
keeps the `requires-python` floor exercised while the default tests the ceiling.
`libroadrunner` stays out: PyPI-only and the most platform-fragile dependency here, so a
failed install should cost one tutorial rather than all of them.

Docs updated in step: `README.md`, `CLAUDE.md`, `tutorials/README.md` and ten notebooks no
longer reference the retired env. Verified after the rebuild: `ruff format --check` and
`ruff check` clean on 111 files under ruff 0.16.2; fast suite green.


## Terminology pass over the tutorials — five glosses, and a DOE clarification (2026-08-11)

A deliberately small pass: find terms a reader meets before anything defines them, and gloss
each at that point. Everything else left alone. Verified each claimed gap by scanning
*markdown only* in reading order — a definition living in a `print()` does not reach someone
reading the prose.

**Changed (five edits, all markdown):**

- **T0 — DOE.** The glossary defined the acronym but not the tradition. Added two clauses:
  the spec field and module are called `design` (so grepping the source for "doe" returns
  nothing, which was confusing), and — the substantive part — that classical design of
  experiments is about *physical* experiments where measurement noise is averaged out by
  replication, randomisation and blocking. **None of that applies to a deterministic
  simulator**: replicating a design point returns the same number. What matters instead is
  coverage, which is what T4 measures. This is a rigour fix, not just vocabulary: the series
  practises design *for computer experiments* (Sobol, discrepancy) while borrowing a name
  from a field whose other pillars it correctly omits, and it never said so.
- **T0 — NUTS** spelled out once as the No-U-Turn Sampler at its introduction.
- **T0 — dropped a stray "IR"** from a parenthetical rather than defining it there; the
  sentence reads better without the jargon, and 7a defines the term properly where it earns
  its place.
- **T2 — SBML** expanded once: Systems Biology Markup Language, the standard XML format
  kinetic models are published in, plus what BioModels is. It appeared 39 times in T2 and was
  never expanded anywhere in the series.
- **T6 — SBI** expanded once as simulation-based inference. Used **59 times** in its own
  title tutorial without ever being spelled out.
- **7b — r-hat and divergences.** Their only explanation lived inside a `print()` string, so
  a reader following the prose never met it. Now defined in markdown, framed as alarms rather
  than scores, with the point that a random walk can raise neither.
- **tutorials/README.md** — the index table promised "read ESS/r-hat" before either exists;
  replaced with the plain-English phrasing.

**Checked and deliberately left alone:**

- **DOE across the tutorials (~110 occurrences).** Kept. T0 defines it before first use, T1
  genuinely teaches the design-of-experiments framing (full factorial, why three levels), and
  converting would delete a concept T1 exists to teach.
- **IR in 7a and T8** — defined in 7a, used downstream. **PPL in 7a** — defined in place.
  **NPE** — expanded in T0's glossary, upstream of T6. **ESS in 7b** — defined at first
  substantive use. No change needed for any of them.
- **T0's self-check cell** — untouched. No wording change invalidated any of its assertions.
- **The root `.md` files** — read for consistency, nothing wrong found, not rewritten.

**Verification note worth recording.** The suggested gate
`REQUIRE_TUTORIAL_BACKENDS=1 pytest -m slow tests/test_tutorial_integration.py` **cannot pass
in `py312_bayesmm_all`**, because that environment deliberately excludes libroadrunner and T2
then takes its preflight-skip path — which is exactly what the flag exists to catch. Strict
coverage therefore needs a split: everything but T2 in `py312_bayesmm_all` (11/11), and T2 in
`py312_bayesmm_biomodels` (1/1). Both green. Only `Deep CI`'s `full` job, which installs the
biomodels extra too, can run the single-command version.


> **Vocabulary.** Framework nouns (spec, design, sweep, surrogate, coupling, metamodel) and
> acronyms (DOE, IR, PPL, NPE, ESS) are defined in [README.md](README.md#terms) and, for the
> sampling diagnostics, in the README's [Sampling method](README.md#sampling-method---method)
> section. Entries below are a dated decision log and are **left as written** — rewriting past
> entries to expand their acronyms would falsify the record of what was decided when.

## Root docs define their terms on first use (2026-08-11)

Prompted by a fair question from the user: *"what's DOE? Why use weird acronyms? It's a
package for scientists."* The README used DOE eight times and expanded it zero times.

The diagnosis is worth keeping, because it is not simply "the acronym is obscure". DOE is
genuinely standard vocabulary — in **statistics and industrial engineering**. It is close
to unknown in computational and systems biology, which is who this package is for. So the
term is standard in a field adjacent to the audience, not in the audience. Two further
strikes against it here:

1. **It over-promises.** Classical design of experiments is about randomization, blocking,
   replication and confounding — machinery for extracting inference from noisy *physical*
   experiments. What this framework does is enumerate input points for a deterministic
   simulator. Borrowing the name imports guarantees the code does not make.
2. **The code never used it.** The spec field is `design`, the module is
   `designs/planner.py`, the artifacts are `sweep_*`. `grep -rn doe src/` returns nothing.
   A reader who met "DOE" in the docs and searched the source found zero hits.

**Convention adopted, applied to every root doc:** define each term the first time it is
used, as one would in a paper. Mechanically, that is two things — a `Terms` table in
`README.md` (the single definition site, worded to agree with Tutorial 0's glossary rather
than compete with it), and inline expansion of every acronym at first use: DOE, IR, PPL,
NUTS, ESS, r-hat, divergences, NPE, SBI, GP, BNN, MPI, SBML, CI, KS, TCR, `LKJCholeskyCov`.
Prose now says "design point"; DOE survives only where it is being defined.

Two of those were worse than merely undefined and are now fixed: **ESS** appeared in a
results table and was spelled out two sections *later*; and the environment table sold
`pymc_gp` as "PyMC GP surrogates" when the backend is Bayesian linear regression — the
README now says plainly that it is not a Gaussian process, and what that costs you on
extrapolation.

Per-document treatment, because one size did not fit:

| Doc | Treatment | Why |
|---|---|---|
| `README.md` | full — `Terms` table + inline expansion | the definition site everything else points at |
| `PRD.md`, `TechSpec.md`, `CodeDesign.md`, `TEST_PLAN.md` | pointer + inline expansion | linked from the doc map as things a reader should open |
| `PROMPT_TO_CODEX.md` | pointer + a vocabulary block; prompt text untouched | its blocks are pasted verbatim into another agent's prompt; editing them would change instructions, not just prose |
| `Status.md` | pointer only | a dated decision log. Rewriting past entries to expand their acronyms would falsify the record of what was decided when |

Also fixed in `README.md` while there: a paragraph that restated the sweep-artifact list
verbatim four lines after the first one, and an orphaned sentence about placeholder
artifacts that had been glued onto the end of the `observed` section.

Not touched: `tutorials/`. Tutorial 0's glossary already defines DOE before any tutorial
uses it, so the series already follows the convention.

## Uncommitted work is now a reportable failure (2026-08-11)

Rule 11 already said "commit regularly". It did not say what to do when you don't, and the
gap showed: a turn could end with a dirty tree and the user would only learn it from a
sentence buried in a long report — if at all.

New `CLAUDE.md` section, *Uncommitted work is a reportable failure*, with three parts:

- **A green-gate definition** (`fmt`/`lint`/`fast`/Status.md/one-logical-unit) that
  *authorizes* committing without asking. Asking permission for a commit the rules already
  sanction costs a round-trip on a question the user has answered in advance.
- **An explicit stop-and-ask list** — red gate, work belonging on a branch, a tree entangled
  with edits you did not make, anything needing a push or history rewrite (rule 9), files the
  user is mid-review on. Caution is half the rule: a wrong commit is its own harm. Crucially,
  the notice is owed in these cases *too* — "I correctly declined to commit" and "I silently
  left the tree dirty" look identical to a reader otherwise.
- **A placement requirement**: the notice is the **first line** of the response, not a
  bullet under Notes and not the closing paragraph. The rule has to be about placement,
  because the failure being prevented is a true statement nobody reads.

Also added, from something that happened during this very session: a commit appeared in the
tree that this agent did not make (`c75001a`, authored from another window while the edits
were in flight). So a clean `git status` proves *someone* committed, not that *you* did —
check `git log` and report which commit carried the work, by hash and author.

`Definition of Done` gains a matching line.

## Module 7 split into 7a/7b/7c; series scope stated honestly (2026-08-11)

Four decisions taken with the user, then executed.

**1. Module 7 is three notebooks.** One 31-minute Tutorial 7 was three questions wearing a
trench coat. Now:

| | Question | Backend | prose |
|---|---|---|---|
| **7a** | What *is* a coupling? (probability, the graph, propagation) | none | ~24 min |
| **7b** | How is the joint sampled, and can I trust the sampler? | PyMC from Step 3 | ~14 min |
| **7c** | What can I ask it? (conditioning, the paper's query, the ridge) | PyMC (SBI optional) | ~19 min |

7a keeping **no backend requirement** is the point of the split: coupling is the concept the
framework is named for, and every student can now reach it. The fitted-surrogate and
noise-trap material that had been bolted onto Tutorial 7 moved to 7b, where it belongs.

**2. SBI in 7c is now a real fit, two-tier.** The backend-refusal demonstration used a
stand-in class that raises `NotImplementedError`. It now fits an actual `sbi_npe` surrogate
when sbi is present and **prints which tier you got**, because a reader whose output differs
from a colleague's should be told why rather than left guessing. Verified: the run reports
`backend refusal checked with real sbi_npe`.

**3. Environments: no change, and the reason is worth recording.** `environment-all.yml`
(`py312_bayesmm_all`) already carries pymc 5.26.1 + sbi 0.26.1 + torch 2.13.0 with no
conflicts, and `CI` has installed `.[pymc,sbi]` together on every push for some time. The
history is the opposite of the folklore: sbi <0.26 listed **pymc as a hard dependency**, so
the two were forced together, never incompatible. The single-backend envs stay because they
mirror CI's per-backend jobs and their value is in what they lack.

`libroadrunner`/`tellurium` deliberately stay out of the all env: PyPI-only, the most
platform-fragile dependency here, and folding them in would mean a student who cannot build
roadrunner loses *every* tutorial instead of one. T2 now says this in plain language, with
two concrete options and a "do not spend an afternoon on it" note.

**4. KS reconnection deferred**, as agreed. 7c Step 4 demonstrates the principle both ways —
its own three-model chain is connected and recovers a planted truth, while the real TCR
metamodel is checked mechanically and reports `kinetic_segregation` UNREACHABLE. The refit
remains the user's call.

### The honesty the series was missing

`"principle"` appeared **zero times** in Tutorial 0. The curriculum never said what it is and
is not. Added:

- **T0, "What this series is — and what it is not"**: a course in the principles, taught on
  toys small enough to check against closed-form answers; explicitly *not* a reproduction of
  the paper. A table maps each thing the paper does to the toy that teaches its shape, and a
  final caveat states plainly that the toys are mostly linear and real systems are not.
- **7c, "Honestly: how this differs from the paper"**: what transfers (the principles) versus
  what does not (the data, the models, the numbers, the finding), and why a toy is the right
  teaching tool — in Step 2 the truth is known, so "did the inference work?" has an answer,
  which is how you earn the right to read a ridge where it does not.

### Verified

All **12** notebooks execute clean in `py312_bayesmm_all` **and** in the backend-less
`py314_bayesmm`; T2 additionally verified for real in `py312_bayesmm_biomodels`. Lint and the
fast suite are clean; every cell in every notebook retains its nbformat id; all internal
notebook cross-references resolve.

One assertion corrected while building 7b: I had claimed joint sampling narrows a coupling's
source by >10%. The closed form says 0.500 → 0.469 at that σ — a 6% effect. The test now
asserts the *direction* plus agreement with the closed form, which is the real distinction
from propagation, rather than a property of those particular numbers.


## Tutorial 7b rebuilt around the paper's actual query (2026-08-11)

Prompted by the question: *can I take any variable in one model and conditionally infer it
from a variable in another?* The answer is yes with one real caveat, and the notebook now
teaches both halves by reproducing the published inference rather than a toy analogue of it.

**What the paper actually does** (Neve-Oz, Sherman & Raveh 2024,
[doi:10.3389/fimmu.2024.1412221](https://doi.org/10.3389/fimmu.2024.1412221), Fig. 7):

    Pr( DL, Dep, t_KS, R_KS, Diff, P_off | Phos_obs, Rg_obs )

Two imaging measurements; six hidden parameters across three separately-built models. It
reports using NUTS — the same sampler `--method nuts` now provides — and its headline
structural finding is a **proportionality constraint `Diff = C·P_off`**: the two Lck
parameters are not separately identifiable, only their ratio is.

**7b now derives that rather than describing it.** The physics is
`λ = sqrt(D / k_off)`, which in logs is linear — so a linear surrogate represents it
exactly, and observing a decay length constrains `log D − log k_off` and nothing else.
Measured in the notebook:

| | value |
|---|---|
| `sd(log_diff)` | 0.882 (prior 1.2 — barely informed) |
| `sd(log_poff)` | 0.875 (prior 1.2 — barely informed) |
| **`sd(log_diff − log_poff)`** | **0.327** — the combination *is* informed |
| correlation | +0.931 |

and the hidden state is recovered through two model boundaries: `log_decay` 5.986 ± 0.162
against a truth of 6.0, `depletion` 221.9 ± 23.5 against 220.0, from two numbers alone.
The ridge plot is the notebook's Figure-7G analogue.

**The caveat, and it is about this repo's own metamodel.** Conditioning travels along
factors; a variable with no path to your data sits at its prior forever and nothing warns
you. Step 6 checks this mechanically and finds `kinetic_segregation` **UNREACHABLE** — its
only output feeds nothing. That is why `rigidity_kT_nm2` and `time_sec` keep tripping the
mixing diagnostic: not a sampler problem, a missing coupling. Recorded in the submodule's
Status.md; fixing it needs a refit, so it is the user's call.

**Also in this pass:** a vocabulary table for onboarding readers who did T1–T7 but do not
remember the jargon; the science of the immune synapse stated plainly (what CD45 and Lck
each do, what a microscope can and cannot see); and an honest `pymc_gp` vs `sbi_npe`
comparison — they are near-interchangeable for *fitting*, and not interchangeable here,
because only a symbolic density gives NUTS its gradient. Guidance: pick on fit quality
first, sampler speed second.

**Verified:** all 11 notebooks pass in `py312_bayesmm_all` and backend-less in
`py314_bayesmm`; 7b's structural lesson (Step 6) runs even without PyMC.


## Tutorial 7b: inference on a coupled model, with PyMC doing the sampling (2026-08-11, stage 3 of 3)

Completes the conditioning work. T7 teaches what a coupling *is* and samples it with the
gradient-free walk that works for any surrogate. 7b answers the question T7 leaves open —
once the models are coupled, how do you *ask things of them* — and shows why a real
probabilistic-programming library earns its place at this layer after all.

Five steps, each verified against something independent rather than asserted:

1. **Two samplers, one distribution.** NUTS, the T7 random walk, and the closed form, side
   by side. Licence to use the faster one comes from it agreeing, not from it being faster.
2. **What gradients buy.** 18% effective samples per draw against 2%, plus r-hat and
   divergences — alarms a random walk cannot raise. Notes that r-hat needs ≥2 chains and
   that the framework reports `None` rather than a NaN that would pass any check.
3. **Conditioning.** `observed` clamps a measurement; `x` moves 0.891 → 2.091 against a
   closed form of 2.092, and narrows. `y` held exactly, and absent from `free_variables`.
4. **Backwards through two models** — the headline. Model A learned `y` from `x`, model B
   learned `z` from `y`, both fitted independently. Measure `z = 2.2` and `x` lands at
   1.961 ± 0.220 against an algebraic 2.00, seven times narrower than its prior. `x`
   appears in neither the measurement nor model B. Under `propagate` this question is not
   inefficient, it is unanswerable.
5. **When the fast path refuses**, and that it says so.

The generalisation the notebook states, which is the actual answer to "would hand-rolling
limit the questions I can ask": any variable can be conditioned on any other as long as a
path of factors connects them. You are not restricted to the direction the simulators
happen to run in — and that, not speed, is the argument for building a joint model.

**A bug this turned up in my own earlier work.** T7's fitted-surrogate step (added the same
day) called `fit_backend_model` unguarded, so T7 *crashed* in the backend-less env while its
prerequisites table claimed it needed nothing. Now: Steps 1-3 need no backend, Steps 4-5
skip cleanly with a printed reason, and the table says exactly that. Verified in both envs.

**And T0's drift guard caught me.** Its self-check asserts the exact set of `--method`
choices, so adding `nuts` failed T0 — by design, since T0's glossary lists them. Guard and
glossary both updated. This is the second time that guard has paid for itself.

Registered in `tests/test_tutorial_integration.py` (`SELFCHECK_BEACONS`), which
`pytest.fail`s on an unregistered notebook rather than skipping it — so a new tutorial
cannot slip in unchecked. `tutorials/README.md` gains the row, and the T7/T8/T9 "Needs"
column is corrected.

**Verified:** all 11 notebooks pass in `py312_bayesmm_all` and in the backend-less
`py314_bayesmm` (7b and T7's Steps 4-5 skipping cleanly there).


## `--method nuts`: the same joint, with gradients (2026-08-11, stage 2 of 2)

Stage 2 of the conditioning work. `sample_joint` treats every surrogate as a black box —
`log_prob` on a dict of floats — so it can only do a gradient-free random walk. That is
correct and backend-neutral, and it is slow: on the TCR metamodel three variables had an
effective sample size under 20.

It does not have to be a black box for `pymc_gp`. That backend is Bayesian **linear**
regression, so its predictive density is

    mu[s,d] = x @ W[s,:,d] + bias[s,d]
    log p(y|x) = logsumexp_s( sum_d Normal_logpdf(y[d]; mu[s,d], sigma[s,d]) ) - log S

— an equally weighted mixture over the surrogate's S posterior draws, every operation
differentiable. Written as a PyTensor graph, NUTS applies.

**Measured on the real TCR metamodel** (14 variables, 4 fitted surrogates, same seed):

| method | worst-variable ESS | efficiency | diagnostics |
|---|---|---|---|
| `joint` (random walk) | 10 / 1500 | 0.7% | accept_rate only |
| `nuts` | 1744 / 3000 | **58%** | r-hat 1.0036, 0 divergences |

The three poorly-mixed variables that the mixing diagnostic has been flagging are gone.
Note also that this path carries the surrogate's **parameter posterior** into the metamodel
(the full 500-draw mixture) rather than collapsing it to a predictive mean — which is
arguably the point of having fitted a Bayesian surrogate at all.

**Scope is deliberately narrow, and the fallback is loud.** It activates only when every
surrogate is a diagonal `PymcPosteriorLinearModel`. `sbi_npe` is a torch normalizing flow:
its gradients exist but reaching them from PyTensor needs a custom `Op`, not written. When
the model is not expressible the CLI prints why and falls back to `joint` — a performance
flag that silently gives you the slow path is a lie.

`sample_joint` is **not** replaced. It stays the default for `--method joint`, the
backend-neutral option, and the one verified against a closed-form Gaussian.

**The risk this introduces** is that two implementations of one density drift apart: if the
PyTensor graph and `evaluate_log_prob` ever disagree, both samplers keep running and both
keep producing plausible numbers. `tests/test_nuts_sampling.py` guards it from both sides —
against the closed form, and against `sample_joint` on the same model.

One bug caught while building it, of exactly the shape rule 12 is about: r-hat is undefined
for a single chain and arviz returns NaN. A mixing check written the obvious way
(`r_hat > 1.01`) would then be **False for every variable**, so a one-chain run would look
impeccable. r-hat is now reported as `None` below two chains, with the ESS floor taking
over, and a test pins it.


## Conditioning: `observed` makes the question askable at all (2026-08-11)

Raised by the user as a design critique: it is awkward that the metamodel layer hand-rolls
its own sampler instead of using a probabilistic-programming library, and — the sharper
half — *wouldn't that limit asking probabilistic questions about any variable of one
surrogate conditioned on any variable of another?*

Investigated before answering. The critique is right, and the sampler turned out to be the
**smaller** half of the problem:

**There was no `observed` anywhere.** Not in `MetaModelSpec`, not in the IR. The layer
could only ever draw the *whole joint*. "Given that I measured y, what does that imply
about a and b?" was not expressible — the only workaround being a razor-tight prior on the
measured variable, which is undocumented and actively bad: it is precisely the ridge
geometry that makes a coordinate-wise random walk freeze (see the mixing-diagnostic entry).

Measured, on `y` observed at 4.0 with a fitted `pymc_gp` surrogate asserting `y = a + b`:

| route | posterior a | ESS efficiency | diagnostics |
|---|---|---|---|
| tight-prior workaround | 1.783 ± 0.470 | 4.6% | accept_rate only |
| **`observed` (this change)** | 1.751 ± 0.475 | 5% | + records what was conditioned on |
| PyMC + NUTS prototype | 1.794 ± 0.478 | **29%** | + r̂ = 1.0027, divergences |

All three agree on the answer, which is reassuring about the hand-rolled sampler's
correctness. Note that `observed` alone does **not** fix efficiency here — the bottleneck
is the `a`/`b` trade-off along `a + b = 4`, not the `y` dimension. That is what the NUTS
path is for, and it is why this landed as stage 1 of 2 rather than as one change.

**What `observed` does:** clamps the variable — never drawn, never proposed, held at its
value while every factor mentioning it is evaluated there. It leaves the sample space
entirely, so its prior term becomes a constant that cannot affect any acceptance ratio,
which is the honest meaning of "I measured this".

- `joint`: real conditioning; information reaches every connected variable, both directions.
- `propagate`: forward only, because propagation never looks upstream. Stated in the code
  and the docs rather than left for a reader to discover.
- Observing the target of a `deterministic` coupling is **refused** by the builder, naming
  the variable and the fix. That target is computed from its source, so a second asserted
  value is a contradiction — and silently letting one win would return healthy-looking
  draws for a model that cannot be satisfied.
- Both paths record `observed` in `inference_data.json`: the same spec with and without an
  observation answers two different questions and lands in the same store.

**Verified.** `tests/test_metamodel_conditioning.py` checks the conditioned posterior
against the **closed form** (normal priors + linear-Gaussian coupling give an analytic
answer), that conditioning actually moves and tightens the free variable — a guard against
`observed` being silently ignored, which would otherwise still produce plausible numbers —
that the deterministic conflict is refused, and that specs and stored IRs written before
this field still load. End to end on the real TCR metamodel: observing
`contact_fraction = 0.30` clamps it (sd 0) and the deterministic link reproduces
`cd45_boundary_density = 588.81 × 0.30 + 277.30 = 453.94` to 1e-13, while the
surrogate-informed variables stay free.

**Next (stage 2):** a PyMC-native `--method nuts` for metamodels whose surrogates are all
`pymc_gp` — that backend is Bayesian linear regression, so its predictive density is
directly expressible as a PyTensor graph and NUTS applies. The random-walk path stays as
the backend-neutral fallback for black-box surrogates such as `sbi_npe`, whose torch
normalizing flow would need a custom PyTensor `Op` to expose gradients. All four TCR
surrogates are `pymc_gp`, so that project would benefit immediately — it currently has
three variables with ESS < 20.


## Tutorial 7 rewritten to teach coupling as probability (2026-08-11)

Three problems, all reported by the user reading it as a newcomer would.

**1. The prerequisites spoke in implementation jargon.** The table said "no PPL backend at
all", `"ppl_backend"` "names a *compiler target*", `compile_metamodel` "returns a plain
dataclass". A reader who does not already know what a PPL or an IR is learns nothing from
that. Rewritten in plain language, with the one unavoidable term defined once, inline.

**2. "Why does coupling need no PyMC or SBI?"** — a good question that deserved a real
answer rather than a parenthetical. It is now its own short section: the libraries were for
*fitting* (T5/T6), that work is finished and saved as an artifact by the time you get here,
and coupling itself needs only draws from a normal, an affine transform, and a
log-density comparison. Verified rather than asserted: nothing under `meta/` imports
`pymc`, `torch` or `sbi`.

Also states accurately what `ppl_backend` does, which is nearly nothing —
`compile_metamodel` validates the string against two allowed values and stores it; its only
effect on any number is that `"numpyro"` multiplies coupling noise by 1.05 in the propagate
path. The transferable lesson (a config field that looks like a dependency may be a
statement of intent) is drawn explicitly, with `pymc_gp` named as the same trap.

**3. Coupling was never written down as probability.** It was described as a sentence you
add to a spec and shown as a scatter plot. A student could finish unable to say what density
they had sampled from. There is now a section building it in three small steps — independent
priors multiply; the assertion is a *scoring factor* `φ(y,C) = Normal(C; y, σ)`; the coupled
joint is their product — followed by a computed three-panel figure and this table:

```
                              sd(y)    sd(C)     corr
prior, uncoupled              1.000    1.000    0.000
coupled joint (exact)         0.711    0.711    0.978
propagate (sampled)           0.998    1.010    0.989
```

The correlation is nearly identical, so a scatter plot cannot distinguish the two — which is
precisely why the confusion survives in real work. `sd(y)` can: the true joint narrows the
coupling's *source* to 0.711 (exact, from inverting the precision matrix), while propagate
leaves it at its prior width. That single number is the propagation-vs-inference distinction,
made measurable.

Writing the coupling as a factor rather than as `p(C | y)` matters and is called out: read it
as a conditional and you have silently assumed `C` is *generated* from `y`, which is
`--method propagate` chosen without realising you chose. A callout says so.

**4. Structure was wrong** — the recap and troubleshooting tables sat in the *middle*, and
step numbers ran 1, 2, 3, 6, 7 after the fitted-surrogate section was appended. Now: framing
sections, Steps 1-5 in order, then recap, troubleshooting, final check. A "Where this sits in
the series" table connects T1/T3/T4/T5/T6 to what T7 does with each.

Verified: T7 executes clean in `py312_bayesmm_all` and its self-check passes; the full
10-notebook suite is green; every cell keeps its nbformat id.


## Full pedagogical audit and repair of the tutorial series (2026-08-11)

Ten independent reviewers, one per notebook, then a per-notebook repair pass, then my own
verification. **49 high-severity findings**, 19 of them `science-wrong`; T4 and T5 came back
rated *broken*. What follows is what was actually wrong, not what was tidied.

### The defect that produced ~15 of the findings

`pymc_gp` is Bayesian linear regression (see the separate entry below). T5, T6 and T9 all
reasoned from Gaussian-process behaviour — reversion to the prior mean off the data, error
bars that widen to warn you — which is the *opposite* of what this backend does. Students
were being handed a mental model that would mislead them on their own data. All three
notebooks now name the trap and **measure** the behaviour instead of asserting it.

T5 goes further and fits the toy's `product` channel, where a linear surrogate is genuinely
wrong: MAE 0.419, predictions as low as −1.001 for a quantity that is never negative, and a
reported width of 0.670 that does not cover the error. That is the lesson worth having —
*a linear surrogate on a nonlinear system is confidently wrong*, which is more dangerous
than a GP that widens and warns.

### Things that had never run at all

- **T6's Step 4** — the GP-vs-NPE comparison, the one cell where the two surrogate families
  appear side by side — printed `Step 4 SKIPPED` in *every environment we shipped*, because
  no documented env had both backends. Its skip message also told the reader to install SBI
  when SBI was present and PyMC was missing. New `environment-all.yml` (`py312_bayesmm_all`)
  fixes the first; the branch now names the backend that is actually absent.
- **T4's Sobol panel** — the right half of its central figure — had never rendered. Cell 10
  read `tmp/tutorials/toy_store_sobol/runs/`, which does not exist (the framework writes
  centralized sweeps). The self-check passed anyway.
- **The framework's own central arrow.** No notebook in the series had ever fed a *fitted*
  surrogate into a metamodel: every coupled spec references `dummy_A/B/C` placeholders with
  no `backend_payload`. T7 now demonstrates both halves — `--method joint` refusing the
  placeholders (asserted exit 1), and then succeeding on a surrogate the notebook fits
  itself. Priors put `a + b` near 2 and `y` near 4; the surrogate says `y = a + b`; the
  joint brings them together at `a`≈1.65, `b`≈1.82, `y`≈3.69, with `a` and `b` narrowing.
  Both ends move, which is the whole difference from `propagate`.

### Concepts the series never taught

- **"prior" appeared zero times in T0–T4**, and "likelihood" zero times in T0–T5, while T0
  used "posterior" seven times and defined "joint posterior" in its glossary. T0 now defines
  prior / likelihood / posterior before anything depends on them, and carries DOIs for the
  two source papers (previously cited by author name only).
- **`--method` appeared in no notebook's code.** All four `meta sample` calls ran the default
  `propagate` while six passages called the output a "joint posterior". `--method` is now in
  7 of 10 notebooks' prose and executed in T0, T7, T8, T9.
- **T2's sweep was scientifically inert**: `k_on` has elasticity 1.7e-05 on this model — the
  heatmap varied by ~0.01% of its own colour bar. It now also sweeps `k_p`, elasticity
  **+5.73**, and the `k_on` units are corrected (the SBML declares `unit_0 = 1/s` over
  molecule counts, not `1/(M·s)`).
- **T8's effect was below its own noise floor**: coupling sigmas 0.2/0.25 moved `std(w)` from
  1.027 to 1.059, smaller than Monte Carlo error at 400 draws. Raised to 0.6/0.8 so the
  quadrature lesson is visible rather than asserted.

### Self-checks

Previously several were tautologies — T3's re-read a value the cell above had just written;
T1's would pass on a notebook that did nothing. They now carry 4–16 assertions each, and the
rule applied throughout was: *it must fail on a notebook that ran but taught nothing*.

### Verification

- All 10 notebooks execute clean in `py312_bayesmm_all`; T2 verified separately in
  `py312_bayesmm_biomodels` (11/11 points, both sweeps).
- Both backends exercised for real, not in skip mode: T5 `pymc_gp` MAE 0.00000, T6 `sbi_npe`
  MAE 0.02460, and T6's comparison cell now prints both.
- T0 additionally executed in the backend-less `py314_bayesmm`, where its readiness table
  correctly flips to `[MISSING]` — proving the verdict is a live probe, not hardcoded.
- `ruff format --check` + `ruff check` clean; fast suite green; every cell in all 10
  notebooks retains its nbformat `id`.

### Caveat worth keeping in view

The prose grew substantially (T5 7.7k → 20k characters). The reviewers' own warning was
"density is not depth", and a future pass should look for places where a shorter statement
would land harder. Nothing was cut to make room; that trade has not been made yet.

## A joint chain that never moved reported `accept_rate=0.29` (2026-08-11)

Found while wiring a *real* fitted surrogate into a metamodel — something no tutorial had
ever done (every coupled spec in the curriculum referenced `dummy_A/B/C` stub artifacts
with no `backend_payload`).

A `pymc_gp` fit of an exactly-linear truth has predictive sd ~1e-5, so its likelihood is
effectively a delta function. Conditioning on it puts the posterior on a thin ridge;
tuning then shrinks every proposal scale to ~6e-6 in order to keep accepting, and the
chain explores a ~3e-5 sliver of a distribution whose real width is ~0.6. Result:

```
var   prior sd  propagate    joint
a         0.60      0.600    0.000
b         0.60      0.609    0.000
y         3.00      2.971    0.000
```

Those zeros read as "conditioning pinned them precisely". They actually mean the sampler
went nowhere. And `accept_rate` was **0.29** — by the only diagnostic reported, the run
looked healthy. A coordinate-wise random walk cannot climb a ridge: to move `a` it must
move `y` by the same amount in the same step, which it essentially never proposes.

**Fix:** `sample_joint` now computes a per-variable effective sample size and reports
`poorly_mixed` — free variables with ESS < 20. Both go into `inference_data.json`, and
`bayesmm meta sample --method joint` prints a warning naming the variables and the usual
cause. 20 is deliberately low: this is a "this chain told you nothing" alarm, not a
convergence standard.

**This is not hypothetical on real work.** The TCR metamodel flags
`contact_radius`, `rigidity_kT_nm2` and `time_sec` — matching the ESS ≈ 10 measured by
hand when notebook 03 gained its ESS column. The framework now says it without anyone
computing it.

**Tested in both directions** (`tests/test_joint_sampling_mixing_diagnostic.py`): a
razor-sharp likelihood must be flagged, and a well-mixing chain must NOT be. A warning
that fires on healthy runs is trained away within a week, which would leave us worse off
than before.

## `pymc_gp` is not a Gaussian process, and the tutorials were teaching that it was (2026-08-11)

Found during a full pedagogical audit of the tutorial series. `_fit_pymc_bayesian_linear`
builds `beta ~ Normal(0,2)`, `intercept ~ Normal(0,2)`, `mu = intercept + x @ beta` —
Bayesian **linear regression**. There is no kernel, no covariance function, no `pm.gp`
anywhere in the package. Nothing in `src/` said so, and the backend name says otherwise.

Tutorials 5, 6 and 9 reasoned throughout from Gaussian-process properties: that
predictions revert toward the prior mean away from the training data, and that error bars
widen as you leave it. Measured, trained on `a, b ∈ [0,2]` predicting `a + b`:

| query | mean | sd | truth |
|---|---|---|---|
| (1, 1) | 2.000 | 0.00000 | 2.0 |
| (5, 5) | 10.000 | 0.00000 | 10.0 |
| (20, 20) | 40.000 | 0.00000 | 40.0 |
| (100, 100) | 200.000 | 0.00000 | 200.0 |

Perfect, confident extrapolation fifty times outside the training box — the *opposite* of
what the tutorials claimed, not merely an imprecise version of it. Students were being
taught a mental model that would mislead them on their own data.

The honest lesson is also the more useful one, and the tutorials now teach it: a linear
surrogate on a **nonlinear** system is confidently wrong with near-zero error bars, which
is more dangerous than a GP that widens and warns you. Judge fit from held-out error, never
from predictive width alone.

**Not renaming the backend.** `SurrogateSpec.backend` is a `Literal["pymc_gp", "sbi_npe",
"numpyro_gp"]`, so a rename breaks every existing spec and every stored artifact. The name
stays; the correction is carried in the module docstring, the fit function's docstring, and
the tutorials. Worth revisiting if a compatibility alias is ever added — flagged for the
user rather than decided here.

**Pinned by** `tests/test_pymc_gp_is_linear_not_a_gp.py` (`slow`, `optional_backend`): the
extrapolation behaviour at three points far outside the training box, plus a structural
guard that no GP machinery (`pm.gp.`, `ExpQuad`, `Matern*`) has appeared in the package. If
someone later swaps in a real GP — a reasonable thing to want — it fails, which is the
signal to rewrite those tutorial passages in the same change rather than let them rot back
into being wrong.

## Registry writes were silently lost under concurrency on Windows (2026-08-10)

`test_locked_registry_concurrent_writes` went red on Windows only: four threads wrote
to one registry, three raised, and the file ended with **one key of four**.

`_filelock.py`'s docstring asserted that opening a fresh descriptor per acquirer
serialized threads — *"both backends behave correctly when separate fds are used per
acquirer"*. True for `fcntl.flock()`, false for `msvcrt.locking()`, whose locks belong
to the **process**, not the descriptor. And `LK_LOCK` does not block: it retries ten
times at one-second intervals, then raises `OSError`. So concurrent threads did not
queue — they failed, and their registry entries disappeared. Silent data loss, caught
only because that test asserts all four keys rather than merely that the file parses.

**Fix:** a `threading.Lock` per registry path, taken *before* the descriptor is opened,
so only one thread in a process ever contends for the OS lock. The OS lock still does
cross-process exclusion. Locks are keyed by resolved path, so two names for one file
contend correctly. Nesting for the same path deadlocks and is documented as
unsupported — a reentrant lock would only hide that the OS lock cannot be reacquired
either.

**Test added:** `test_locked_registry_under_contention_never_drops_a_writer` — 16
threads released together from a `threading.Barrier`, asserting that no writer raised,
none hung, and every key landed. The existing 4-thread test asserts contents only; a
dropped writer that happened not to change the key set would slip past it.

This was not caused by the joint-sampling work, though it first appeared alongside it:
the failing test is self-contained (its own `tmp_path`, its own registry), so it cannot
be pollution from another test.

**A second Windows bug behind the first**, found by the new 16-thread test rather than
by inspection: with the thread lock in place, 1 of 16 writers still raised
`PermissionError(13)`. The lock file was prepared *outside* the lock with
`lock_path.write_bytes(b" ")` — and `write_bytes` truncates. Truncating a file whose
byte 0 another handle has locked is denied on Windows. Sixteen threads starting
together all saw a missing lock file and all tried to create it; the ones arriving
after the first had locked byte 0 raised instead of writing.

Preparation now happens inside the lock, via `os.open(O_RDWR | O_CREAT)` — created if
absent, never `O_TRUNC` over a live lock region — and the initial byte write tolerates
`PermissionError`, since another process holding byte 0 means the byte is already
there. Verified 20/20 consecutive runs locally; the Windows path is CI's to confirm.

Worth noting the shape of this: the first fix was correct and insufficient, and the
only reason the remainder surfaced is that the new test asserts *no writer raised*
rather than only checking the final contents. A dropped writer whose key happened to
be written by someone else would have passed a contents-only check.

## Joint sampling verified against both surrogate backends (2026-08-10)

`sample_joint` conditions on surrogates through exactly one call — `log_prob` — and
that call was exercised on `pymc_gp` only, because the TCR metamodel fits all four of
its surrogates with `pymc_gp`. Nothing in the repo drove `sbi_npe` through a joint
sample, so "joint sampling works" was a claim about one backend.

`tests/test_joint_sampling_backends.py` (new) runs the same test against both: fit a
surrogate on data from a known linear map, give the output a deliberately vague prior
(sd 5.0), and require joint sampling to pull it onto the surrogate's prediction
(residual sd < 1.0). If the likelihood were skipped — which is what `--method
propagate` still does — the output would return at its prior and the test would fail
loudly rather than quietly agreeing. A second test pins the single-row calling
convention `CompiledMetaModel.evaluate_log_prob` actually uses, which batch-oriented
surrogate tests would not catch.

Each parametrisation skips when its backend is absent; `REQUIRE_JOINT_BACKENDS=1`
turns that skip into a failure, and is set for Deep CI's `full` job alongside
`REQUIRE_TUTORIAL_BACKENDS` (rule 12). Skip reasons are worded to begin "needs pymc" /
"needs sbi" so they match Deep CI's existing `SANCTIONED` patterns — a reason that
cannot match fails the job, which is the intended behaviour, not something to work
around.

**Result: both backends work.** Verified by running the file in each env —
`py312_bayesmm_pymc` (pymc passes, sbi skips) and `py312_bayesmm_sbi` (sbi passes,
pymc skips), and confirmed on Deep CI.

**One CI-only wrinkle**, worth recording because the fix looks like a suppression and
is not: on Deep CI's ubuntu runners the `pymc_gp` parametrisation failed with
`RuntimeWarning: overflow encountered in dot`, raised inside pymc's own internals while
NUTS explored extreme values during tuning, and promoted to an error by
`filterwarnings = error`. It did not reproduce locally in three runs, including under
CI's own `PYTENSOR_FLAGS=cxx=` — it is BLAS-build dependent.

Handled with a `@pytest.mark.filterwarnings` scoped to that exact message. That is
defensible here specifically because **the test does not infer fit quality from the
absence of warnings**: it asserts directly that the fitted surrogate assigns higher
`log_prob` to the true output than to a wrong one, before using it for anything. A
genuinely broken fit still fails on an assertion that says what broke. A blanket
`ignore::RuntimeWarning` would not have been acceptable.

**Marked `slow`, and the reason is a fact worth carrying:** joint sampling's cost is
dominated by surrogate evaluations, and the two backends are ~100x apart. Measured
here: `sbi_npe.log_prob` ≈ **23.5 ms/call** against ≈ 0.2 ms for `pymc_gp`, with the
NPE *fit* itself only 4.5 s. So the chain, not the training, is what costs — 2800
evaluations run in 8.6 s on pymc_gp and 3 min 8 s on sbi_npe.

Two consequences:
- These tests cannot live in the fast suite. CI's fast job installs both backends, so
  unmarked they would have added minutes to every push on three operating systems.
  The first draft used 4000 draws x 2 chains and took ~20 minutes; it is now 2000
  draws x 1 chain, which still constrains `y` from a prior sd of 5.0 to a residual sd
  below 1.0.
- For real use with NPE surrogates: budget for it, and prefer fewer, longer chains
  over many short ones. A gradient-based sampler would need the surrogate `log_prob`
  as a PyTensor graph, which is the same prerequisite as unlocking NUTS.

## `meta sample` now records which sampler produced a dataset (2026-08-10)

`sample_joint_to_store` wrote `method: "random_walk_metropolis"`; the `propagate` path
wrote no `method` key at all. Both write into `tmp/metamodel_samples/`, so the two were
distinguishable only by a **missing** field, and a store containing both could not be
read without knowing which command had produced which entry. `_sample_core` now records
`method: "prior_propagation"` and `surrogates_evaluated: false` — the latter being the
consequential difference, since that path calls the compiled model with `surrogates={}`
and therefore propagates rather than conditions.

Pinned by `test_both_sampling_methods_label_themselves_in_their_artifacts`: both paths
must name a sampler, and the two names must differ. This is what lets notebook 03 select
its propagate and joint datasets explicitly instead of by mtime.

## Formatter emitted syntax the package's own minimum Python cannot parse (2026-08-10)

`ruff format` rewrote `except (OSError, json.JSONDecodeError):` in
`meta/joint_sampling.py` into the unparenthesized PEP 758 form
`except OSError, json.JSONDecodeError:`. That is valid only on Python 3.14+, and
`requires-python` is `>=3.12` while CI runs 3.12 — so `tests/test_joint_sampling.py`
could not even be *collected* on any of the three CI operating systems, while the
same tree was green locally on 3.14.

**Cause:** `[tool.ruff] target-version = "py314"` did not track
`[project] requires-python = ">=3.12"`. Ruff treats target-version as permission to
emit newer syntax, so the formatter was targeting the newest interpreter on the dev
box rather than the oldest one the package supports.

What made this costly to diagnose was the feedback shape: every hand-fix of the
`except` line was undone by the next `make fmt`, which reads as an editor fighting
back rather than as a configuration mismatch. Isolating it needed a two-line file
formatted in a scratch directory, plus running that file under both interpreters.

**Fixes:**
- `pyproject.toml`: `target-version` → `"py312"`, with a comment saying it must
  track `requires-python`. Re-running `ruff format` now leaves the parenthesized
  form alone.
- `tests/test_ruff_target_matches_requires_python.py` (new, `contract`): asserts
  `target-version <= min(requires-python)`. Verified it actually fails when
  target-version is put back to `py314` — a guard that cannot fail is rule 12's
  whole complaint.

**Verified:** `ruff format --check .` + `ruff check .` clean; fast suite green on
3.14 (104 files formatted, 0 failures); `tests/test_joint_sampling.py` collects and
passes 4/4 on Python 3.12, which is the exact thing that was broken.

### Pre-existing, unrelated: pytensor/numpy einsum break in the local pymc env

`tests/test_surrogate_multi_output.py::test_pymc_gp_multi_output_full_cov_runs_and_recovers_means`
fails in `py312_bayesmm_pymc` with `ValueError: not enough values to unpack
(expected 5, got 3)` at `pytensor/tensor/einsum.py:672`. pytensor 2.37.0 calls
numpy's *private* `np.einsum_path(..., einsum_call=True)` and unpacks 5-tuples;
numpy 2.4.6 returns 3-tuples. Purely upstream.

Confirmed pre-existing by stashing the changes above and re-running the same test at
HEAD — identical failure. Recorded rather than silently tolerated (rule 2): local env
is pytensor 2.37.0 / numpy 2.4.6 / pymc 5.27.1. CI installs numpy unpinned, so
whether CI sees it depends on what pip resolves there. If it turns up in CI, the fix
is a numpy upper bound on the `pymc` extra, not a change to our code.

## Tutorial-stability hardening + post-mortem on missed T2 silent failure (2026-05-15, commits 28835b8..)

A previous verification commit (`61454b5`) reported "30/30 PASS" — 10 tutorials × 3 conda envs (`py312_bayesmm_sbi`, `py312_bayesmm_pymc`, `py312_bayesmm`). The user then opened Tutorial 2 manually in `py312_bayesmm_sbi` and saw `Run complete: 0 successful runs / 11/11 points failed`. The BioModels SBML sweep failed silently for every DOE point even though `libroadrunner 2.9.2` was installed in the kernel. **My verification reported PASS for a tutorial that did no useful work.**

Diagnosis surfaced THREE independent bugs:

1. **`runners/local_process.py:32` had a misguided `shutil.which("python") is None` guard.** The intent was to substitute `sys.executable` for bare `"python"` only when no `python` was on PATH. With base conda's `python` on PATH almost everywhere, the substitution NEVER fired — so worker subprocesses ran in PATH-`python` (typically base conda) instead of the kernel/CLI's env. When the kernel had libroadrunner but base didn't, every DOE point failed silently with `ModuleNotFoundError: No module named 'roadrunner'` recorded only in `sweep_logs.jsonl`. **Fix:** drop the guard; ALWAYS substitute `sys.executable` for bare "python" when no `conda_env` is set.

2. **`adapters/biomodels_sbml.py:101` hardcoded bare `"python"`** at command construction. Even with the runner's substitution as a backstop, the adapter's intent should be explicit at the source. Replaced with `sys.executable`.

3. **The BioModels download URL was broken.** The previous URL returned HTTP 200 with `text/html` (the BioModels web UI) instead of SBML XML. The adapter blindly cached the HTML as `<biomodels_id>.xml`; subsequent libroadrunner loads failed with "XML content is not well-formed". Fixed in three spec files; new URL verified to return `application/xml`. The adapter now also content-type-checks responses and raises a loud `RuntimeError` (with the bad content-type + URL + actionable instruction) instead of caching garbage.

### Post-mortem (constructive)

Three things went wrong, ordered by lesson value:

- **False success metric.** The verification used `jupyter execute` exit code as the criterion. T2's run cell calls `run_mm_cli("run", spec, check=False)` — non-zero CLI exit doesn't propagate to Python; the notebook completes "cleanly". The cell printed `Run complete with failures: 11/11 points failed` literally, but the harness never read cell outputs. The wrong question is "did the notebook crash?"; the right question is "did the notebook achieve what it claims to teach?". A test that asserts nothing meaningful is no test at all.
- **Verification was ad-hoc, not tracked.** A bash script in `/tmp/verify_tutorials.sh` doesn't get reviewed, doesn't accumulate per-tutorial knowledge of what success looks like, and won't be re-run by anyone else. A test in `tests/` would have forced rigorous success criteria upfront.
- **Pattern audit missed the second instance.** The same subprocess-env-leakage was already fixed once in `tutorial.py::run_tool` (~commit eb894ab). When fixing pattern X, grep the whole codebase for X — don't trust "I fixed the one that bit me".

### Hardening response (this commit series)

- **`tests/test_runner_subprocess_env.py`** + **`tests/test_adapters_no_bare_python.py`** (new): regression tests pinning the new always-substitute contract at both the runner and adapter layers. Belt + suspenders.
- **`tests/test_local_process_runner.py`** + **`tests/test_runner_unit.py`**: updated — the previous versions PINNED THE OLD BROKEN BEHAVIOR (`expected = "python" if shutil.which("python") else sys.executable`). Now anchored on the correct contract.
- **Per-tutorial self-check cells** appended to all 10 `tutorials/Tutorial_*.ipynb`: each notebook ends with a code cell that asserts the canonical scientific artifact (sweep_rows.csv has success rows, surrogate has posterior_draws calibrated to within tolerance, samples_dataset has the right variables and the coupling correlation, capstone composes end-to-end). Failures raise `AssertionError` → propagate through `jupyter execute` exit code → both interactive students AND CI/harness see them loudly. Two-tier for backend-gated tutorials (T2 / T6): if the optional dep is missing and preflight skipped, the assertion is "preflight banner was printed".
- **T2 preflight extended** with `LIBROADRUNNER_WORKER_OK`: in addition to checking that the kernel can `import roadrunner`, spawn a `[sys.executable, "-c", "import roadrunner"]` subprocess and verify it works too. Catches "half-installed env" cases where the bug recurs in some new way. New banner branch explains what's wrong + how to fix.

### Open follow-ups
- **Verification harness rewrite (`scripts/verify_tutorials.py`)**: tracked in plan file; defers to per-tutorial self-check cells (which now do the heavy lifting). Worth landing as a tracked test (`tests/test_tutorial_integration.py @pytest.mark.slow`) so CI's slow suite catches notebook regressions automatically.
- **Audit `subprocess.run()` calls across `src/`** for any other `python` vs `sys.executable` instances. Two were found and fixed (runner + biomodels adapter); a third (`tutorial.py::run_tool`) was already correct.



## High level state
- Stage: Prompt 17 implementation complete
- Current focus: validating centralized sweep output behavior across tutorial and optional MPI environments

## Decision Log

### 2026-08-09: Commit `environment-all.yml`; correct two stale references

Loose-end sweep before handing the tutorials to a reader.

- **`environment-all.yml` was untracked while three committed documents told readers to
  use it** — `README.md` calls it "the one to use to work through the tutorials",
  `CLAUDE.md`'s env table lists it, and `tutorials/README.md` puts it first. Anyone
  cloning the repo and following the documented setup hit a missing file. Committed;
  `conda env create --dry-run` resolves it cleanly.
- **`README.md`'s documentation map still pointed at `AGENTS.md`**, which was folded into
  `CLAUDE.md` in 2dffa30. Repointed. (`PROMPT_TO_CODEX.md` also references it, but that
  file is a historical prompt pack rather than a live map, so it is left alone.)
- **`tests/test_submodule_notebooks.py` carried two comments that had gone stale.** Its
  docstring said the execution tests "are not in CI" — `.github/workflows/notebooks.yml`
  runs them weekly — and the timeout rationale quoted a "79 DOE points / ~30 min" sweep
  from before 02 gained its `TEACHING_SCALE` default. Both corrected; the generous
  timeout is kept, with the real reason stated (flipping TEACHING_SCALE off is supported
  and runs for hours).


### 2026-08-07: pre-commit formatted in place, so it shipped unformatted commits

The hook ran `ruff format .` — in place, after staging. So it rewrote files the
commit had already captured: the commit kept the unformatted content while the
working tree quietly held the fix.

It bit exactly as you would expect. `meta/joint_sampling.py` and `cli/main.py`
were committed unformatted, `CI`'s `ruff format --check src tests` went red on all
three OSes, and the working-tree difference looked like an unexplained local edit
— so it was reverted, discarding the fix and leaving the repo red.

Changed to `ruff format --check .`, which refuses the commit and says to run
`make fmt`. What gets committed and what got checked are now the same bytes. The
`ruff check` and pytest gates are unchanged.

### 2026-08-07: `meta sample --method joint` — the coupling step now samples

Raised by Amit Meiri: the coupling step "didn't exist" — practically, how do you
sample once you have declared a Gaussian coupling between variables of two models?
He was right, and the gap was narrower and stranger than it sounds.

**What already worked.** `CompiledMetaModel.evaluate_log_prob` computes the full
joint log-density: priors, couplings (gaussian_link / deterministic, identity /
affine) and surrogate likelihoods. The target density was there all along.

**What did not.** Nothing sampled from it. `sample_metamodel` draws each variable
independently from its prior and overwrites coupled targets with
`transform(source)`, and it calls `evaluate_log_prob(probe, surrogates={})` — an
empty map — purely as an executability probe. There is no MCMC in `meta/`. So a
declared coupling reshaped its **target** and left its **source** at the prior:
information flowed one way, and the surrogates were never evidence.

**Added** `meta/joint_sampling.py`:

- `load_surrogates_for_ir` rehydrates the IR's surrogates. Three resolution routes,
  because the builder stores the resolved artifact_id and discards the path: a
  literal path, the spec's `surrogate_refs`, then the registry. A placeholder
  artifact (no `backend_payload`) raises a message naming the fix rather than a
  KeyError three frames down.
- `sample_joint` runs random-walk Metropolis over the joint density, adapting the
  proposal during tuning and freezing it for the retained draws. Deterministic
  couplings are computed from their source rather than sampled — proposing them
  freely would be rejected essentially always and the chain would stall.
- `sample_joint_to_store` writes the same files as the existing sampler, so
  `meta list` and the notebooks keep working either way.
- CLI: `bayesmm meta sample --method {propagate,joint}`, default unchanged.
  Opt-in because joint sampling is far slower and changes what the numbers mean.

**Correctness is checked against a right answer, not against itself.** For normal
priors and a linear-Gaussian coupling the joint is Gaussian in closed form, so
`test_gaussian_link_matches_closed_form` compares sampled mean, sd and correlation
with the analytic values. A sampler targeting the priors instead fails it: the
prior mean of y is 0.0 against a joint mean of 0.95, and the prior sd 2.0 against
0.75. Three further tests pin that a coupling tightens its SOURCE (the asymmetry
propagation has), that a deterministic coupling holds exactly in every draw, and
that a misspecified model is reported rather than sampled through.

**On the real four-model TCR metamodel**, conditioned on four fitted surrogates:
prior sd -> joint sd, contact_fraction 0.139 -> 0.099, cd45_boundary_density
85.1 -> 58.3, mean_lck_activity 140 -> 13.7, ptcr_fraction 0.336 -> 0.235. 2.6 s
for 400 draws, accept rate 0.32.

**Why Metropolis and not NUTS**: a fitted surrogate's `log_prob` is a black box
with no gradient, so a gradient-free sampler is what the model admits. That costs
efficiency, not correctness. Expressing the model as a PyTensor graph would unlock
NUTS and needs every surrogate backend to expose a symbolic log_prob — the natural
next step, and a real piece of work.

**Tutorials updated.** T7 gains a section contrasting the two methods and running
the two-variable case with its closed form printed alongside; T7/T8's own specs use
placeholder artifacts, so `--method joint` on them reports that clearly. The TCR
notebook 03 and Tutorial_0 have their "this is not conditioning" caveats re-scoped
to the default method.

### 2026-08-07: Framework bug — a shared store broke every surrogate fit

`_load_from_centralized_sweeps` globs every `sweep_rows.csv` under the store and
indexed the surrogate's input columns on each row, so a store holding more than
one model's sweeps raised `KeyError: '<input>'` on the first foreign row. Fitting
ANY surrogate therefore broke as soon as a second model had been swept.

That is not an exotic layout — it is what "centralized sweep store" means, and it
is exactly how `projects/tcr_signaling` is arranged: four partial models sharing
one `store/`. It is why the surrogates there had never been fitted, and why
`metamodel.tcr_signaling.json` referenced four artifacts that did not exist.

Fix: skip sweeps whose header does not provide this surrogate's inputs, and if
nothing matches, say so — naming the inputs sought and how many foreign sweeps
were passed over, so the skip cannot become silent.

`tests/test_dataset_multi_model_store.py` pins all three edges: a foreign sweep
is ignored, a store with only foreign sweeps still raises with a useful message,
and the status filter was not loosened in the process. Verified bidirectional —
the first test raises `KeyError: 'a'` without the fix.

With this and the run-directory fix, `projects/tcr_signaling` notebooks 01-04
execute end to end for the first time (~3 min), and the metamodel samples:
14 variables, 16 factors, 2000 draws.

### 2026-08-07: Framework bug — a relative `storage.root` silently lost every output

`_run_single_point` built its run directory as `Path(spec.storage.root)/...`,
which is relative. The adapter hands that to the model as `--run-dir`, but the
model subprocess runs with `cwd=REPO_ROOT` — not the cwd of whoever invoked
`bayesmm`. The two therefore resolved to different directories: the model wrote
its outputs under REPO_ROOT while `parse_outputs` looked under the invoking cwd.
Every point failed with "Output parsing failed: No such file or directory". The
outputs existed; nobody looked where they were.

It hid because every test and example invoked the CLI **from the repo root**,
where the two paths coincide. It surfaced only when the `projects/tcr_signaling`
notebooks ran it from the submodule root — 21/21 and 64/64 points failing, with
the summary line reporting nothing more useful than a failure count.

Fix: resolve the run directory to an absolute path. Verified both ways —
21/21 successful from the submodule root, 21/21 from the parent root.

`tests/test_run_dir_cwd_independence.py` pins the property rather than the
implementation: a sweep must succeed when invoked from an arbitrary cwd.
Confirmed bidirectional — it passes with the fix and fails with "9/9 points
failed" without it. That the whole existing suite passed while this was broken
is the point: the tests all ran from the one directory where it worked.

### 2026-08-07: Pin `sbi<0.27`; reconcile conda envs; repair submodule + hook setup
- **CI had been red since 2026-05-15 without anyone noticing.** The last green
  run was `a34b3e0`; no runs happened between then and 2026-08-06, so the break
  was pure PyPI drift, not a code change. `src/` and `tests/` were untouched.
- **`sbi` pinned to `>=0.22,<0.27`.** On sbi 0.27.0 the NPE trainer no longer
  converges within its default 100 epochs on the test problems and warns
  "Maximum number of epochs ... reached"; `filterwarnings = error` escalates
  that to hard failures in 5 tests. `pyproject.toml` already documented the
  supported range as 0.22..0.26, so 0.27 was never validated. Reproduced in a
  clean venv matching CI's install, and verified green after the pin (sbi
  resolves to 0.26.1). Lift once 0.27+ is checked against the surrogate suite —
  `backends.py::max_num_epochs` (default 120) is the likely knob.
- **Conda env files reconciled with the documented three envs.** README and
  `tutorials/README.md` told users to create `bayesian-metamodeling`, while
  CLAUDE.md, the submodule docs and both githooks reference `py314_bayesmm` /
  `py312_bayesmm_pymc` / `py312_bayesmm_sbi`. The hooks fall back to
  `~/miniconda3/envs/py314_bayesmm/bin/{ruff,pytest}` **by name**, so an env
  built from the old file could not satisfy them. `environment.yml` now builds
  `py314_bayesmm` and carries `pytest`/`ruff`/`cmake` (previously absent — so
  `make fast` and `make lint` could not run in it); backends split into
  `environment-pymc.yml` and `environment-sbi.yml`.
- **`python_abi=*_cp314` pinned** in `environment.yml`: conda-forge resolves a
  bare `python=3.14` to the free-threaded build, under which `import _brotli`
  raises a GIL `RuntimeWarning` that `filterwarnings = error` turns into a
  collection error — the suite cannot even start.
- **Ruff scoped to the framework.** `ruff check .` from the root reported 46
  errors, all inside `projects/tcr_signaling`, which root config does not
  govern. Added `projects/` and `*.md` to `extend-exclude` (this ruff formats
  fenced code blocks, so the hook's in-place `ruff format .` was silently
  rewriting `CodeDesign.md`). CI was unaffected — it already scoped to
  `src tests`.
- **`githooks/pre-commit` Status.md gate was dead.** It called `rg`, which is
  not installed; inside an `if` condition exit 127 reads as false, so the hook
  reported success while enforcing nothing. Switched to POSIX `grep`.
- **Submodule now tracks `main` over HTTPS.** `tcr_signaling` `main` was 19
  commits stale; fast-forwarded to the `feature/ks-metamodel-sweep` tip and
  deleted the four fully-merged branches. The SSH remote authenticates as
  `ravehlab`, which has no push access to `barakr/tcr_signaling`. Added
  `update = rebase` to `.gitmodules` — it had been in `.git/config`, which is
  never cloned, so every fresh clone still landed in detached HEAD.
- **Three independent CI signals, deliberately not merged.** `CI` (here) =
  framework broken; `KS model CI` (tcr_signaling repo) = KS model broken;
  `Interface CI` (here) = the two no longer fit. Keeping them separate avoids
  a submodule toolchain failure colouring the framework's status.
- **Interface contract tests added** (`tests/test_submodule_interface.py`).
  Nothing tested the framework against the case study before: the framework
  suite never checks out the submodule (`submodules: false` in CI) and the
  submodule suite imports no framework code, so a change to `spec/*.py` could
  invalidate all 9 case-study specs unnoticed. Validates each spec against the
  schema its filename prefix selects, plus schema_version presence and
  metamodel→surrogate name references. Pure pydantic — no CMake, no Metal.
- **`Interface CI` runs on every push, not `paths: projects/**`.** The contract
  breaks from either side and the framework side is likelier; a path filter on
  `projects/` would never fire for a `src/spec/` edit. Path filters fail open —
  when wrong they give silence, not an error.
- **`REQUIRE_SUBMODULE_INTERFACE=1`** makes "submodule absent" a failure rather
  than a skip in that job, so it cannot pass green having run nothing. Same
  concern as the KS suite's skip guard.
- Note: `bayesmm validate` only ever applies `ModelSpec`. Pointing it at a
  surrogate or metamodel spec reports a misleading "Extra inputs are not
  permitted" that looks like spec rot but is not — the interface tests
  dispatch on the filename prefix instead.

### Tutorial review (2026-08-07)

- **T5 and T9 crashed in `py314_bayesmm`, the documented main env.** Both call
  `bayesmm surrogate fit` with the `pymc_gp` backend and had no preflight, so a
  missing PyMC produced a mid-notebook `RuntimeError` rather than a skip. T6
  already solved this for SBI; its idiom was applied verbatim. All ten now pass
  in the main env, degrading with an actionable banner.
- **The tutorial integration test had never run in CI.** It is marked `slow`,
  and CI runs `-m "not slow"` — which is why the T5/T9 breakage survived. Added
  the `Deep CI` workflow (weekly + manual) to run the slow suite with every
  backend installed.
- **`REQUIRE_TUTORIAL_BACKENDS=1` added.** Every backend-gated tutorial degrades
  to a clean "SKIPPED" path and still reports its self-check OK — correct for a
  learner, worthless as verification, and the same false-success shape as the
  original post-mortem. The flag makes any preflight skip a failure. Verified:
  with pymc+sbi installed locally, exactly one tutorial fails under the flag —
  T2, because `libroadrunner` is in no conda env. Deep CI installs `[biomodels]`
  to close that, so T2's BioModels sweep gets exercised for the first time since
  it was fixed.
- **Verified for real, not just for exit code**: 10/10 in `py314_bayesmm` (37s,
  backend steps skipped), 10/10 in `py312_bayesmm_pymc` (235s) and
  `py312_bayesmm_sbi` (237s). The 6× runtime difference is the evidence that GP
  fitting actually ran rather than being skipped.
- **Pedagogical audit — first pass was wrong.** A keyword scan reported
  objectives 3/10 and recap 4/10; the notebooks use "Learning aims" and
  "Scientific checkpoint", so the real figures were 9/10 and 8/10. The material
  was already substantially pedagogical (T1 in particular has a
  predict-then-verify exercise and plants a question T5 answers). Corrected
  before acting on it — the flawed measurement would have justified a needless
  rewrite of all ten notebooks.
- **Real gaps closed** (~20 markdown cells, additive; no existing cell altered):
  troubleshooting 2→9 (T0 excepted, being orientation), predict-before-you-run
  5→9, inter-tutorial threading 6→10, recap 7→10, objectives 9→10.
- **`tutorials/README.md` rewritten.** It claimed troubleshooting in every
  notebook (there were two) and a visual checkpoint in every notebook (T3 had
  none). Now states the course arc, the per-tutorial question/capability table,
  and the env matrix.

#### Sanctioned-skip registry, and a coverage gap it exposed (2026-08-07)

- **Every skip in Deep CI is now classified** against a registry of sanctioned
  reasons and rendered in the job summary as `verdict | test | reason | why
  that's OK`. Unsanctioned skips emit an annotation and fail the job. The `full`
  job is strict: with everything installed the only defensible skips are the
  three external constraints below.
- **mpi4py installed, and the test actually launched.** `test_mpi_sweep_integration`
  had never run anywhere — mpi4py was in no conda env and no CI job. Installing
  it was necessary but not sufficient: the test needs >=2 ranks, so under a
  plain `pytest` it skips regardless. The full job now also runs it under
  `mpirun --oversubscribe -n 2`.
- **The strict check immediately caught two skips I had not sanctioned** — the
  MPI rank requirement and the BioModels 403 — which is the check working, not
  failing. Both are external constraints rather than missing dependencies, so
  both are now sanctioned with written justifications.
- **Gap found and NOT papered over: `notebooks/01-04` run in no CI job.** They
  drive `ks_gpu` by subprocess, so they need the submodule's compiled native
  model *and* the framework, and they run real sweeps (>10 min locally). An
  attempt to run them from Interface CI was reverted: building the KS model
  there would cross the submodule boundary that workflow exists to police, and
  would turn a seconds-long per-push signal into a minutes-long one. The
  submodule's own CI covers `notebooks/models/kinetic_segregation/KS_*`, a
  different set. Closing this needs a deliberate choice about which side pays
  (parent builds KS, or submodule installs the framework); until then the skip
  is sanctioned with that reason rather than pretended away.

#### Policy: no silent no-ops; dev envs must match what CI installs (2026-08-07)

- **Rule 12 added to CLAUDE.md** — "a gate that can skip must be able to fail for
  skipping" — with a *Guarding against silent no-ops* section listing the five
  instances found today and a table of the mechanisms that already exist, so the
  next suite reuses them rather than reinventing. The test to apply: *if every
  step silently did nothing, would this still be green?*
- **Conda env pins replaced with pyproject's ranges.** The exact pins were not
  cosmetic drift, they were the mechanism: `sbi==0.23.3` lists `pymc>=5.0.0` as a
  HARD dependency, so `py312_bayesmm_sbi` always contained PyMC and was never
  sbi-only. It structurally could not reproduce CI's sbi-only job — which is
  exactly why Tutorial 6's missing PyMC guard was invisible locally and only
  surfaced in CI. From 0.26 pymc is an optional extra. Rebuilt: sbi 0.26.1,
  torch 2.13.0, pymc absent — identical to what CI resolves, and T6 now
  reproduces the CI behaviour locally (skips Step 4, self-check green).
  Trade-off accepted: exact pins give reproducibility, ranges give fidelity to
  what users actually get; for a *dev* env fidelity wins, and exact versions
  behind a published result belong in that project's own Status.md.
- **Notebook tooling added to both backend env files.** Without nbclient,
  `pytest -m slow tests/test_tutorial_integration.py` importorskips and reports
  green having run nothing — rule 12 applied to the envs themselves.
- **CI trigger paths documented as a future consideration, not a rule.** Deep CI
  is the only workflow using `paths:` and it is now correct. Recorded that path
  filters fail open, that the filter must cover everything the job executes, and
  that the escape hatch is simply to drop them (Actions minutes are free on
  public repos).

#### Deep CI's first matrix run found three real bugs (2026-08-07)

The matrix and the REQUIRE flag were justified on the argument that a single
all-backends job hides env-specific breakage. Its first run substantiated that
immediately — none of the three reproduced on macOS.

- **T6 needed PyMC as well as SBI.** Step 4 compares the SBI surrogate against
  T5's `pymc_gp` surrogate but guarded only on `SBI_AVAILABLE`, so the sbi-only
  job raised. Same unguarded-backend bug as T5/T9. Now detects PyMC separately
  and skips only the comparison.
- **`test_biomodels_slow` asserted a column that never existed.** It read
  `time_series__json`; `_flatten_nested` only emits a whole-payload blob when a
  member cannot be flattened, and here every member can, so the data lands in
  `time_series__{n_points,t0,t1,columns__N,rows__json}`. The assertion had never
  passed — the test needs libroadrunner (installed in no env until now) and is
  `slow`, so it was excluded from every CI run. Rewritten against the real
  schema and against values, including a check that not every species is zero,
  so a hollow simulation cannot pass.
- **biomodels.org returns 403 to GitHub runner IPs.** T2 failed 11/11 DOE points
  in CI while passing locally. Not a code bug: the service refuses cloud address
  ranges. The `403` was only visible after adding a step that surfaces
  `sweep_logs.jsonl` as annotations — Actions *logs* need an authenticated token
  to fetch, but *annotations* do not, so a red run was otherwise undiagnosable
  from its URL.
  - Fix: vendored `examples/biomodels/MODEL1907260003.xml` (40K). Tests pin
    `local_sbml_path` at it, so CI verifies parse/simulate/mapping/flattening.
    T2 keeps fetching by default — that is part of what it teaches — and probes
    the URL first, falling back to the vendored copy when offline or blocked.
    The fetch is covered by a *separate* test, `test_biomodels_adapter_fetch_slow`,
    which calls the adapter directly (not via a sweep, where a failed download
    surfaces as "N/N points failed" with the cause buried in sweep_logs.jsonl) and
    skips with an explicit HTTP-code reason where the service refuses. So the
    download IS tested on a developer machine and only unverifiable on hosted CI.
    First attempt got this wrong: pinning `local_sbml_path` in the one existing
    test made the fetch untested *everywhere*, not just in CI.

#### Decisions taken with the user (2026-08-07)

- **Deep CI runs nightly, not weekly** (03:00 UTC). Tutorials are user-facing; a
  break sitting for a week would be found by a learner before CI found it.
- **Deep CI runs a 4-way matrix mirroring the documented envs**, not one
  all-backends job. T5/T9 crashed *only* in the backend-less main env, which a
  single full-install job would never have caught. The three partial jobs prove
  tutorials DEGRADE correctly (skips allowed); the `full` job sets
  `REQUIRE_TUTORIAL_BACKENDS=1` and proves the science RUNS (no skips allowed).
- **Fourth env added: `environment-biomodels.yml` → `py312_bayesmm_biomodels`.**
  libRoadRunner/tellurium are heavy and PyPI-only and only T2 needs them, so
  they do not belong in `environment.yml`; but leaving them installed nowhere
  meant T2 could only ever be debugged through CI logs — which is the condition
  that let its silent failure survive. Own env, symmetric with pymc and sbi.
- **T0 troubleshooting and T3 plot added** (reversing the earlier call to leave
  them). T0's table covers the kernel-vs-env mismatch that causes most newcomer
  failures, and is arguably the highest-value one in the course despite T0
  running no models. T3's figure is a ModelSpec anatomy map showing which error
  each block raises and marking the two cross-block contracts — which is where
  the confusing errors come from, since the reported `loc` is often not the
  field just edited. Every notebook now has a plot and a troubleshooting table,
  so the README needs no exceptions.

### 2026-03-05: Fix KS model MC loop + self-contained example specs
- **MC loop fix**: Changed from single-particle stepping to full sweeps — each
  `n_steps` iteration now updates every molecule and every grid cell once,
  matching standard MC convention. Previous behavior updated ~3 molecules per
  step (150 molecules / 500 steps), far too few for equilibration.
- **n_steps auto-scaling**: Changed from `max(500, time*100)` to `max(50, time*5)`
  since each step now does ~1000x more work (full sweep vs single particle).
- **Default grid_size**: Increased from 32 to 64 for better spatial resolution.
- **Per-point seed derivation**: `__main__.py` now derives a unique reproducible
  seed per DOE point via `seed + hash(inputs)`, eliminating correlated MC noise
  across the parameter sweep.
- **Self-contained example specs**: Created `examples/specs/` with model, pymc_gp,
  and sbi_npe specs. Example script now references local specs instead of
  global `specs/` directory. Moved `specs/surrogate.kinetic_segregation.sbi_npe.json`
  to `examples/specs/`.
- **Tests updated**: All n_steps values reduced (full sweeps need far fewer
  iterations); grid_size and molecule counts reduced for speed. All 54
  submodule tests and 272+ root fast tests pass.

### 2026-03-05: Co-locate model tests within each model subdirectory
- Moved `tests/test_kinetic_segregation.py` into `projects/tcr_signaling/models/kinetic_segregation/tests/`
  split into `test_potentials.py`, `test_model.py`, `test_cli.py`
- Added new test suites for `membrane_topography`, `lck_activity`, `tcr_phosphorylation`
- Added `projects/tcr_signaling/pytest.ini` and `conftest.py` for standalone test discovery
- Root `pytest.ini` updated to discover submodule tests via `testpaths`
- Total: 54 submodule tests, 272 fast tests from root (all passing)

### 2026-03-05: Add TCR signaling case study (Neve-Oz, Sherman & Raveh 2024)
- Created `projects/` top-level directory for real-world scientific reproductions
- First project: `projects/tcr_signaling/` — reproduces Bayesian metamodeling of
  early TCR signaling from Frontiers in Immunology 2024
- 4 partial models: membrane topography, kinetic segregation, Lck activity, TCR phosphorylation
- 4 ModelSpecs (2 grid DOE, 2 sobol DOE), 4 SurrogateSpecs, 1 MetaModelSpec
- 4 Jupyter notebooks for exploration, surrogate fitting, inference, and figure reproduction
- All model specs pass `bayesmm validate`; all fast tests pass

### 2026-03-04: Rename package from metamodeler to bayesian-metamodeling
- pip name: `bayesian-metamodeling`
- import name: `bayesian_metamodeling`
- CLI command: `bayesmm` (was `mm`)
- Source directory: `src/bayesian_metamodeling/` (was `src/metamodeler/`)
- Conda envs: `py314_bayesmm`, `py312_bayesmm_pymc`, `py312_bayesmm_sbi`

## Folder structure
- src/bayesian_metamodeling/: library code
- examples/: example specs and toy models
- projects/: real-world scientific case studies using the framework
- tutorials/: modular tutorial curriculum, tutorial specs, and notebook entrypoint
- tests/: unit and integration tests
- tmp/: scratch and temporary files, not committed
- githooks/: git hooks that enforce formatting, lint, and fast tests

## Implemented
- Prompt 17 implemented: centralized sweep output + synchronized execution modes (2026-02-15):
  - Replaced per-point numeric result persistence in `bayesmm run` with one centralized sweep artifact set:
    - `sweep_rows.csv`
    - `sweep_manifest.json`
    - `sweep_logs.jsonl`
  - Added synchronized execution modes in `RunnerSpec` and `bayesmm run`:
    - `runner.sweep_mode`: `serial` (default), `parallel_local`, `mpi`
    - `runner.workers` (parallel-local only; defaults to runner CPUs)
  - Single-writer guarantees:
    - serial: direct writer
    - parallel_local: coordinator writes centralized files
    - mpi: rank 0 writes centralized files; non-root ranks synchronize via broadcast
  - Added centralized sweep helpers:
    - `src/bayesian_metamodeling/storage/sweep_store.py`
  - Added sweep persistence contract:
    - `src/bayesian_metamodeling/storage/run_store.py` (`persist_sweep`)
    - run registry now tracks sweep records with `sweep_rows_path`, `sweep_manifest_path`, `sweep_logs_path`
  - Updated surrogate dataset loading to support centralized sweep CSV stores (with legacy `runs/*` fallback):
    - `src/bayesian_metamodeling/surrogates/dataset.py`
  - Tutorial updates:
    - `tutorials/Tutorial_1.ipynb` now reads centralized `sweep_rows.csv` and renders two heatmaps (`sum`, `product`)
    - helper module for Tutorial 1 heatmap loading:
      - `src/bayesian_metamodeling/tutorials/toy_heatmap.py`
  - Test updates:
    - `tests/test_run_pipeline.py` now validates centralized sweep CSV and serial-vs-parallel equivalence
    - `tests/test_sweep_store.py` added for flattening and deterministic CSV order
    - `tests/test_tutorial_toy_heatmap.py` added for Tutorial 1 CSV-to-heatmap parsing
    - `tests/test_surrogate_dataset_loading.py` now covers centralized sweep dataset loading
    - `tests/test_modelspec_validation.py` now covers `sweep_mode`/`workers`
    - `tests/test_biomodels_slow.py` updated to consume centralized sweep rows
    - optional MPI integration test:
      - `tests/test_mpi_sweep_integration.py`
  - Schema/docs updates:
    - `src/bayesian_metamodeling/spec/modelspec.schema.json`
    - `README.md`, `tutorials/README.md`, `PRD.md`, `TechSpec.md`, `CodeDesign.md`, `TEST_PLAN.md`, `PROMPT_TO_CODEX.md`
- Runner/env portability + optional backend test controls (2026-02-12):
  - Added optional `runner.execution_env` to `ModelSpec` (`default={}`), currently supporting:
    - `conda_env` (validated key; whitespace normalized).
  - Plumbed `runner.execution_env` through adapter materialization into local process runner:
    - `src/bayesian_metamodeling/adapters/base.py`
    - `src/bayesian_metamodeling/adapters/python_cli.py`
    - `src/bayesian_metamodeling/adapters/biomodels_sbml.py`
    - `src/bayesian_metamodeling/runners/local_process.py`
  - Local runner behavior:
    - If `conda_env` is set, run commands via `conda run -n <conda_env> ...`.
    - If no `conda_env` and command starts with `python` but no `python` on PATH, fallback to current `sys.executable`.
  - Removed hardcoded environment names from runtime backend dependency error messages:
    - now uses generic `conda install -n <env_name> ...` guidance.
  - Added optional backend test controls and reporting:
    - env flag: `MM_SKIP_OPTIONAL_BACKEND_TESTS=1`
    - pytest report header now prints optional backend availability and skip-flag state
    - optional backend tests are marked and can be skipped explicitly via the flag
    - files:
      - `tests/backend_support.py`
      - `tests/conftest.py`
      - `tests/test_surrogate_backends.py`
      - `tests/test_surrogate_backend_hardening.py`
      - `pytest.ini`
  - Added tests for env execution behavior and ModelSpec validation:
    - `tests/test_local_process_runner.py`
    - `tests/test_modelspec_validation.py`
  - Regenerated schema artifact:
    - `src/bayesian_metamodeling/spec/modelspec.schema.json`
  - Created permanent backend-specific conda environments:
    - `/Users/barak/miniconda3/envs/py312_bayesmm_pymc`
    - `/Users/barak/miniconda3/envs/py312_bayesmm_sbi`
  - Renamed PyMC env prefix to match actual Python version:
    - removed `/Users/barak/miniconda3/envs/py314_bayesmm_pymc`
    - active env is `/Users/barak/miniconda3/envs/py312_bayesmm_pymc`
  - Installed backend stacks:
    - `py312_bayesmm_pymc`: Python `3.12.12`, `pymc 5.27.1`, `arviz 0.23.4`
    - `py312_bayesmm_sbi`: Python `3.12.12`, `torch 2.10.0`, `sbi 0.23.3`
  - Verified both PyMC tracks in the renamed env:
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTENSOR_FLAGS='cxx=' PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_pymc/bin/python -m pytest -q tests/test_surrogate_backends.py -k pymc_gp_backend_fit_sample_and_logprob` -> `1 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTENSOR_FLAGS='cxx=' PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_pymc/bin/python -m pytest -q tests/test_metamodel_sampling.py -k two_surrogates` -> `1 passed`
  - Validation commands (passed):
    - `ruff format .`
    - `ruff check .`
    - `pytest -q -m "not slow"`
- Scaffold created:
  - Python package skeleton under `src/bayesian_metamodeling/` including target subpackages from TechSpec.
  - `pyproject.toml` added with setuptools build, Python package metadata, and CLI entry point `mm`.
  - Minimal CLI scaffold at `src/bayesian_metamodeling/cli/main.py`.
  - Baseline pytest smoke test at `tests/test_scaffold_smoke.py`.
  - Git hooks implemented in `githooks/`:
    - `pre-commit` runs format/lint/fast tests, blocks main/master commits by default, and enforces `Status.md` staging when `src/` or `examples/` are staged.
    - `pre-push` runs fast tests.
    - `commit-msg` enforces conventional commit style.
  - Hook logs path standardized to `tmp/hook_logs/`.
  - `tmp/` confirmed gitignored.
- Design validation artifacts created:
  - `CodeDesign.md` added with explicit spec family (`ModelSpec` / `SurrogateSpec` / `CouplingSpec` / `MetaModelSpec`) and concrete workflow mapping.
  - Three-model coupling example spec added:
    - `examples/coupled/spec.three_model_coupling.json`
  - BioModels execution + surrogate-spec examples added:
    - `examples/biomodels/spec.model1907260003.json`
    - `examples/biomodels/surrogate.model1907260003.json`
  - `TechSpec.md` and `README.md` updated to reference design-validation scenarios and `CodeDesign.md`.
- Prompt 1 implemented:
  - Added typed Pydantic v2 spec model hierarchy in `src/bayesian_metamodeling/spec/modelspec.py`:
    - `ModelSpec`, `VariableSpec`, `AdapterSpec`, `RunnerSpec` and nested contract models.
  - Added schema export helper in `src/bayesian_metamodeling/spec/schema.py`.
  - Added JSON schema artifact:
    - `src/bayesian_metamodeling/spec/modelspec.schema.json`
  - Added `bayesmm validate <spec>` command with actionable validation output in:
    - `src/bayesian_metamodeling/cli/main.py`
  - Added fast tests in:
    - `tests/test_modelspec_validation.py`
  - Added shared test path setup in:
    - `tests/conftest.py`
- Prompt 2 implemented:
  - Added DOE planner module in:
    - `src/bayesian_metamodeling/designs/planner.py`
  - Added strategy support:
    - `grid` cartesian product planning
    - `sobol` deterministic low-discrepancy planning with bounds scaling
  - Added `bayesmm plan <spec>` CLI command with deterministic preview output.
  - Added fast tests in:
    - `tests/test_doe_planner.py`
- Prompt 3 implemented:
  - Added adapter interfaces and registry:
    - `src/bayesian_metamodeling/adapters/base.py`
    - `src/bayesian_metamodeling/adapters/python_cli.py`
    - `src/bayesian_metamodeling/adapters/registry.py`
  - Added local process runner:
    - `src/bayesian_metamodeling/runners/local_process.py`
  - Added run store + registry with provenance and stdout/stderr references:
    - `src/bayesian_metamodeling/storage/run_store.py`
  - Added CLI commands:
    - `bayesmm run <spec>`
    - `bayesmm runs list`
    - `bayesmm runs show <run_id>`
  - Added toy executable program:
    - `examples/toy_program/run.py`
  - Added fast end-to-end integration test:
    - `tests/test_run_pipeline.py`
- Prompt 4 implemented:
  - Added BioModels SBML adapter baseline:
    - `src/bayesian_metamodeling/adapters/biomodels_sbml.py`
  - Added SBML worker script for simulation:
    - `src/bayesian_metamodeling/adapters/biomodels_worker.py`
  - Adapter registry now resolves `biomodels_sbml_adapter_v1`.
  - Added BioModels example spec:
    - `examples/biomodels/spec.prompt4.model1907260003.json`
  - Added slow integration test:
    - `tests/test_biomodels_slow.py`
- Prompt 5 implemented:
  - Added typed placeholder surrogate spec:
    - `src/bayesian_metamodeling/spec/surrogate.py`
  - Added typed placeholder metamodel spec:
    - `src/bayesian_metamodeling/spec/metamodel.py`
  - Added CLI placeholder commands:
    - `bayesmm surrogate fit <spec>`
    - `bayesmm surrogate eval <spec>`
    - `bayesmm meta build <spec>`
  - Added fast tests for placeholder CLI wiring:
    - `tests/test_surrogate_meta_placeholders.py`
- Prompt 6 implemented:
  - Refined `SurrogateSpec` to backend-neutral contract fields (`kind`, `inputs`, `outputs`, `backend`, `backend_config`, `dataset_ref`, `seed`).
  - Added backend-neutral `SurrogateModel` wrapper interface:
    - `src/bayesian_metamodeling/surrogates/base.py`
  - Added metamodel IR schema and helpers:
    - `src/bayesian_metamodeling/meta/ir.py`
  - Added compiler boundary:
    - `src/bayesian_metamodeling/meta/compiler.py`
    - `compile_metamodel(..., backend=\"pymc\")` implemented
    - `compile_metamodel(..., backend=\"numpyro\")` stubbed with clear `NotImplementedError`
  - Added metamodel IR builder + artifact store:
    - `src/bayesian_metamodeling/meta/builder.py`
    - `src/bayesian_metamodeling/storage/meta_store.py`
  - Updated CLI:
    - `bayesmm meta build <spec>` now writes IR artifact to `tmp/metamodel_ir/` and registers it in `tmp/meta_registry.json`
  - Added tests:
    - IR roundtrip serialization: `tests/test_meta_ir_roundtrip.py`
    - Compiler smoke with mocked surrogate factor: `tests/test_meta_compiler_smoke.py`
    - Generic fit-quality tests with increasing challenge: `tests/test_surrogate_fit_quality_generic.py`
- Prompt 7 implemented:
  - Added backend implementations behind wrapper contract:
    - `pymc_gp` (pragmatic linear-Gaussian baseline API)
    - `sbi_npe` (pragmatic linear-Gaussian baseline API)
    - module: `src/bayesian_metamodeling/surrogates/backends.py`
  - Added dataset loader from canonical run store:
    - `src/bayesian_metamodeling/surrogates/dataset.py`
    - no implicit downsampling/thinning
  - Added backend-neutral surrogate artifact persistence:
    - `src/bayesian_metamodeling/storage/surrogate_store.py`
    - includes spec digest, dataset digest, variable lists, seed, dependency versions
  - Added surrogate fit/eval service layer:
    - `src/bayesian_metamodeling/surrogates/service.py`
  - Updated CLI:
    - `bayesmm surrogate fit surrogate.json`
    - `bayesmm surrogate eval surrogate.json --inputs '<json>' --n 1000`
  - Added examples:
    - `examples/surrogates/surrogate.toy.pymc_gp.json`
  - Added fast tests:
    - `tests/test_surrogate_backends.py`
    - updated `tests/test_surrogate_meta_placeholders.py` for real fit/eval flow
- Prompt 8 implemented:
  - Added MetamodelSpec v1 fields in `src/bayesian_metamodeling/spec/metamodel.py`:
    - `ppl_backend`, `surrogate_refs`, `variables`, `couplings`, `priors`
  - Updated IR builder to load surrogate artifacts and include surrogate likelihood factors:
    - `src/bayesian_metamodeling/meta/builder.py`
  - Added metamodel sampling module and artifacts:
    - `src/bayesian_metamodeling/meta/sampling.py`
    - stores `inference_data.json` and canonical `samples_dataset.json`
    - registry: `tmp/metamodel_samples_registry.json`
  - Updated CLI:
    - `bayesmm meta build metamodel.json`
    - `bayesmm meta sample metamodel.json --draws D --tune T --chains C --seed S`
    - backend behavior:
      - `pymc`: sampling path implemented
      - `numpyro`: explicit `NotImplementedError` pending Prompt 9
  - Added example metamodel specs/artifacts:
    - `examples/metamodels/metamodel.simple.json`
    - `examples/coupled/spec.three_model_coupling.json` updated to v1 structure
  - Added fast synthetic integration test:
    - `tests/test_metamodel_sampling.py`
- Prompt 9 implemented:
  - Enabled `compile_metamodel(ir, backend=\"numpyro\")` path:
    - `src/bayesian_metamodeling/meta/compiler.py`
  - Enabled `ppl_backend: \"numpyro\"` sampling mode using same metamodel spec interface:
    - `src/bayesian_metamodeling/meta/sampling.py`
  - Kept canonical sample storage format aligned with pymc path:
    - `inference_data.json`
    - `samples_dataset.json`
  - Added fast backend integration test:
    - `tests/test_metamodel_sampling_numpyro.py`
  - Added backend-switch documentation and known numerical differences in `README.md`.
- Prompt 10 implemented:
  - Added guided CLI command:
    - `bayesmm tutorial`
  - Added artifact listing commands:
    - `bayesmm surrogate list`
    - `bayesmm meta list`
  - Hardened artifact metadata fields across surrogate/meta artifacts:
    - `spec_digest`
    - `dataset_digest`
    - `dependency_versions`
    - `seed`
  - Added end-to-end quickstart block in `README.md`.
  - Added fast UX/repro tests:
    - `tests/test_cli_ux_commands.py`
- Documentation update:
  - Linked tutorial notebooks from:
    - `README.md`
    - `tutorials/README.md`
  - Refreshed tutorial after Prompts 6-10 to reflect real commands and backend behavior:
    - `bayesmm tutorial`
    - `bayesmm surrogate list`
    - `bayesmm meta list`
    - real surrogate fit/eval and metamodel build/sample flow
- Tutorial architecture update (modular track):
  - Added `tutorials/` subfolder with 9-part progression and notebook hub:
    - `tutorials/Tutorial_0.ipynb`
    - `tutorials/Tutorial_1.ipynb` ... `tutorials/Tutorial_9.ipynb`
  - Added tutorial-specific runnable specs and artifact stubs:
    - `tutorials/specs/`
    - `tutorials/artifacts/`
  - Added standalone vs serial execution guidance, prerequisites, estimated times, checkpoints, and troubleshooting in each notebook.
  - Converted tutorials to notebook-only delivery by retiring `tutorials/Tutorial_*.md` files.
  - Re-pointed top-level docs:
    - `README.md` now links to notebook-only tutorial track.
    - tutorials are indexed from `tutorials/README.md` and `tutorials/Tutorial_0.ipynb`.
- Prompt 11 implemented:
  - Replaced placeholder `pymc_gp` backend with a real PyMC probabilistic fit path in:
    - `src/bayesian_metamodeling/surrogates/backends.py`
  - Added posterior-based surrogate methods (`sample`, `log_prob`, `summary`) backed by PyMC posterior draws.
  - Added actionable missing-dependency error for `pymc_gp` with conda/pip install guidance.
  - Added warning-safe PyMC import path to avoid ArviZ startup warning failures under `filterwarnings = error`.
  - Added backend dependency version capture and persistence into surrogate artifacts:
    - `src/bayesian_metamodeling/surrogates/service.py`
    - `src/bayesian_metamodeling/storage/surrogate_store.py`
  - Added optional dependency extra for PyMC:
    - `pyproject.toml`
  - Updated tests for real PyMC backend behavior and graceful skip/error handling:
    - `tests/test_surrogate_backends.py`
  - Strengthened PyMC fit test with a real-learning quality assertion (bounded predictive MSE on synthetic mapping).
  - Updated user docs with backend install and behavior notes:
    - `README.md`
    - `tutorials/Tutorial_0.ipynb`
- Prompt 12 implemented:
  - Replaced placeholder `sbi_npe` backend with real SBI NPE fit/eval flow in:
    - `src/bayesian_metamodeling/surrogates/backends.py`
  - Added dependency guards with actionable runtime errors for missing `sbi` / `torch`.
  - Added warning-safe SBI training path to ignore known non-fatal 1D-flow warning under `filterwarnings = error`.
  - Added persisted SBI backend payload format:
    - model type `sbi_npe_posterior`
    - serialized posterior payload via torch-save + base64
    - normalization metadata (`x_mean`, `x_scale`, `y_mean`, `y_scale`)
  - Added optional dependency extra for SBI:
    - `pyproject.toml`
  - Added/updated tests:
    - real SBI backend fit/eval test (skip-safe when dependency missing)
    - SBI missing-dependency actionable error test
    - backend selection helpers for integration tests so fast suite remains stable without optional deps
  - Updated docs with SBI install and verification commands:
    - `README.md`
    - `tutorials/Tutorial_0.ipynb`
- Prompt 13 implemented:
  - Added explicit backend-config validation contract with actionable errors:
    - `src/bayesian_metamodeling/surrogate_config.py`
    - wired into `SurrogateSpec` validation in `src/bayesian_metamodeling/spec/surrogate.py`
  - Added strict artifact compatibility checks during eval:
    - backend mismatch detection
    - artifact input/output signature mismatch detection
    - payload input/output order mismatch detection
    - backend payload presence check
    - module: `src/bayesian_metamodeling/surrogates/service.py`
  - Added backend payload signature checks at load boundary:
    - module: `src/bayesian_metamodeling/surrogates/backends.py`
  - Improved CLI robustness for surrogate fit/eval failures:
    - clear `Surrogate fit failed: ...` / `Surrogate eval failed: ...` messages
    - module: `src/bayesian_metamodeling/cli/main.py`
  - Hardened artifact metadata for IO compatibility:
    - added `io_signature` fields in `src/bayesian_metamodeling/storage/surrogate_store.py`
  - Added dedicated hardening tests:
    - `tests/test_surrogate_backend_hardening.py`
      - backend_config key/value validation
      - backend mismatch and signature mismatch guards
      - malformed/missing eval payload and artifact CLI errors
      - optional dual-backend integration path (slow, dependency-gated)
  - Added troubleshooting section for surrogate fit/eval guardrails:
    - `README.md`
- Prompt 15 implemented:
  - Converted tutorial delivery to notebook-only (`.ipynb`) in:
    - `tutorials/Tutorial_0.ipynb` ... `tutorials/Tutorial_9.ipynb`
  - Removed markdown tutorial duplicates:
    - retired `tutorials/Tutorial_*.md`
  - Upgraded onboarding structure across all tutorials:
    - estimated time
    - prerequisites/dependencies
    - success criteria
    - runnable checkpoints
    - troubleshooting/fallback guidance
  - Synchronized tutorial architecture across docs:
    - `README.md`
    - `tutorials/README.md`
    - `PRD.md`
    - `TechSpec.md`
    - `CodeDesign.md`
    - `PROMPT_TO_CODEX.md`
- Tutorial hardening pass (post-Prompt 15):
  - Fixed surrogate tutorial blocker in dataset parsing:
    - `src/bayesian_metamodeling/surrogates/dataset.py`
    - now supports adapter output envelope shape `{out_name: {\"inputs\": ..., out_name: [...]}}`.
  - Added regression coverage:
    - `tests/test_surrogate_dataset_loading.py`
  - Notebook quality-gate compatibility:
    - `pyproject.toml` updated with Ruff `extend-exclude = [\"*.ipynb\"]` so docs notebooks do not break repo lint gate.
  - Regenerated tutorial notebooks with richer guided pedagogy:
    - explicit prerequisites, time estimates, success criteria, and troubleshooting.
    - added graphics/plots in each tutorial notebook.
    - removed manual `RUN_ID` placeholder in Tutorial 1 (auto-selects latest tutorial run).
  - Validation results:
    - `ruff format .` / `ruff check .` / `pytest -q -m \"not slow\"` pass in `py314_bayesmm`.
    - PyMC and SBI tutorial fit/eval commands verified in dependency-capable env:
      - `tmp/conda_pymc_verify`.
    - New dataset parser regression test passes:
      - `pytest -q tests/test_surrogate_dataset_loading.py`
- SBI module verification + Tutorial 6 portability hardening (2026-02-20):
  - Updated `tutorials/Tutorial_6.ipynb` to remove machine-specific absolute paths:
    - Bash cells now auto-detect repo root when notebook runs from either repo root or `tutorials/`.
    - Step 3 spec-loading cell now resolves `tutorials/specs/surrogate.toy.sbi_npe.json` from detected repo root.
    - Tutorial checkpoint test command now uses `PYTHONPATH=src python -m pytest ...` instead of bare `pytest`.
  - Added regression coverage for Tutorial 6 portability:
    - `tests/test_tutorial_sbi_notebook.py`
  - Environment fixes applied to support real SBI validation in the dedicated SBI env:
    - Installed `pytest` and `pydantic` into `/Users/barak/miniconda3/envs/py312_bayesmm_sbi`.
  - Validation results (2026-02-20):
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_tutorial_sbi_notebook.py` -> `1 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_surrogate_backends.py -k sbi` -> `2 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests -k \"sbi or tutorial\"` -> `5 passed`
    - `/Users/barak/miniconda3/envs/py314_bayesmm/bin/ruff format .` -> no changes
    - `/Users/barak/miniconda3/envs/py314_bayesmm/bin/ruff check .` -> passed
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py314_bayesmm/bin/python -m pytest -m \"not slow\" -ra` -> passed (`47 passed`, `8 skipped`, `3 deselected`)
- Optional-backend fast-suite hardening for mixed PyMC/SBI environments (2026-02-20):
  - Added PyMC runtime-constraint classifier for optional backend tests:
    - `tests/backend_support.py` (`is_pymc_runtime_constraint`)
  - Routed SBI training summary logs from repo root into `tmp/`:
    - `src/bayesian_metamodeling/surrogates/backends.py`
      - added `_make_sbi_summary_writer()` and wired it into `_build_sbi_inference(...)`
      - default SBI tensorboard output now writes under `tmp/sbi-logs/` (fallback no-op writer when unavailable)
  - Added regression coverage for SBI log root location:
    - `tests/test_surrogate_backends.py::test_make_sbi_summary_writer_uses_tmp_log_root`
  - Synchronized main-folder docs with backend/runtime behavior and log-path policy:
    - `README.md`
    - `PRD.md`
    - `TechSpec.md`
    - `CodeDesign.md`
    - `TEST_PLAN.md`
    - `PROMPT_TO_CODEX.md`
  - Cleaned obsolete root-level SBI log artifact:
    - removed untracked `sbi-logs/` (old runs); active log path remains `tmp/sbi-logs/`.
  - Hardened optional backend tests to skip/fallback on toolchain-limited PyMC runtime failures while still executing SBI paths:
    - `tests/test_surrogate_backends.py`
      - `test_pymc_gp_backend_fit_sample_and_logprob` now skips with explicit runtime-constraint reason when PyMC cannot compile locally.
      - `test_backend_specific_fit_quality_increasing_difficulty` now falls back to `sbi_npe` when PyMC is installed but not runtime-usable.
  - Validation result (no `PYTENSOR_FLAGS` override):
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -m \"not slow\" -ra` -> passed (`54 passed`, `1 skipped`, `3 deselected`)
- SBI backend extensive test expansion (2026-02-20):
  - Added a dedicated SBI unit/behavior coverage file:
    - `tests/test_sbi_backend_extended.py`
  - New tests added: `20` (SBI-focused), covering:
    - `SbiNPEPosteriorModel` input normalization, sampling shape/seed behavior, denormalization, `log_prob` jacobian correction, length mismatch errors, and summary statistics.
    - `_make_sbi_summary_writer` fallback behavior when tensorboard writer import is unavailable.
    - `_build_sbi_inference` NPE-first path and SNPE fallback path.
    - `_train_sbi_density_estimator` full-kwargs train path and compatibility fallback-on-`TypeError`.
    - `_fit_sbi_npe` normalization details (including constant-feature scaling guard) and default/configured `summary_samples`.
    - SBI payload persistence and loading (`save_backend_payload` + `load_backend_model` for `sbi_npe_posterior`).
    - `fit_backend_model` SBI dispatch + invalid-density-estimator rejection.
  - Validation results:
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py314_bayesmm/bin/python -m pytest -q tests/test_sbi_backend_extended.py -ra` -> `20 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_sbi_backend_extended.py -ra` -> `20 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_surrogate_backends.py -k sbi -ra` -> `3 passed`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_surrogate_backend_hardening.py -ra` -> `7 passed`, `1 skipped` (optional dual-backend runtime constraint)
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py314_bayesmm/bin/python -m pytest -m \"not slow\" -ra` -> passed (`67 passed`, `8 skipped`, `3 deselected`)
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -m \"not slow\" -ra` -> passed (`74 passed`, `1 skipped`, `3 deselected`)

## Provenance log (design verification runs)
- BioModels sample source used:
  - `https://www.ebi.ac.uk/biomodels/services/download/get-files/MODEL1907260003/2/lever2014%20v5.0.xml`
- Local artifact:
  - `tmp/biomodels/MODEL1907260003_lever2014_v5_0.xml`
- Artifact digest (SHA256):
  - `bb58b84e80f11b7cea87393bb8b79247e0c13fa9c5347a13c65b341d70a3b94e`
- Simulation driver:
  - `tmp/scripts/simulate_lever_model.py`
- Driver digest (SHA256):
  - `d35ac97d4df556fb960f3b25dd2ea56d13990da7d8723fd838633f93d4921dd0`
- Executed scenarios (seeds): baseline=101, param_low=102, param_high=103
- Scanned parameter:
  - `k_on` with values `[0.00008, 0.0001, 0.00012]`
- Output summary:
  - `tmp/biomodels/simulations_MODEL1907260003/summary.json`
- Summary digest (SHA256):
  - `1bce50952d5df74eb399dff9f247efbf250541315b22c407884d033347178536`
- Run logs:
  - `tmp/run_logs/biomodel_download_lever.stderr.log`
  - `tmp/run_logs/biomodel_sim_lever.stdout.log`
  - `tmp/run_logs/biomodel_sim_lever.stderr.log`
- PyMC verification run (Prompt 11 acceptance backfill):
  - Verification environment:
    - `tmp/conda_pymc_verify` (Python `3.11.14`, PyMC `5.27.1`, ArviZ `0.23.4`)
  - Command:
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTENSOR_FLAGS='cxx=' PYTHONPATH=src /Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/conda_pymc_verify/bin/pytest -q tests/test_surrogate_backends.py -k pymc_gp_backend_fit_sample_and_logprob`
  - Result:
    - `1 passed` (2026-02-11)
  - Note:
    - `PYTENSOR_FLAGS='cxx='` was required in this sandbox to avoid missing local C++ stdlib/toolchain headers during PyTensor compilation.
- SBI verification run (Prompt 12 acceptance backfill):
  - Verification environment:
    - `tmp/conda_pymc_verify` (Python `3.11.14`, SBI `0.25.0`, Torch `2.5.1`)
  - Command:
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/Downloads/metamodeler_codex_scaffold_docs/tmp/conda_pymc_verify/bin/pytest -q tests/test_surrogate_backends.py -k sbi_npe_backend_fit_sample_and_logprob`
  - Result:
    - `1 passed` (2026-02-11)
- SBI + Tutorial 6 verification run (2026-02-20):
  - Verification environment:
    - `/Users/barak/miniconda3/envs/py312_bayesmm_sbi` (Python `3.12.12`, SBI `0.23.3`, Torch `2.10.0`, Pydantic `2.12.5`, Pytest `9.0.2`)
  - Spec digests (SHA256):
    - `tutorials/specs/model.toy.grid.json`: `1e9932106f67261a6ca49ed389e332cef20711d978e455e8234f9d1aae9858ae`
    - `tutorials/specs/surrogate.toy.sbi_npe.json`: `7cfd28482379c5327b3d556376d669141d3c5d12540e4172f5b8e84d8755d2f8`
  - Tutorial commands:
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m bayesian_metamodeling.cli.main run tutorials/specs/model.toy.grid.json`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m bayesian_metamodeling.cli.main surrogate fit tutorials/specs/surrogate.toy.sbi_npe.json`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m bayesian_metamodeling.cli.main surrogate eval tutorials/specs/surrogate.toy.sbi_npe.json --inputs '{\"a\":[0.25,0.75,1.25,1.75],\"b\":[0.2,0.6,1.0,1.4]}' --n 200`
    - `HOME=$(pwd)/tmp/home_for_tests MPLCONFIGDIR=$(pwd)/tmp/home_for_tests/.mpl PYTHONPATH=src /Users/barak/miniconda3/envs/py312_bayesmm_sbi/bin/python -m pytest -q tests/test_surrogate_backends.py -k sbi_npe_backend_fit_sample_and_logprob`
  - Outputs:
    - Sweep run id: `318336745d994b8abd053abfe8427b83` (`9/9` successful points)
    - Surrogate artifact id: `e43a8159607e44eca97700c76fd90c4b`
    - Eval summary (`n=4`, `posterior_draws=256`):
      - `mean=[0.421676390359283, 1.3336015344047611, 2.249973503133714, 3.1773650763390755]`
      - `std=[0.00926032403558707, 0.006743305751872682, 0.005223104873577676, 0.007056205854447724]`
  - Artifact digest (SHA256):
    - `tmp/surrogate_artifacts/e43a8159607e44eca97700c76fd90c4b/artifact.json`: `0eb8f17692b10673cbf3bb16884aa35751dc0734c317fe159b446450fdc95e10`
  - Logs:
    - `tmp/sbi_verify_2026-02-20/tutorial6_step1_run.log`
    - `tmp/sbi_verify_2026-02-20/tutorial6_step2_fit.log`
    - `tmp/sbi_verify_2026-02-20/tutorial6_step2_eval.log`
    - `tmp/sbi_verify_2026-02-20/tutorial6_step4_pytest.log`

### 2026-03-04: Security hardening audit and remediation
- Performed comprehensive security audit and applied fixes across 9 files:
  - **C1 (Critical)**: `surrogates/backends.py` — added type validation on `torch.load` deserialized objects (must implement `sample`/`log_prob` posterior interface)
  - **H1 (High)**: `adapters/python_cli.py` — added entrypoint path confinement to repo root
  - **H2 (High)**: `adapters/python_cli.py` — added path traversal guard on output mapping paths (confined to `run_dir`)
  - **H3 (High)**: `storage/run_store.py` — added registry path confinement (must resolve within CWD or `tmp/`)
  - **H4 (High)**: `spec/modelspec.py` — added regex validation for `conda_env` names (rejects injection characters)
  - **M1 (Medium)**: `surrogates/dataset.py` — added `..` traversal guard on dataset paths
  - **M2 (Medium)**: `surrogates/service.py` — replaced predictable temp file with UUID-based name + `finally` cleanup
  - **M4 (Medium)**: `adapters/biomodels_sbml.py` — added explicit `verify=True` on `requests.get`
  - **L1 (Low)**: `spec/modelspec.py` — added `..` traversal guard on `storage.root` validator
- Added security test suite: `tests/test_security_hardening.py` (23 tests covering all guards)
- Validation: `ruff format .`, `ruff check .`, `pytest -q -m "not slow"` all pass

## Next steps, ordered
1) Run optional MPI integration path under `mpirun` and record environment/result details
2) Migrate remaining tutorial notebooks that still read legacy `runs/*` folders to centralized sweep paths
3) Extend centralized sweep schema validation for higher-dimensional/non-scalar outputs

## Decisions log
- 2026-02-11: Prioritize execution/reproducibility core before advanced Bayesian coupling.
- 2026-02-11: Freeze v1 to local runner + typed contracts + run provenance; defer full surrogate/meta inference.
- 2026-02-11: Enforce explicit no-downsampling policy in docs and prompt pack.
- 2026-02-11: Scaffold step implemented with strict hooks and no modeling logic added.
- 2026-02-11: Main-branch commit blocking hook includes explicit override (`ALLOW_MAIN_COMMIT=1`) to support controlled bootstrap commits.
- 2026-02-11: Added pre-implementation `CodeDesign.md` to lock target interfaces against a three-model coupling use case and a real BioModels sample use case.
- 2026-02-11: BioModels sample verification executed against MODEL1907260003 with logged three-scenario parameter scan (no downsampling).
- 2026-02-11: Prompt 1 implemented using Pydantic v2 contracts and explicit schema artifact generation.
- 2026-02-11: Prompt 2 implemented with deterministic DOE planning for `grid` and `sobol`.
- 2026-02-11: Prompt 3 implemented with adapter/runner/storage separation and run registry CLI.
- 2026-02-11: Prompt 4 implemented with BioModels SBML adapter baseline and slow integration test path.
- 2026-02-11: Prompt 5 implemented as typed contract placeholders only; no inference logic added.
- 2026-02-11: Added tutorial-first usage guide to reduce onboarding friction before full implementation.
- 2026-02-11: Prompt 6 added backend-neutral IR and compiler boundary before binding runtime inference backends.
- 2026-02-11: Prompt 7 introduced concrete backend names and artifact contracts while keeping user-facing surrogate interface stable.
- 2026-02-11: Prompt 8 implemented metamodel build/sample flow with backend-gated behavior and canonical sample artifacts.
- 2026-02-11: Prompt 9 enabled backend switching (`pymc`/`numpyro`) without changing metamodel JSON interface.
- 2026-02-11: Prompt 10 added UX commands and reproducibility metadata guarantees for emitted artifacts.
- 2026-02-11: Tutorial and README backend notes updated to remove stale placeholder/stub language.
- 2026-02-11: Added prompts 11-13 in `PROMPT_TO_CODEX.md` to implement real `pymc_gp` and `sbi_npe` backends plus compatibility hardening.
- 2026-02-11: Prompt 11 implemented real PyMC-backed surrogate learning for `pymc_gp` with persisted posterior payload and optional dependency handling.
- 2026-02-11: Prompt 11 acceptance criteria retroactively tightened to require at least one executed real-PyMC verification test run and log in `Status.md`.
- 2026-02-11: Verified real PyMC surrogate learning test passes in isolated conda env (`tmp/conda_pymc_verify`) using PyTensor non-C fallback.
- 2026-02-11: Prompt 12 implemented real SBI NPE surrogate learning path with persisted posterior payload and dependency-gated tests.
- 2026-02-11: Prompt 12 acceptance criteria retroactively tightened to require at least one executed real-SBI verification test run and log in `Status.md`.
- 2026-02-11: Verified real SBI surrogate learning test passes in isolated conda env (`tmp/conda_pymc_verify`).
- 2026-02-11: Prompt 13 implemented backend-config validation, artifact compatibility checks, and improved surrogate CLI error reporting.
- 2026-02-12: Consolidated tutorial requests into Prompt 14 and implemented a modular 9-part tutorial curriculum with BioModels moved early and per-tutorial scientific side-aims.
- 2026-02-12: Prompt 15 converted tutorials to notebook-only delivery and upgraded onboarding structure (time estimates, prerequisites, success criteria, checkpoints, troubleshooting).
- 2026-02-12: Hardened tutorial execution by fixing surrogate dataset envelope parsing and regenerating all notebooks with guided explanations and graphics.
- 2026-02-12: Introduced `runner.execution_env` (default empty) and explicit `conda_env` support so runtime environment is user-configurable via JSON, not hardcoded.
- 2026-02-12: Added `MM_SKIP_OPTIONAL_BACKEND_TESTS` to make optional backend tests warning/skip-friendly when `pymc`/`sbi` are intentionally unavailable.
- 2026-02-12: Created dedicated backend conda envs and installed `pymc`/`sbi` stacks there; kept the main project env skip-safe.
- 2026-02-12: Renamed `py314_bayesmm_pymc` to `py312_bayesmm_pymc` and re-verified surrogate-PyMC plus metamodel-PyMC test tracks in the renamed env.
- 2026-02-12: Updated `tutorials/Tutorial_0.ipynb` to run no install commands at all; replaced with a manual "Loading environment" guidance box and commented conda examples (`py314_bayesmm` kept as recommendation/example only).
- 2026-02-15: Removed redundant root tutorial files (`TUTORIAL.md`, `TUTORIAL.ipynb`); tutorials now live only under `tutorials/` with `tutorials/Tutorial_0.ipynb` as the entry point.
- 2026-02-15: Hardened `tutorials/Tutorial_0.ipynb` preflight cell to auto-detect repo root from either repo-root or `tutorials/` execution context; verified by executing notebook end-to-end in `py314_bayesmm` (`tmp/Tutorial_0.executed.ipynb`).
- 2026-02-15: Commit pass: finalized runner `execution_env` plumbing (spec validation, adapter materialization, local runner conda prefixing, and dedicated runner/spec tests).
- 2026-02-15: Commit pass: finalized optional-backend test controls (`optional_backend` marker + `MM_SKIP_OPTIONAL_BACKEND_TESTS`) and generalized backend install guidance to use `<env_name>`.
- 2026-02-15: Refined `tutorials/Tutorial_0.ipynb` for safer onboarding (manual install guidance only, no hardcoded path/env assumptions) and re-validated notebook execution (`tmp/Tutorial_0.executed.ipynb`).
- 2026-02-15: Simplified `tutorials/Tutorial_0.ipynb` to a standard notebook flow: explicit "use a pre-set kernel environment" guidance, CLI preflight with `PYTHONPATH` wiring, manual/commented install examples only, and successful end-to-end execution check (`tmp/Tutorial_0.executed.ipynb`).
- 2026-02-15: Expanded `examples/toy_program/run.py` module docstring to document toy-run behavior and its role in local integration testing.
- 2026-02-15: Added Prompt 17 design package (PRD/TechSpec/CodeDesign/TEST_PLAN/PROMPT_TO_CODEX updates) for centralized DOE sweep CSV output and synchronized serial/local-parallel/MPI writing; no runtime implementation in this step.
- 2026-02-15: Completed Prompt 17 implementation with centralized sweep artifacts, synchronized serial/local-parallel/MPI execution modes, Tutorial 1 dual-heatmap update, and updated fast/slow test coverage.
- 2026-02-15: Hardened `tutorials/Tutorial_1.ipynb` against stale registry paths and missing prior sweep records by auto-running the toy sweep when needed; verified end-to-end notebook execution to `tmp/Tutorial_1.executed.ipynb`.
- 2026-02-15: Refactored `tutorials/Tutorial_1.ipynb` CLI helper naming/usage to `run_mm_cli` consistently (removed mixed `run_mm`/`run_mm_CLI` calls and shell-style invocation remnants).
- 2026-02-15: Refactored `tutorials/Tutorial_2.ipynb` to notebook-native CLI execution via `run_mm_cli`, added dense/wider `k_on` sweep generation (11-point grid over `[8e-05, 1.2e-04]`), switched analysis to centralized sweep CSV parsing, and added time-vs-`k_on` heatmap plus biological interpretation guidance.
- 2026-02-15: Hardened `tutorials/Tutorial_2.ipynb` for offline BioModels execution by seeding dense-run SBML cache from existing local cache/file when available; fixed heatmap parsing to use centralized columns (`time_series__rows__json` + `time_series__columns__*`).
- 2026-02-15: Verified Tutorial 2 in `py313_metamodeling_pymc` using notebook code cells (3/5/7/9): dense BioModels run completed successfully with 11/11 successful points (`run_id=ed4db1e01b1d449684784f5503fa56f8`).
- 2026-02-20: Hardened `tutorials/Tutorial_6.ipynb` for portable execution (no hardcoded local paths) and added a regression test to lock this behavior.
- 2026-02-20: Optional backend tests now treat PyMC compile/toolchain failures as runtime constraints (skip/fallback) so SBI-enabled environments can still pass the fast suite without forcing `PYTENSOR_FLAGS='cxx='`.
- 2026-02-20: Routed SBI training logs to `tmp/sbi-logs/` to prevent root-level `sbi-logs/` workspace pollution and added explicit coverage for this path.
- 2026-02-20: Updated root docs (`README.md`, `PRD.md`, `TechSpec.md`, `CodeDesign.md`, `TEST_PLAN.md`, `PROMPT_TO_CODEX.md`) to reflect optional-backend runtime behavior and SBI log-path policy.
- 2026-02-20: Removed stale root `sbi-logs/` directory left by earlier SBI runs; canonical location is `tmp/sbi-logs/`.
- 2026-02-20: Added a dedicated 20-test SBI backend coverage suite (`tests/test_sbi_backend_extended.py`) and re-validated both baseline and SBI-enabled fast suites.
- 2026-02-20: Hardened optional backend imports for sandboxed environments by routing ArviZ/matplotlib cache writes to `tmp/` (`HOME`, `MPLCONFIGDIR`, `XDG_CACHE_HOME`) and suppressing ArviZ startup warning during import; validated with `conda run -n py312_bayesmm_sbi ruff format .`, `ruff check .`, and `pytest -q -m "not slow"`.

### 2026-03-04: Production hardening (8-commit series)
- **Commit 1** `fix(cli): replace broad exception handlers with specific types`
  - `src/bayesian_metamodeling/cli/main.py`: replaced two `except Exception` blocks with specific exception types (`ValueError`, `FileNotFoundError`, `json.JSONDecodeError`, `KeyError`, `OSError`, `subprocess.SubprocessError`)
  - Added tests: `tests/test_cli_ux_commands.py` (specific exception catch + unexpected propagation)
- **Commit 2** `fix(runner): add subprocess timeout from walltime_min`
  - `src/bayesian_metamodeling/runners/local_process.py`: added `__init__` with `timeout_sec`, `subprocess.TimeoutExpired` handling
  - `src/bayesian_metamodeling/cli/main.py`: plumbed `walltime_min * 60` into `LocalProcessRunner`
  - Added tests: `tests/test_local_process_runner.py` (timeout pass-through + TimeoutExpired handling)
- **Commit 3** `fix(storage): add file locking to registry operations`
  - New: `src/bayesian_metamodeling/storage/_filelock.py` — `locked_registry()` context manager using `fcntl.flock()`
  - Modified: `run_store.py`, `surrogate_store.py`, `meta_store.py`, `meta/sampling.py` — wrapped registry writes
  - Added tests: `tests/test_storage_unit.py` (concurrent write safety)
- **Commit 4** `fix(meta): unify coupling sigma default and document approximation`
  - `src/bayesian_metamodeling/meta/ir.py`: added `DEFAULT_COUPLING_SIGMA = 0.1`
  - `src/bayesian_metamodeling/meta/compiler.py`: named constants `_DETERMINISTIC_PENALTY`, `_DETERMINISTIC_TOL`, use shared default
  - `src/bayesian_metamodeling/meta/sampling.py`: use shared default, added `_NUMPYRO_NOISE_SCALE_FACTOR`, docstring for `_sample_core()`
  - Added tests: `tests/test_meta_ir_edge_cases.py` (sigma default consistency)
- **Commit 5** `fix: thread-safe backend imports, CLI input size limit`
  - `src/bayesian_metamodeling/surrogates/backends.py`: `_ENV_LOCK = threading.Lock()` around env var manipulation
  - `src/bayesian_metamodeling/cli/main.py`: `_MAX_INPUTS_JSON_BYTES = 10 MB` size check before JSON parse
  - Added tests: `tests/test_surrogate_backend_hardening.py` (lock exists + oversized input rejection)
- **Commit 6** `test: add tier-1 unit tests` (~80 tests across 9 files)
  - New test files: `test_spec_edge_cases.py`, `test_adapter_unit.py`, `test_runner_unit.py`, `test_storage_unit.py` (expanded), `test_dataset_edge_cases.py`, `test_surrogate_model_contract.py`, `test_meta_ir_edge_cases.py` (expanded), `test_compiler_edge_cases.py`, `test_sampling_edge_cases.py`
  - Shared helpers added to `tests/conftest.py`
- **Commit 7** `test: add tier-2/3 integration and tutorial regression tests`
  - New test files: `test_cli_error_paths.py`, `test_run_failure_handling.py`, `test_tutorial_portability.py`, `test_example_specs.py`, `test_surrogate_quality_extended.py`, `test_metamodel_coupling_quality.py`
- **Commit 8** `docs: fix tutorials, update Status.md`
  - `tutorials/Tutorial_2.ipynb`: removed legacy `tmp/Old/` cache path reference
  - `tutorials/Tutorial_3.ipynb`: added markdown cells showing expected validator output inline
  - `tutorials/Tutorial_9.ipynb`: added pre-flight cell checking which prior tutorial artifacts exist
  - `Status.md`: recorded all 8 fixes
- Validation: `ruff format .`, `ruff check .`, `pytest -q -m "not slow"` all pass

## 2026-05-14: joint multi-output surrogates, configurer, cross-platform tutorials
Ported from `main` (PR #2 had merged the same features there against the old
`metamodeler` package name) and adapted for develop's `bayesian_metamodeling`
package + `bayesmm` CLI. Backup ref `claude/develop-pre-port` retained.
- **Commit `feat(cli): add bayesmm doctor / bayesmm setup configurer`** — new
  `bayesian_metamodeling.config` package (`bootstrap`, `diagnose`, `setup`,
  `platform`, `_import_helpers.probe_package`) + `bayesian_metamodeling.tutorial`
  helper. CLI gains `bayesmm doctor [--json]` and
  `bayesmm setup [--non-interactive --backend ...]`. The hardened `_require_*`
  helpers stay in `surrogates/backends.py`.
- **Commit `feat(surrogates): joint multi-output learning`** — `SurrogateSpec`
  accepts any number of outputs; `backend_config.output_correlation` selects
  `"diagonal"` (independent per-output, default) or `"full"` (joint covariance:
  PyMC `LKJCholeskyCov`, SBI D-dim density estimator). Dataset loader reads all
  output columns (`y` is now `(N, D)`). Multi-output posterior models return
  `(N, n)` for D=1 and `(N, n, D)` for D>=2; `LinearGaussianModel` keeps its
  original 2-D contract. Payload schema bumped to `..._v2` with v1 read-back.
  `SbiNPEPosteriorModel` keeps a back-compatible constructor for the old
  `posterior=` / `output_name=` / scalar-`y_mean` call sites.
- **Commit `chore(tutorials): cross-platform notebooks`** — converted the
  remaining `%%bash` cells in Tutorials 3/4/5/6/7/8/9 to in-notebook
  `run_mm_cli` / `run_tool` helpers (no `%%bash`, no `PYTHONPATH=src`); each
  notebook bootstraps and chdir's to the repo root. Added `environment.yml`.
  README + tutorials/README rewritten with cross-platform install + configurer
  notes; README doc-map paths de-absolutized. Tutorial_9's quality gate scoped
  to `src tests` (was `.`, which dragged in the unrelated tcr_signaling submodule).
- Worked around a ruff 0.15.12 formatter bug that unwraps bare `except (A, B):`
  tuples into invalid `except A, B:` (`config/platform.py`).
- Validation: all 10 tutorials execute end-to-end via `jupyter execute` on the
  `py312_bayesmm_sbi` env; `ruff check src tests` clean; fast suite
  (`pytest -q -m "not slow" tests`) green.

## Independent review + cross-platform verification (2026-05-14)
- Code-reviewed both packages and ran every test.
- `bayesian_metamodeling` (macOS): fast suite green on `py312_bayesmm_sbi` (256 passed)
  and `py314_bayesmm` (244 passed; optional-backend tests skip-safe); slow suite green
  on `py312_bayesmm_sbi`; `ruff check` / `ruff format --check` clean.
- `tcr_signaling` submodule (macOS, run from inside the submodule): clean CMake build of
  `ks_gpu` + `libks_potentials.dylib`; full `pytest` suite — 169 tests — all passed. The
  32 GPU tests ran on Metal with no silent CPU fallback (stderr clean). Treated
  read-only; its Windows gaps (Makefile-only build, `ks_gpu` not `.exe`, Metal-only GPU)
  are documented, not fixed.
- All 10 tutorial notebooks execute end-to-end via `jupyter execute` on `py312_bayesmm_sbi`.
- Cross-platform fixes applied (`bayesian_metamodeling` + tutorials only):
  - `tutorials/Tutorial_0.ipynb`: hardcoded `:` PYTHONPATH separator → `os.pathsep` (broke
    PYTHONPATH on Windows). The preflight cell now also runs `bayesmm doctor` for fast
    onboarding; stale `py*_metamodeling_*` env references replaced with pointers to
    `bayesmm doctor` / `bayesmm setup`.
  - `pytest.ini`: dropped `projects/tcr_signaling` from `testpaths` — collecting the
    submodule under the parent's `filterwarnings = error` turned its unregistered
    `deterministic` marker into a collection error. The submodule is tested from inside
    itself (its own pytest.ini).
  - `config/diagnose.py`: Python-floor advisory aligned to the real floor (`>=3.12` per
    pyproject.toml; was warning at `< 3.11`).
  - `tutorial.py::run_tool`: a bare `python` now also routes through `sys.executable`
    (conda-on-Windows PATH robustness).
- Added `.github/workflows/ci.yml`: matrix CI on ubuntu/windows/macos × py3.12 — install
  with `[pymc,sbi]`, ruff lint + format, fast test suite, and a `bayesmm doctor` / `setup`
  smoke. This is the authoritative Windows + Linux verification (cannot be run from a
  macOS dev box). The `tcr_signaling` submodule is intentionally out of CI scope (native
  CMake/Metal build).
- Note: Linux verification was subsequently completed locally via Docker — see the
  2026-05-15 entry below for the run, the two issues it surfaced (`sbi` 0.26 +
  PyMC/PyTensor BLAS), and the resulting fixes. The CI `ubuntu-latest` leg now
  has the same fixes baked in.

## Cross-platform compat fixes from Linux Docker re-verify (2026-05-15)
- Re-verified the `bayesian_metamodeling` fast suite in a fresh `python:3.12`
  Docker container with the repo mounted (`docker run --rm -v <repo>:/work -w /work
  -e PYTENSOR_FLAGS=cxx= python:3.12 …`). The first run surfaced two real issues
  that were silently hidden by the local conda envs:
  - **sbi 0.26 incompatibility**: pip pulled `sbi 0.26.1` in the container.
    0.26 renamed the training-logger kwarg `summary_writer` → `tracker` (a
    `FutureWarning`, fatal under the suite's `filterwarnings = error`) **and**
    changed the tracker object interface so it now calls `.log_metric()` —
    `SummaryWriter` doesn't have that method, so even after passing the new
    kwarg the training loop crashes with `AttributeError`. Scoped fix: pinned
    `sbi = ["sbi>=0.22,<0.26", "torch>=2,<3"]` in `pyproject.toml`. Verified
    against sbi 0.25.x. Supporting sbi 0.26+ requires a tracker-protocol shim
    and is tracked as a follow-up (see Open issues).
  - **PyMC/PyTensor BLAS**: the bare `python:3.12` image lacks the system BLAS
    PyTensor needs to compile its C ops, so PyMC tests crashed in compile.
    Fix: added `PYTENSOR_FLAGS: cxx=` to the CI workflow's job-level `env:`
    (PyTensor's C-less fallback — already documented for constrained envs in
    `README`). The same env var is what the local `py312_bayesmm_pymc`
    verification has used since 2026-02-11.
- Hardened `_build_sbi_inference` (in `surrogates/backends.py`) to be
  sbi-version-robust anyway: it now tries the new (`tracker`), legacy
  (`summary_writer`), then no-logger constructor signatures and uses whichever
  the installed sbi accepts. This keeps the code forward-compatible for the
  sbi-0.26 follow-up without requiring it now.
- Added `pytest` to the CI workflow's install step — `pytest` is a dev tool, not
  a runtime dependency, so it has to be installed explicitly alongside
  `[pymc,sbi]` and `ruff`. The original CI workflow was missing it.
- Test updates in `tests/test_sbi_backend_extended.py`:
  - Rewrote `test_build_sbi_inference_falls_back_to_snpe` to use the realistic
    "old sbi" signal — `from sbi.inference import NPE` raises `ImportError`
    (NPE attribute absent), which is what actually triggers the SNPE path now.
  - Added `test_build_sbi_inference_uses_tracker_kwarg`: a fake NPE that only
    accepts the sbi-0.26-style `tracker` kwarg must still be constructed
    correctly. Locks the new kwarg-trying loop.
- Re-verification (after the fixes):
  - **Linux Docker** (`python:3.12` + `PYTENSOR_FLAGS=cxx=`, sbi 0.25.0): full
    `pytest -m "not slow" tests` green (only the 3 expected backend-deselected
    skips), `ruff check` clean, `bayesmm doctor` OK, `bayesmm setup
    --non-interactive --backend pymc,sbi` OK.
  - **Local `py312_bayesmm_sbi`** (sbi 0.25.0, torch 2.5.1, pymc 5.28.1, arviz
    0.23.4): full fast suite green (3 expected skips).
  - **Local `py314_bayesmm`** (python 3.14.3, no optional backends): full fast
    suite green (backend tests cleanly skip-deselected).
  - `ruff check src tests` + `ruff format --check src tests` clean on the main
    repo.

## Windows CI fix: cross-platform file lock (2026-05-15)
- The first CI matrix run on `claude/develop` had Linux + macOS green but
  Windows red at the test step. Root cause: `src/bayesian_metamodeling/storage/_filelock.py`
  did `import fcntl` unconditionally; `fcntl` is POSIX-only, so any module
  that touched the registry (run_store, surrogate_store, meta_store,
  meta/sampling) failed at import on Windows, killing pytest collection.
- Fix: cross-platform `_filelock.py` — `fcntl.flock(LOCK_EX/LOCK_UN)` on
  POSIX, `msvcrt.locking(LK_LOCK/LK_UNLCK, 1)` on Windows. The lock file is
  pre-seeded with one byte (Windows requires the locked region to actually
  exist; POSIX doesn't care). Each call opens its own fd, so threads inside
  one process are serialized too — matching the pre-existing
  `tests/test_storage_unit.py::test_locked_registry_concurrent_writes`
  contract.
- Audited the rest of the codebase for other Windows traps (POSIX-only
  imports, `os.fork`/`os.uname`, `shell=True` subprocess, `bash`
  invocations, residual `%%bash` notebook cells). `_filelock.py` was the
  only blocker.
- Re-verified `tests/test_storage_unit.py` (8/8 pass) on macOS POSIX.

## Windows CI fix #2: cross-platform storage.root absolute-path detection (2026-05-15)
- After the `_filelock` fix landed (66c7a6e) the windows-latest leg got past
  pytest collection but two tests failed: the `storage.root` validator's
  "rejects absolute path" check used `pathlib.Path(value).is_absolute()`,
  which on Windows treats `/tmp/absolute` as drive-relative (not absolute),
  so the test `payload["storage"]["root"] = "/tmp/absolute"` slipped through:
  - `tests/test_security_hardening.py::TestStorageRootTraversal::test_rejects_absolute_storage_root`
  - `tests/test_spec_edge_cases.py::test_modelspec_storage_root_rejects_absolute_path`
- Fix: `StorageSpec.check_not_absolute` now rejects absoluteness under EITHER
  convention by checking both `PurePosixPath(value).is_absolute()` and
  `PureWindowsPath(value).is_absolute()`, plus an explicit
  `value.startswith(("/", "\\"))` guard for drive-less rooted Windows paths
  (which pathlib doesn't classify as absolute). The `..` traversal check now
  splits on either separator. Truth-tabled against 9 inputs (POSIX-abs,
  Windows-abs, UNC, drive-rooted, traversal with either separator,
  plain relative).
- This is the platform-symmetric form of the same security intent: any
  attempt to escape the project root via an absolute path is rejected on
  every platform, regardless of which convention the path string uses.

## sbi 0.26+ tracker shim landed (2026-05-15)
- Added `_TrackerCompatWriter` in `src/bayesian_metamodeling/surrogates/backends.py`
  that adapts a `tensorboard.SummaryWriter` to expose `log_metric(name, value, step=...)`
  in terms of the legacy `add_scalar(name, value, step)` so a single writer
  satisfies both sbi <0.26 (uses `add_scalar`) and sbi >=0.26 (uses
  `log_metric`). `_make_sbi_summary_writer` now wraps the real writer; the
  `_NoOpSummaryWriter` fallback is already 0.26-safe via its blanket
  `__getattr__`. The kwarg-trying loop in `_build_sbi_inference` (added
  earlier) handles the corresponding `summary_writer` -> `tracker` rename.
- Relaxed `pyproject.toml` from `sbi<0.26` to `sbi<1` and rewrote the
  comment block above it.
- Three regression tests added in `tests/test_sbi_backend_extended.py`:
  `test_tracker_compat_writer_translates_log_metric_to_add_scalar`,
  `test_tracker_compat_writer_forwards_other_attrs`,
  `test_make_sbi_summary_writer_wraps_real_writer_with_tracker_compat`.
- Local re-verify on `py312_bayesmm_sbi`: full extended suite green
  (24 passed). CI matrix is the authoritative cross-version verification.

## MPI verification + tcr_signaling parent-README note (2026-05-15)
- Executed `tests/test_mpi_sweep_integration.py` end-to-end under
  `mpirun -n 2` for the first time. Found and fixed a latent test bug:
  `pytest.importorskip("mpi4py")` returns the package without auto-importing
  the `MPI` submodule, so `mpi4py.MPI.COMM_WORLD` raised `AttributeError`.
  Switched to `MPI = pytest.importorskip("mpi4py.MPI")`. After the fix,
  both ranks pass — 4/4 DOE points executed, exactly one centralized
  `sweep_rows.csv` produced (rank 0 writer; rank 1 synchronizes via barrier).
- Parent `README.md` extended with two new subsections:
  - "Optional: verify the MPI single-writer contract end-to-end" — gives
    the exact `mpirun -n 2 python -m pytest -q -m mpi …` command and the
    `conda install … mpi4py mpich` self-contained install path.
  - "Optional case study: `projects/tcr_signaling`" — surfaces the
    submodule's CMake / toolchain / Metal-only / Makefile-only / read-only
    constraints so a Windows user who clones with `--recurse-submodules`
    knows what to expect (the submodule is intentionally outside the parent
    CI matrix).
- MPI provenance:
  - mpi4py 4.1.1 / MPICH (Hydra 5.0.0), env `py312_bayesmm_sbi`.
  - Test session token: `4642208cf3934d1e97077da606240761`.
  - Sweep id: `262588341e8942399f217ebfa4a28228`; 4/4 successful points.
  - SHA256 `sweep_rows.csv`: `d491b0bde8e04187dc3f85c0ee8f5c952dcd31d765d05ffd078036b8f792a5ff`
  - SHA256 `sweep_manifest.json`: `90aed85cb7059bd86859bf7a7ec370d57237b6fde6a08968095f9c3c902e43ee`
  - Logs: `tmp/mpi_verify_2026-05-15/pytest.log`

## Tutorial 2 offline path landed (2026-05-15)
- New env var `MM_BIOMODELS_OFFLINE`: when set truthy and the SBML cache is
  empty, the adapter (`adapters/biomodels_sbml.py`) raises a clear
  `RuntimeError` mentioning the missing cache path and a `curl` recipe
  instead of attempting an HTTP fetch. Used by tutorial / CI / sandboxed
  workflows where the network is unavailable.
- New optional field `model.artifact.local_sbml_path` on `ArtifactSpec`: a
  spec-relative path to a local SBML file. When set, the adapter copies the
  local file into the per-spec cache (resolved against `repo_root` so the
  spec stays portable) — no network either way. Letting a tutorial ship its
  own sample SBML in-tree is now a one-field change.
- `tutorials/Tutorial_2.ipynb` updated: the bootstrap cell detects
  `MM_BIOMODELS_OFFLINE` + cache presence and prints an actionable banner
  with the exact cache path + `curl` recipe; Step 2 (the `bayesmm run`
  cell) now short-circuits cleanly in offline mode instead of failing. The
  heatmap analysis cells were already skip-safe ("no sweeps yet").
- 5 regression tests in `tests/test_biomodels_adapter_offline.py`:
  offline-env blocks download, offline-env uses existing cache,
  local_sbml_path seeds the cache (no network), local_sbml_path with
  missing file errors clearly, and a sanity check that existing example
  specs (without `local_sbml_path`) still validate.
- Local verify:
  - `pytest -q tests/test_biomodels_adapter_offline.py`: 5/5 pass.
  - `pytest -q -m "not slow" tests`: full fast suite green.
  - `MM_BIOMODELS_OFFLINE=1 jupyter execute tutorials/Tutorial_2.ipynb`:
    notebook completes end-to-end with the offline banner + Step 2 skip,
    no crashes (`tmp/tutorial2_offline_verify/Tutorial_2.executed.ipynb`).
- Schema artifact regenerated: `src/bayesian_metamodeling/spec/modelspec.schema.json`.

## Pedagogical pass on Tutorial_0..9 (2026-05-15, 11 commits)

Mechanically the tutorials were already clean (cross-platform helpers,
offline-aware T2, no `%%bash`). A pedagogical review (lab-manager voice,
applied best practices) found that they didn't actually **teach** —
they were a clean *demonstration sequence* with three structural failures
(T0 had no biology + a fake complexity plot; T7 + T8 were skeletal
coupling demos that never explained coupling; T9 was a CI checklist
masquerading as a capstone) and six cross-cutting issues (boilerplate
"Why this tutorial matters" cell duplicated verbatim across 7 notebooks;
no shared glossary; generic biology motivation; no predict-before-you-run
prompts; no anticipated-misconceptions callouts; stale `$ mm` outputs in
T1 from before the package rename).

This commit series fixed all of that across 11 commits, one per notebook
plus this Status.md summary, each independently revertible:

- **`762c1c5` — T0**: Rewrote opening with TCR-signaling running example;
  added shared glossary cell (referenced from later tutorials, single
  source of truth); replaced fake `complexity = [1,2,2,3,...]` plot with
  a real markdown ASCII pipeline diagram
  (`Spec → DOE plan → Sweep → CSV → Surrogate → Metamodel → Joint posterior`)
  showing which tutorials cover each segment; rewrote tutorial map as
  outcome table; expanded tips with time-sink warnings.

- **`e00672b` — T1**: Replaced boilerplate Why; added `validate` vs
  `plan` callout, "predict before you run" before the dual heatmap, and
  a "you can skim this" banner above the 50-line auto-selection cell;
  added a forward-link to T5 in the scientific checkpoint; re-executed
  to refresh stale `$ mm` outputs to `$ bayesmm` (the actual mechanical
  fix the agent flagged).

- **`352b14b` — T2**: Named MODEL1907260003 as Lever, Maini, van der
  Merwe & Dushek 2014 (citation verified via the BioModels API, PubMed
  25145757); added a `k_on` biological callout (forward association
  rate constant for `L+R→LR`, units `1/(M·s)`, ±20% sweep around the
  published parameter); added "you can skim this" above the 70-line
  CSV+timeseries parser; added a "Common confusion" callout in the
  scientific checkpoint connecting T2 → T5/T6.

- **`5e10c27` — T3**: Replaced boilerplate Why; added Step 4 second
  error type — inverted `support: [max, min]` (a per-input contract
  violation the validator catches with the exact field path
  `io_schema.inputs.0.support`); reframed the scientific checkpoint
  around per-input contract reasoning; deleted the fake importance-
  weights bar chart and replaced with a real markdown table listing
  spec sections + one sentence each on what they contract for. (Also
  attempted-and-abandoned: an input-name mismatch test — `design.grid`
  keys aren't cross-checked against `io_schema.inputs` names today,
  which is a real validator gap noted but out of scope for this
  notebook-only pass.)

- **`1d02642` — T4**: Replaced boilerplate Why with budget framing;
  added a CLI `bayesmm run` for the Sobol spec BEFORE the comparison
  scatter (the single biggest fix in T4 — previously the scatter showed
  "No Sobol runs yet" placeholder ~100% of the time because the spec
  was planned but never run); added "predict before you run" + a real
  curse-of-dimensionality table (4ⁿ vs Sobol counts at 2D-6D);
  augmented the scientific checkpoint with a Sobol-determinism note.

- **`3f58fda` — T5**: Replaced boilerplate Why with a surrogate
  definition + an explicit T1 callback ("at the bottom of T1 you held a
  question — would you trust a surrogate at `a=0.5, b=0.5`? This is
  where you answer it"); **moved the prior/posterior/posterior-predictive
  mini-lesson BEFORE the plot** (the single highest-value move in T5);
  augmented the errorbar plot with a 9-point training overlay, the
  analytical truth `y = a + b` as a dotted reference line, and an
  annotation showing the actual std value (~`1e-6`); added a "Common
  confusion: errorbars ≠ confidence intervals" callout; demoted the
  pytest call to an optional appendix.

- **`4651363` — T6**: Replaced boilerplate Why with PyMC-vs-SBI framing;
  simplified `cell-8` path detection (the bootstrap helper had already
  established `repo_root`); **added a Step 4: explicit T5-vs-T6
  comparison cell** that loads both surrogates, evaluates on the same 4
  query points, plots both errorbar series on shared axes with the
  analytical truth, and prints a numeric comparison (`PyMC mean vs SBI
  mean vs truth, PyMC std vs SBI std`) — the central comparison the
  curriculum was missing; added a "Common confusion: SBI doesn't have
  priors in the PyMC sense" callout; reframed the closing mini-lesson
  with three concrete decision rules for "what to do when PyMC and SBI
  disagree on a real model"; demoted pytest call.

- **`3d4288b` — T7**: 15-minute source dive (in this commit) into
  `meta/builder.py` + `compiler.py` + `sampling.py` confirmed that
  `equality_soft` (T7's spec) and `gaussian_link` (T8's spec) compile to
  the **same Gaussian-noise primitive** — the only special-cased coupling
  kind is `deterministic` (which gets a sharp `_DETERMINISTIC_PENALTY`).
  Aligned T7's spec to use `gaussian_link` consistently with T8.
  Sharpened secondary aim around induced joint posterior shape; replaced
  boilerplate Why with the concept introduction T7 needed; added a
  "What surrogates are we coupling?" callout naming the pre-built
  `surrogate_A` and `surrogate_B` honestly; added a "Coupling kinds"
  callout naming the `gaussian_link` vs `deterministic` distinction;
  added "Predict before you sample"; **augmented the scatter into a
  side-by-side prior-vs-posterior plot** with numeric output showing
  `corr(y, C)` jump from ~0 (no coupling) to ~0.99 (with coupling) and
  `std(y - C) ≈ σ`; rewrote scientific checkpoint as an active-learning
  σ exercise (vary 0.15 → 0.5 → 1.0, observe). Also fixed a latent
  bug in the registry-lookup logic (`sorted(payload.keys())[-1]` sorts
  UUID hex alphabetically — random; replaced with sort-by-`created_at`
  + filter-by-required-vars).

- **`bed47c9` — T8**: Sharpened learning aims around uncertainty
  propagation; replaced boilerplate Why with noise-budget framing for
  the chain `y → C → z → w` and the σ values along it; added "Predict
  before you sample" walking the chain step by step; **replaced the
  overlapping translucent histograms with a violin plot** of `y, z, w`
  side-by-side, std annotated above each, plus a numeric noise budget
  printout that makes the lesson quantitative
  (`std(z) = std(C) ≈ std(y); std(w) ≈ sqrt(std(z)^2 + 0.25^2)`,
  agreement within sampling noise IS the lesson — quadrature addition
  holds); rewrote scientific checkpoint as four active-learning prompts
  (verify quadrature, predict-then-test what doubling σ does, recognize
  the deterministic surprise, connect to real models). Same registry-
  lookup fix as T7.

- **`00b76b1` — T9**: **Capstone fully rewritten** from the CI checklist
  ("ruff format --check, ruff check, pytest, hardcoded `[1,1,1,0.5,0.5]`
  bar chart") to four student-driven steps (each with explicit
  `# === EDIT ME ===` markers): (1) Pick your DOE — student sets a 5x5
  grid, the cell builds a temporary spec at
  `tmp/tutorials/specs/capstone.grid.json`, validates / plans / runs;
  (2) Fit a PyMC surrogate on the student's sweep; (3) Evaluate at
  NEW points the student picks; (4) Visualize with training overlay +
  analytical truth + numeric summary. Replaced the deliverable template
  with a fill-in markdown the student literally edits. Added a closing
  forward-pointer to `projects/tcr_signaling/` ("the real version of
  T7-T8-T9 composed at full scale on four real biological models"
  with the four model names and the Frontiers in Immunology 2024
  paper). Demoted the original quality gate to an optional appendix
  (with `check=False` so it doesn't fail the notebook). Pragmatic
  deviation from the plan: the original Step 3 said "swap a
  `surrogate_refs` entry in T7's spec to point at the capstone surrogate"
  — but T7's example surrogates have a 1D-1D shape contract while the
  capstone surrogate is 2D-1D, so a direct swap would have required
  spec engineering bigger than a notebook lesson should have. Kept
  the spec composition lesson as a forward pointer rather than a
  half-working demonstration.

Verification approach (per-commit + final):
- Each commit re-executed its notebook with `jupyter execute --inplace`
  in `py312_bayesmm_sbi`. T2 used `MM_BIOMODELS_OFFLINE=1` so the
  offline path is exercised. T6 uses both PyMC and SBI artifacts;
  needs both backends in the env.
- Final suite-level smoke: all 10 notebooks re-executed end-to-end,
  including T0's bootstrap + `bayesmm doctor` preflight, T1's CLI
  loop + dual heatmap, T2's offline-mode banner + skip, T3's break/fix
  cycles, T4's grid+sobol comparison scatter, T5's surrogate fit + eval
  + augmented plot, T6's T5-vs-T6 comparison plot, T7's prior-vs-
  posterior scatter, T8's violin + noise budget, T9's full capstone
  pipeline.
- `ruff check src tests` + `ruff format --check src tests` clean
  throughout (notebooks aren't linted but if a stray Python file got
  touched it'd surface here).

Explicitly out of scope (locked decisions, recorded so they don't get
re-litigated):
- No standalone Bayesian primer notebook — T5's mini-lesson (now moved
  before the plot) is enough at the moment students need it.
- No `ipywidgets` — notebook-only delivery + cross-platform.
- No tutorial renumbering — stable links matter more than aesthetic
  numbering.
- No T7/T8 merge — the 2→3-model progression is the lesson; both
  notebooks now teach distinct concepts (induced joint shape vs
  uncertainty propagation along a chain).
- No CLI / spec changes beyond the T7 spec vocabulary alignment
  (`equality_soft` → `gaussian_link`, same primitive). The
  input-name-mismatch validator gap surfaced during T3's commit is a
  real follow-up; tracked here, not fixed.
- No re-running the cross-platform CI matrix per commit — tutorials
  aren't part of CI's fast suite.

## Open issues
(Real, actionable items only. Items here become commits or are intentionally deferred.)

- **Validator gap surfaced during the T3 pedagogical commit (5e10c27)**:
  `design.grid` keys are not cross-checked against `io_schema.inputs`
  names. A spec with `design.grid["alpha"]` but `io_schema.inputs[0].name
  == "a"` validates green today; the runner downstream then errors with a
  less-clear message. The T3 tutorial works around this by using inverted
  `support: [max, min]` as the second-error-type example instead. Adding
  the cross-check is one Pydantic `model_validator` on `ModelSpec`; out
  of scope for the notebook-only pedagogical pass but worth fixing
  before the next pedagogical iteration so T3 can teach the more common
  bug directly.

_All previously-tracked open issues from the cross-platform verification pass
are now resolved. Subsequent work (mac-specific unified `py312_bayesmm` env
attempt) is tracked separately under "Local environment notes" below._

## Designed behavior (skip-safe contract)
(Documenting intentional behavior so future readers don't reopen these as bugs.)
- PyMC backend tests skip via the `optional_backend` marker (in
  `tests/conftest.py` + `tests/backend_support.py`) when `pymc` is not
  importable.
- SBI backend tests skip via the same marker when `sbi`/`torch` are not
  importable.
- Slow BioModels test (`tests/test_biomodels_slow.py`) skips via
  `pytest.importorskip("roadrunner")` when `libroadrunner` is unavailable.
- Optional MPI integration test (`tests/test_mpi_sweep_integration.py`)
  skips when `mpi4py` is not importable or world size < 2.

## Local environment notes
(Per-developer machine state, not bugs.)
- Optional backends are intentionally not installed in the lean
  `py314_bayesmm` env; install them in `py312_bayesmm_pymc` /
  `py312_bayesmm_sbi` per `bayesmm setup` guidance, OR use a single
  unified `py312_bayesmm` env (mac, verified 2026-05-15, see below).

### Unified `py312_bayesmm` env on macOS arm64 (2026-05-15, mac-specific)
- Goal: one conda env with **both** `pymc` and `sbi` working in the same
  Python interpreter so the full fast suite passes without backend-tag
  swapping. Useful for local iteration; project CI keeps the existing
  matrix and per-backend pins.
- Recipe (the entire repo's `environment.yml` already has the right pins;
  just install it under a different name):
  ```bash
  conda env create -f environment.yml -n py312_bayesmm
  conda run -n py312_bayesmm pip install -e . --no-deps
  # Optional: MPI integration test support (cf. tests/test_mpi_sweep_integration.py)
  conda install -n py312_bayesmm -c conda-forge -y mpi4py mpich
  ```
- Verified versions in this env (macOS arm64): Python 3.12.13,
  `pymc 5.28.0`, `arviz 0.23.4`, `pytorch 2.10.0`, `sbi 0.26.1`,
  `pydantic 2.13.4`, `mpi4py 4.1.1` + MPICH (Hydra 5.0.0).
- Verification: `pytest -q -m "not slow" tests` -> full suite GREEN
  (3 expected backend-deselected skips). Optional backends both used.
- **Critical pin discovered during this experiment**: `arviz>=0.17,<1`.
  Letting conda pull the latest arviz (1.x) breaks PyMC 5.x with
  `cannot import name 'concat' from 'arviz'` because arviz 1.0 removed
  `InferenceData` and `concat` from the top-level module. The
  `environment.yml` already pins this correctly; an ad-hoc
  `conda create ... pymc arviz` does NOT, since the conda solver picks
  the newest of each individual package.
- This experiment also surfaced the sbi 0.26 prior-support `UserWarning`
  that broke green CI on `eb894ab`; fixed in `c0fec53` by extending the
  `_sbi_warnings_filtered()` context to all five sbi entry points
  (training prep, training, build_posterior, posterior.sample,
  posterior.log_prob).
