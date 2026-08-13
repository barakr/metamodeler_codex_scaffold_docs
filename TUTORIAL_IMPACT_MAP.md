# Tutorial impact map — stage 1-3 validation changes

Produced by a 12-agent audit of every notebook against the behaviour changes on
`feature/design-security-review`. **Tutorial_1 is already fixed and passing**; the rest is
the outstanding work.

Two kinds of breakage, and the second is the dangerous one:

- **`raises`** — the cell now errors, so CI tells you.
- **`teaches_false`** — the cell still runs, but the prose asserts a limitation that no
  longer exists. **Nothing will ever fail to tell you.** This is most of the list below,
  and it is the reason this audit covered all twelve notebooks rather than the four that
  went red.

## Summary

| Notebook | findings | of which raise |
|---|---|---|
| `Tutorial_3` | 21 | 2 |
| `Tutorial_4` | 10 | 1 |
| `Tutorial_1` *(fixed)* | 8 | 1 |
| `Tutorial_2` | 1 | 0 |

## Details

### Tutorial_3

**`raises`** — # Self-check: T3's lessons, re-derived from scratch. Designed to fail on a notebook

> assert rc_mismatch_validate == 0 and rc_mismatch_plan == 0, (

*Fix:* Rewrite Step 5 around a contract that is still unenforced (e.g. rename only adapter.input_mapping[0].var, or an unknown adapter.id) and assert the new outcome; or keep the grid rename and flip the assertions to rc_mismatch_validate == 1 / rc_mismatch_plan == 1 with an assertion on the error path and message text. Drop the KeyError('a')/run_store.py claim entirely, or re-derive it from the adapter-side rename that still reaches the sweep.

**`raises`** — # --- 5) The unenforced contracts are still unenforced. ----------------------

> raise AssertionError(             f"{_label} now FAILS validation ({_locs}). Good news about the framework, "             "bad news about this notebook: Steps 5-6 and the 'Why this matters' cell "             "claim these are unchecked. Update them."         )

*Fix:* Invert this block: assert that a renamed design.grid key and an out-of-support grid now DO fail, and keep only `an unknown adapter.id` (plus, if wanted, an adapter.input_mapping[*].var rename) in the still-unenforced list. Also assert the message fragments "names variables that are not declared in io_schema.inputs" and "contains values outside the declared support" so the new lesson is pinned.

**`teaches_false`** — ## Final check: every lesson in this notebook is still true

> - the unenforced contracts are **still unenforced** — a renamed `design.grid` key and an out-of-support grid both still validate cleanly.

*Fix:* Replace with: the two cross-section contracts are now enforced at validation time — a renamed design.grid key and an out-of-support grid are both rejected with the root-level path — while adapter.input_mapping[*].var and adapter.id remain unchecked and are what Steps 5-6 should now demonstrate.

**`teaches_false`** — ## Why this tutorial matters — "A spec is a contract, and the first job of this tutorial..."

> > **Validation is per-section.** Nothing checks that the variable names in `design.grid`, in `io_schema.inputs[*].name` and in `adapter.input_mapping[*].var` agree with each other. Nothing checks that `design.grid` values fall inside the declared `support`. Nothing checks that `adapter.id` names an adapter that exists. `ModelSpec` has no cross-section validator at all — read `src/bayesian_metamodeling/spec/modelspec.py` and you will find every va

*Fix:* Rewrite the block quote: validation is per-section EXCEPT for one root-level validator, ModelSpec.check_design_against_io_schema, which cross-checks design.grid keys and values (and design.sobol.ranges) against io_schema.inputs. What remains unchecked: adapter.input_mapping[*].var against io_schema names, adapter.id against the registry, and whether model.artifact.entrypoint exists. Change "two break/repair cycles the validator catches ... then two breaks it does not catch" to reflect that the grid-name and support breaks are now caught (with the error paths that come with a root model_validator), and that the remaining uncaught break is the 

**`teaches_false`** — ## The map: anatomy of a `ModelSpec` — "Keep this picture in view while you debug."

> The dashed arrows are the part to remember. They are contracts the framework genuinely depends on and **never checks**: one variable name has to appear identically in three places, and if it does not, `validate` still says yes.

*Fix:* Say that one of the two arrows is now machine-checked and one is not, and make the figure show the difference (see the figure-cell finding). The remaining lesson — a name must appear identically in three places, and only two of the three pairings are validated — is stronger than the old one, not weaker.

**`teaches_false`** — import matplotlib.pyplot as plt / from matplotlib.patches import FancyArrowPatch, Rectangle (anatomy

> unchecked(2, 3, "design.grid keys  ==  io_schema.inputs[*].name", 0.82)

*Fix:* Draw the design.grid<->io_schema arrow in the 'validated' style (a third colour, or reuse the red 'really raises' convention) with the label "design.grid keys/values checked against io_schema.inputs", and keep only the adapter arrow orange/dashed. Update the two trailing print lines accordingly. The `design` block's example error can stay, but consider adding the new message "design.grid names variables that are not declared in io_schema.inputs" as a ModelSpec-level (not design-level) error, since it is attributed to the root.

**`teaches_false`** — ## Predict the error before you read it

> 2. **The category**: missing field, wrong type, or failed constraint. Those are the three you will actually see. There is no fourth "cross-field" category in this framework — which is exactly what Steps 5 and 6 are about.

*Fix:* Add the fourth category — cross-section — and note its tell: the path is empty (the CLI prints `- : Value error, ...`) because the validator is attached to ModelSpec itself, one level above `design`. That extends the notebook's real lesson (path depth diagnoses which validator fired: leaf = field_validator, section = section model_validator, empty = root model_validator).

**`teaches_false`** — ## Step 5: A break the validator does **not** catch

> ## Step 5: A break the validator does **not** catch

*Fix:* Either retitle to "A break the validator now catches (and used to not)" and use it to teach the root-level error path, or move the demonstration to the still-unenforced contract: rename adapter.input_mapping[0].var instead of the grid key, which still passes validate and plan and still dies later. Keep the 'predict first' questions — their answers change, which is the point.

**`teaches_false`** — MISMATCH = root / "tmp/tutorials_modelspec_mismatch.json"

> payload["design"]["grid"] = {"alpha": grid["a"], "b": grid["b"]}   # the whole bug

*Fix:* Keep the cell but expect failure: print the new error and assert exit code 1, showing the empty error path as the signature of a root-level cross-section rule. If Step 5 is retargeted at the adapter, change the mutation to payload["adapter"]["input_mapping"][0]["var"] = "alpha" (leaving design.grid and io_schema agreeing), which still validates and plans cleanly.

**`teaches_false`** — # `run` is the first command that has to make those three name lists agree.

> # `run` is the first command that has to make those three name lists agree.

*Fix:* Retarget the run to a spec that still validates (adapter-side rename) so the late-failure lesson survives, and update the comment to "run is the first command that has to make the ADAPTER's name list agree with io_schema — validate now covers design.grid". Note also that change 5 means the captured output will now begin with a new line, `Entrypoint: python -m examples.toy_program.run`, printed once per sweep before the first design point; the cell's verbatim output block needs that line.

**`teaches_false`** — ### What that silence cost

> `validate`: **pass**. `plan`: **pass** — and it happily enumerated nine design points whose variable is called `alpha`, a name the model has never heard of.

*Fix:* Rewrite around the surviving version of the bug, which the cell already describes in its second bullet ("It gets worse if you are more consistent"): rename the key in design.grid AND adapter.input_mapping so io_schema alone still says `a` — under the new validator that is now caught too, so the genuinely surviving case is renaming ONLY adapter.input_mapping[*].var. That one still runs every subprocess and still dies in run_store.persist_sweep, which keeps the 'silence has a cost' lesson intact with a true example. The quoted persist_sweep snippet (input_names / row[name] = float(result["point"][name])) is still accurate at storage/run_store.p

**`teaches_false`** — ## Step 6: `support` is a claim, not a fence

> So on a **grid** design, `support` clips nothing, warns about nothing, rejects nothing.

*Fix:* Retitle and rewrite: support is now a fence at validation time for grid and sobol designs alike, and still a scientific claim about where the model is trustworthy. The remaining true version of 'a claim, not a fence' is that nothing checks whether the support you declared is the regime your model is actually calibrated in — which is the Scientific Checkpoint's argument and survives intact.

**`teaches_false`** — OUTSIDE = root / "tmp/tutorials_modelspec_outside_support.json"

> payload["design"]["grid"] = {"a": [-500.0, 900.0], "b": [0.0]}

*Fix:* Keep the break and expect rejection, quoting the new message; then show the contrast the notebook still needs — that a value INSIDE support but far outside the calibrated regime is still accepted, which is the surviving scientific point. The trailing 'repaired spec, for contrast' plan on tmp/tutorials_modelspec_edit.json still returns 0 and 9 points, so it needs no change.

**`teaches_false`** — ## Scientific checkpoint: what a contract actually protects

> `io_schema.inputs[*].support` is read by exactly one thing in the entire framework: `plan_sobol_points`, which uses it to map unit-cube Sobol samples onto your parameter range

*Fix:* Say support is read in two places: the validator (which rejects grid values outside it, and rejects design.sobol.ranges that disagrees with it) and plan_sobol_points (which maps unit-cube samples onto it). The follow-on sentence "plan_grid_points never looks at support at all — it enumerates design.grid verbatim" is still true of the planner and can stay, provided the validator is named first.

**`teaches_false`** — The bridge to everything downstream: **the sweep produced inside `support` *is* the surrogate's trai

> `support` is therefore the boundary between interpolation and extrapolation for every metamodel built on top of it — and since nothing enforces it, it is a boundary only you can hold.

*Fix:* Change to: the framework now enforces that your DESIGN stays inside the support you declared — what it cannot enforce is that the support you declared is the regime your model is actually trustworthy in. That is a sharper version of the same lesson and the rest of the paragraph (too narrow / too wide, units, surrogate training set) needs no change.

**`teaches_false`** — | `io_schema` | The variable contract: typed `inputs`/`outputs` ... | (contracts table)

> | `io_schema` | ... | At least one input and one output; `type` an enum; `units` a non-empty string; `support` exactly two floats with max > min; `dims` required for `type: "array"`. Names are cross-referenced **nowhere**. |

*Fix:* Replace the last sentence with: names are cross-referenced against design.grid / design.sobol.ranges by ModelSpec.check_design_against_io_schema, and support is used to range-check grid values; names are still cross-referenced against adapter.input_mapping[*].var nowhere.

**`teaches_false`** — | `design` | The DOE contract: `strategy: grid \| sobol` plus that strategy's config. | (contracts t

> | `design` | ... | The strategy enum, and that the matching config block is present and non-empty. Not the variable names, not the values, not the resulting point count. |

*Fix:* Rewrite the right column: strategy enum; the matching config block present; for sobol, a typed SobolDesignSpec requiring n_points >= 1 and forbidding unknown keys, with ranges required to agree with io_schema support; for grid, keys must be declared inputs and values must lie inside their support. Still unchecked: the resulting point count (a non-power-of-2 n_points is a warning from the planner, not a validation error).

**`teaches_false`** — | `model` | Identity (`name`, `version`) and the artifact to execute ... | (contracts table)

> | `model` | ... | Both conditionals, verbatim. Whether the entrypoint *exists* is never checked. |

*Fix:* Add to the right column: name and biomodels_id must be path-safe identifiers (^[A-Za-z0-9][A-Za-z0-9._-]*$), and local_sbml_path must be project-relative with no '..' — the same containment property the storage row already advertises. Keep 'whether the entrypoint exists is never checked', which is still true.

**`teaches_false`** — ## One name, five layers

> 2. **The DOE points** — the planner builds each point dict from `design.grid`'s *keys*. Step 5 is what happens when layers 1 and 2 disagree.

*Fix:* Say that layers 1 and 2 are now checked against each other by the validator, and that the first genuinely unguarded hop is layer 2 -> layer 3 via adapter.input_mapping (and layer 3 -> layer 4, where a mismatched SurrogateSpec.inputs silently yields 'No successful rows found'). The five-layer chain is still the right picture; only the position of the first unguarded hop moves.

**`teaches_false`** — LAYERS = [ ("1. ModelSpec", "io_schema.inputs[0].name", "model.toy.grid.json"), ... (five-layer figu

> print("Rename the variable in one layer and the failure surfaces in the NEXT one -") print("as a KeyError (layer 3), as 'No successful rows found' (layer 4), or as a")

*Fix:* Change the printed lines to: a rename inside layers 1-2 is now caught by the validator, because it compares them; a rename from layer 2 onward still surfaces in the NEXT layer — KeyError at layer 3 (via a mismatched adapter mapping), 'No successful rows found' at layer 4, a silently uninformed coupling at layer 5. Optionally relabel the bracket "the validator can see — and compare — this far".

**`teaches_false`** — ## Troubleshooting (table)

> | `validate` passes, then `run` dies somewhere unrelated | You broke an unenforced cross-section contract (Step 5) or you are outside `support` (Step 6). | Run `bayesmm plan` first ... |

*Fix:* Replace the causes with the ones that survive: a name in adapter.input_mapping[*].var that no design point carries, an adapter.id the registry does not know, or an entrypoint that does not exist. Add a new row for the new symptom — `- : Value error, design.grid names variables that are not declared in io_schema.inputs` — whose tell is the EMPTY path before the colon, meaning a root-level cross-section validator on ModelSpec rather than a rule inside any one section.

### Tutorial_4

**`raises`** — import copy
import json

from bayesian_metamodeling.designs.planner import DOEPla

> load_and_validate_modelspec(rogue)  # the validator is happy

*Fix:* Invert the demo: keep the rogue grid, but wrap it in `try: load_and_validate_modelspec(rogue) except ValidationError as exc: print(exc)` and present it as the validator *catching* the out-of-domain levels. Keep the second half (pop `support` from the sobol spec, expect DOEPlanError) unchanged — it still behaves as written. If the didactic point about `plan_grid_points` itself never reading `support` is worth keeping, show it by calling `plan_grid_points` on a hand-built ModelSpec that bypasses nothing, or state plainly that the planner does not check but the spec validator now does.

**`teaches_false`** — ### The two strategies read different parts of the spec

> So a grid design can sample outside the domain the spec itself declares, and nothing complains. Run the cell and watch it happen.

*Fix:* Rewrite to: `plan_grid_points` still reads only `design.grid` and never consults `support`, but the spec validator now refuses a grid whose levels fall outside the declared support — so the mistake is caught at `bayesmm validate` time rather than propagating into the sweep. Keep the contrast with sobol (whose box *is* the support, enforced in the planner), which is still accurate.

**`teaches_false`** — **The rule:** with `sobol`, the box is the support and the framework enforces it.

> With `grid`, *you* are responsible for keeping your levels inside the domain you declared — nothing checks it, at plan time or at run time. The failure is silent and it propagates

*Fix:* Replace with the current rule: the framework enforces the box for both strategies, but by different mechanisms — sobol derives it from `support` in the planner, grid is cross-checked against `support` by the ModelSpec validator. Note that the check only fires when `support` is declared (the validator skips inputs with `support is None`), which is the residual case where the author is still on their own.

**`teaches_false`** — ## Troubleshooting  (table row: "A grid sweep sampled outside the box the spec declares")

> | A grid sweep sampled outside the box the spec declares | `plan_grid_points` never reads `io_schema.inputs[].support`; `bayesmm validate` does not check it either | Nothing will tell you — check your levels yourself, or use `sobol`, whose box *is* the support. Step 1 reproduces the failure. |

*Fix:* Change the Symptom to the new failure — a `ValidationError` reading "design.grid['a'] contains values outside the declared support" — with Cause "a grid level sits outside the support you declared for that input" and Fix "widen `io_schema` support or correct the grid levels; the two must agree". Point at the rewritten Step 1 cell.

**`teaches_false`** — ### Read that output before moving on

> 3. **scipy warned about the Sobol design.** `UserWarning: The balance properties of Sobol' points require n to be a power of 2` — because we asked for 9.

*Fix:* Quote the new warning and its class: `SobolBalanceWarning: design.sobol.n_points=9 is not a power of 2 ... Consider 8 or 16.` Attribute it to `bayesian_metamodeling.designs.planner`, and mention that the planner deliberately suppresses scipy's duplicate of the same fact so the actionable version (which sizes to use) is the one you see.

**`teaches_false`** — ## Step 1: Plan both designs — nothing is executed

> it is deliberately the wrong number for Sobol — scipy will say so out loud in the output below, and that warning is one of this tutorial's lessons rather than noise to scroll past

*Fix:* Change "scipy will say so out loud" to "the planner will say so out loud — a `SobolBalanceWarning` from `designs/planner.py`, which also names the sizes you should have asked for".

**`teaches_false`** — ## Troubleshooting  (first table row, Symptom column)

> | `UserWarning: The balance properties of Sobol' points require n to be a power of 2` | `n_points` is not a power of two | Ask for 8, 16, 32… ...

*Fix:* Replace the Symptom cell with the emitted text: `SobolBalanceWarning: design.sobol.n_points=9 is not a power of 2 ... Consider 8 or 16.` The Cause and Fix columns remain correct as written.

**`teaches_false`** — **Predict before you run.** Both DOEs place 9 points on the box `a, b ∈ [0, 2]`.

> With 9 points — one past `2³` — that guarantee is already broken, which is precisely what scipy warned about.

*Fix:* Change "which is precisely what scipy warned about" to "which is precisely what the `SobolBalanceWarning` in Step 1 was about".

**`stale_reference`** — ## Step 5: `scramble`, `seed`, and what "deterministic" actually means

> **`seed` is read only when `scramble` is true.** `plan_sobol_points` defaults `scramble` to `False`, and with an unscrambled engine scipy ignores the seed entirely.

*Fix:* Attribute the default to the spec: "`design.sobol` is a typed `SobolDesignSpec` whose `scramble` field defaults to `False` — note that **scipy's own default is `True`**, so the spec is the opposite of what a `qmc.Sobol` reader expects." Same edit for the troubleshooting row that says "`scramble` is false (the planner's default)".

**`stale_reference`** — ## Troubleshooting  (table row: "You changed `seed` and got the same Sobol points back")

> | You changed `seed` and got the same Sobol points back | `scramble` is false (the planner's default) and scipy ignores `seed` for an unscrambled engine | Set `"scramble": true` in `design.sobol`. Step 5 demonstrates both cases. |

*Fix:* Change "(the planner's default)" to "(the `SobolDesignSpec` field default — note scipy's own default is the opposite)".

### Tutorial_1 *(fixed)*

**`raises`** — import copy
import json

from bayesian_metamodeling.designs.planner import plan_points, render_plan_

> broken_spec = load_and_validate_modelspec(broken)  # <- does NOT raise

*Fix:* Invert the demonstration: keep the same `broken` payload, but wrap the call in `with pytest.raises(...)`-style handling in plain Python — e.g. `try: load_and_validate_modelspec(broken); raise AssertionError("expected a validation error") except ValidationError as exc: print(exc)` — and print the new message. Then drop the `plan_points(broken_spec)` half (there is no `broken_spec` to plan) or replace it with a *legal* spec whose DOE is merely wasteful, to keep the "read plan's output" habit alive. Update the trailing comment `# <- does NOT raise` to say the opposite.

**`teaches_false`** — import copy
import json

from bayesian_metamodeling.designs.planner import plan_points, render_plan_

> print("validate: OK — no cross-block check happened\n")

*Fix:* Replace with something like `print("validate: REJECTED — the cross-block check caught it:\n", exc)`, printing the real error text so the reader sees `design.grid names variables that are not declared in io_schema.inputs: ['c']`.

**`teaches_false`** — ### What `validate` does *not* check

A green `validate` means *each block is well-formed*, not *the

> There is no cross-block validator in `ModelSpec` (`src/bayesian_metamodeling/spec/modelspec.py`) — every rule lives inside one sub-block. So all of these pass validation today:

*Fix:* Rewrite the section around what validation now *does*: state that `ModelSpec` gained a cross-block validator that checks `design.grid` keys and values against `io_schema.inputs` (and `design.sobol.ranges` against `support`), delete bullets (a) and (b), and keep bullet (c) as the remaining genuine gap — an `adapter.input_mapping` entry for an undeclared variable still passes. Retitle to something like "What `validate` checks across blocks — and what it still doesn't", and keep the "read `plan`'s output" habit motivated by the adapter gap and by budget-sizing rather than by undeclared grid keys.

**`teaches_false`** — ### What `validate` does *not* check

A green `validate` means *each block is well-formed*, not *the

> Launching it would not save you either: the run dispatches every point and then dies in the storage layer with `KeyError: 'b'` while writing the table. **So read `plan`'s output; never trust `validate` alone.**

*Fix:* Replace with the current story: the spec is rejected at validation time, before any point runs, and the error names the undeclared variable and lists the declared inputs. Re-anchor the takeaway on what `plan` still adds that `validate` cannot — the actual point count and the concrete coordinates you are about to spend compute on.

**`teaches_false`** — ## Step 1: Validate and plan

**`validate` and `plan` are two distinct read-only steps**, intentiona

> Use it to budget the work before launching it (9 points here; a real biological sweep can be thousands) — and, as the cell after next shows, to catch a class of error `validate` structurally cannot see.

*Fix:* Amend the `validate` bullet to "checks each block's shape *and* the agreement between `design` and `io_schema`", and change the `plan` bullet's justification from "catch a class of error `validate` structurally cannot see" to budgeting the sweep and eyeballing the actual coordinates (plus the adapter-mapping gap, which validation still does not cover).

**`teaches_false`** — ## Scientific checkpoint

Sixty seconds, answers below. A student who understood can do these from m

> (4) The actual DOE points — `validate` only inspects blocks in isolation, so a grid over an undeclared variable sails through it, while `plan` shows the points and the missing variable immediately.

*Fix:* Rewrite answer (4) to: `validate` now cross-checks `design` against `io_schema`, so an undeclared or out-of-support grid variable is rejected outright; what `plan` still adds is the concrete point count and coordinates — the budget — plus the classes validation does not cover (e.g. an `adapter.input_mapping` entry for an undeclared variable). Keep question 4 as written.

**`teaches_false`** — ## Common mistakes

- Running the notebook from the wrong folder without `src/` in scope — the boots

> - Treating a green `validate` as proof the spec is coherent. It checks blocks in isolation; read `plan`'s points.

*Fix:* Narrow the bullet to the coherence checks that genuinely remain outside validation — chiefly `adapter.input_mapping` entries naming undeclared variables — and say plainly that design/io_schema disagreements are now caught by `validate` itself.

**`teaches_false`** — ## Recap: what T1 established

- A **spec** is the whole contract — artifact, `io_schema`, `design`,

> - `validate` checks blocks in isolation; `plan` is where a nonsensical DOE becomes visible. Use both, in that order.

*Fix:* Restate as: `validate` checks each block *and* that `design` agrees with `io_schema`; `plan` is where you see the actual points and their cost before spending it. Use both, in that order.

### Tutorial_2

**`teaches_false`** — **What the plan is telling you.** `validate` type-checks the spec — it never tou

> **What the plan is telling you.** `validate` type-checks the spec — it never touches the model.

*Fix:* Rewrite the opening sentence to cover the cross-block check and use it as the teaching point cell 8 already sets up, e.g.: "`validate` checks the spec without touching the model — both its types and, since the design/schema cross-check, whether the two halves of the spec agree: every `design.grid` key must be a declared `io_schema.inputs` variable, and every grid value must lie inside that variable's `support`. That is why the cell above widened the grid and the support together; widening only one is now a validation error rather than a surprise mid-sweep." Optionally add a one-line comment beside `SPEC_KON["io_schema"]["inputs"][0]["support"

## Unaffected

`Tutorial_0`, `Tutorial_5`, `Tutorial_6`, `Tutorial_7a`, `Tutorial_7b`, `Tutorial_7c`, `Tutorial_8`, `Tutorial_9`

### Why Tutorial_5 is in that list despite failing CI

`Tutorial_5` has **no static findings**. Its CI failure is a *cascade*: its surrogate reads
`tmp/tutorials/toy_store`, which `Tutorial_1` writes. T1 crashing left that store absent in a
fresh checkout, so T5 fitted on inadequate data and its "parameter uncertainty grows away
from the data" assertion failed. Fixing T1 should clear it.

It passed **locally** only because that store already existed from earlier runs. That is worth
recording on its own: **local tutorial runs are contaminated by stale shared state and are not
a faithful check.** A clean-checkout run is the only honest one, which is what Deep CI does.
