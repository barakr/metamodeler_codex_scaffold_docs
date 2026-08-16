# Reproducibility and dependency alerts

Two questions that get confused with each other, answered separately.

| Question | File |
|---|---|
| What should a new student install? | `environment.yml` — unpinned, resolves fresh |
| Which exact versions produced a result I trust? | `requirements.txt` — 181 pins from a verified-green commit |

## Onboarding is unchanged

```bash
conda env create -f environment.yml
```

Still the only thing anyone needs to work through the tutorials. It is deliberately
**unpinned** so an install resolves on whatever platform and date it meets — a pinned
onboarding file is one that eventually stops working.

> **Do not `pip install -r requirements.txt` into a conda environment.** It lists 181
> packages, many of them conda-installed (pymc, torch, …), and reinstalling those with pip on
> top of conda reliably breaks the environment. The file's header says the same thing, louder.

## Reproducing an exact result

```bash
pip install -e . -c requirements.txt      # -c = constraints; installs nothing by itself
```

Those versions **started** as the set present when `checkpoint/2026-08-13-review-verified`
(`a6f9d7a`) was green: CI on three operating systems, all four `Deep CI` environments,
`make fast`, the slow tutorial suite 12/12, and both suites again under
`MM_STRICT_ARTIFACTS=1`.

They do not stay frozen there, and should not. Dependabot opens a pull request whenever a
pinned package has a published vulnerability, and each merged fix edits one line. So the file
is **"the verified set, plus every security fix applied since"**, and
`git log --follow requirements.txt` is the exact provenance.

Worth doing when a figure or number has to be defended a year later. Pointless otherwise.

## Why the file is named `requirements.txt`

Not for installation — for **scanning**. GitHub's dependency graph only reads recognised
manifest filenames (`requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile`,
`poetry.lock`). An earlier version of this file lived at `constraints/darwin-arm64.txt`, which
is *not* a name the scanner knows, so Dependabot would have matched vulnerabilities only
against the seven open ranges in `pyproject.toml` — leaving the roughly **175 transitive
packages unwatched**, which was the entire reason for enabling alerts.

Coverage, concretely:

| | packages watched |
|---|---|
| `pyproject.toml` alone | 7 |
| plus `requirements.txt` | 182 |

## Turning the alerts on (one-time, per repository, needs admin)

This cannot be done from a file in the repository.

> **Settings → Code security → Dependabot**, on each repo:
> - Dependency graph → **Enable**
> - Dependabot alerts → **Enable**
> - Dependabot security updates → **Enable**
> - Grouped security updates → **Enable** (batches several fixes into one PR)

Both repositories need it separately:

- `https://github.com/barakr/metamodeler_codex_scaffold_docs/settings/security_analysis`
- `https://github.com/barakr/tcr_signaling/settings/security_analysis`

The account-wide page at `https://github.com/settings/security_analysis` only sets defaults
for **new** repositories — worth ticking so future work starts protected, but it does not
retrofit these two.

**Version updates stay off**, and require no action: they are switched on by adding a
`.github/dependabot.yml`, and there deliberately isn't one. On ~180 packages, routine bumps
would mean dozens of pull requests a month; everyone stops reading them, and the alert that
mattered arrives in a channel you have been trained to ignore. Security-only fires a handful
of times a year.

**Check it took effect:** open
`https://github.com/barakr/metamodeler_codex_scaffold_docs/security/dependabot`. If it is on
you will see "No open alerts" or a list; if not, the page offers to enable it. The graph takes
a few minutes to populate after first enabling.

## What is not covered

**Other platforms.** These pins were resolved on macOS/arm64. Conda packages differ by
operating system, so the exact set is not installable on Linux or Windows. Genuine
cross-platform locks need `conda-lock`, which is not a dependency of this project:

```bash
pip install conda-lock
conda-lock -f environment.yml -p osx-arm64 -p linux-64 -p win-64
```

That is a deliberate decision with real maintenance cost — every dependency change means
regenerating three platform locks — so it is left open rather than half-done.

**The pins are not a security check.** They cannot tell you a version has a CVE. They make
detection *possible*; Dependabot does the detecting.

## The check that keeps this honest

`tests/test_constraints_match_manifest.py` (fast suite) asserts every pin satisfies the ranges
`pyproject.toml` declares. It catches the mundane way a pin file becomes a liability: a range
is tightened, nobody regenerates, and the file keeps claiming a set the project no longer
permits. Verified it can fail.

It is a **consistency** check, not a security one, and it skips — naming the platform — when
the pins were resolved on a different machine, because a Linux runner has no business
asserting about macOS pins.

## Regenerating

Only from an environment you have **just verified green**, since the file's whole claim is
"this set passed":

```bash
python -m pip list --format=freeze | grep -v '^bayesian-metamodeling=='
# ...then restore the header, which records what was verified and when
```

> **Regenerating can silently undo a security fix.** The freeze reads your *local*
> environment, which may still hold the old, vulnerable version of something Dependabot has
> already fixed here. Re-freezing blindly reverts those bumps, and Dependabot has to find them
> all over again — with a window in between where the repository claims a version it has
> already been told is unsafe.
>
> Update your environment **first**, then regenerate, then diff against the previous file and
> confirm no version went *backwards*:
>
> ```bash
> git diff requirements.txt        # every change should be a version going UP
> ```
