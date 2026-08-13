# Pinned environments, and how dependency alerts are turned on

This directory answers one question: **which exact package versions produced a result you
trust?** `environment.yml` answers a different one — "what should a new student install?" —
and the two must not be conflated, which is why they live apart.

## Onboarding is unchanged

```bash
conda env create -f environment.yml     # still the way in. Nothing here is required.
```

`environment.yml` is deliberately **unpinned** so a new install resolves on whatever platform
and date it meets. Nobody needs a file from this directory to work through the tutorials.

## Reproducing an exact result

```bash
pip install -e . -c constraints/darwin-arm64.txt
```

Each file records every package present in `py314_bayesmm` at the moment a specific commit was
verified green. `darwin-arm64.txt` corresponds to the tag
`checkpoint/2026-08-13-review-verified` (`a6f9d7a`), where CI passed on three operating
systems, all four `Deep CI` environments passed, the full slow tutorial suite passed 12/12, and
both suites passed again under `MM_STRICT_ARTIFACTS=1`.

Installing from it is worth doing when a figure or number needs to be defended a year later,
and pointless otherwise.

## What is *not* here, and why

**Other platforms.** Only `darwin-arm64` is pinned. Conda packages differ across operating
systems, so a macOS pin list is not installable on Linux or Windows, and pretending otherwise
would be worse than the gap. Producing genuine cross-platform locks needs `conda-lock`, which
is not currently a dependency of this project:

```bash
pip install conda-lock                                     # a dev tool, not a runtime one
conda-lock -f environment.yml -p osx-arm64 -p linux-64 -p win-64
```

Adding that is a deliberate decision with real maintenance cost — every dependency change means
regenerating three platform locks — so it is left open rather than half-done.

**Vulnerability detection.** These files cannot tell you a pinned version has a CVE. They make
detection *possible* by giving GitHub's dependency graph exact versions instead of the open
ranges in `pyproject.toml`, but the alerting itself is a repository setting.

## Turning on security alerts (one-time, requires repo admin)

This is the part that actually addresses "a package I installed put a vulnerability in
everything", and it cannot be done from a file in the repository:

> **Settings → Code security → Dependabot**
> - **Dependency graph**: Enable
> - **Dependabot alerts**: Enable
> - **Dependabot security updates**: Enable

That combination is **security-only**: it opens a pull request when a package you depend on has
a *published vulnerability*, and never for routine version bumps.

**Do not enable "Dependabot version updates."** On a tree of ~180 packages that produces dozens
of pull requests a month, everyone stops reading them, and the channel becomes worse than
having no channel — the alert you needed arrives in a stream you have been trained to ignore.
Security-only fires a handful of times a year, and each one is worth reading.

## The check that keeps these honest

`tests/test_constraints_match_manifest.py` (fast suite) asserts that every pinned version
satisfies the ranges `pyproject.toml` declares. It catches the mundane failure that makes a
lock file a liability: a range is tightened, nobody regenerates the pins, and the file keeps
claiming a set the project no longer permits.

It is a **consistency** check, not a security one, and it skips — naming the platform — when no
pin file matches the machine it runs on, because a Linux runner has no business asserting about
macOS pins.

## Regenerating

Only from an environment you have **just verified green**, since the file's entire claim is
"this set passed":

```bash
python -m pip list --format=freeze | grep -v '^bayesian-metamodeling==' \
    > constraints/$(python -c "import platform,sys;print(f'{sys.platform}-{platform.machine()}')").txt
# then restore the header comment, which records what was verified and when
```

The local package is excluded on purpose: `pip install -e . -c <file>` refuses to run if the
file pins the package being installed. A test asserts that exclusion, because it is the kind of
thing that silently creeps back.
