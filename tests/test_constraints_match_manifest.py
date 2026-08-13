"""A pinned constraints file must agree with the ranges `pyproject.toml` declares (S7).

A lock that silently disagrees with its manifest is the worst of both worlds: it looks like
provenance and isn't. The concrete failure is mundane and easy to miss — someone tightens
`pymc>=5,<6` to `>=5.30`, nobody regenerates the pins, and the file keeps claiming a set that
the project no longer permits.

Scope, stated plainly so nobody mistakes this for more than it is:

- it checks the **direct** dependencies from `pyproject.toml` (core + every optional extra),
  because those are the ones the project actually makes promises about;
- transitive packages are pinned in the file but not range-checked, since the project declares
  no ranges for them;
- it is a **consistency** check, not a security check. It cannot tell you a pinned version has
  a CVE. That is what GitHub's Dependabot security alerts are for — see `REPRODUCIBILITY.md`
  for the repository settings that turn them on.

Fast, and deliberately skipped rather than failed when the pins were resolved on another
platform: the pins are per-platform by nature, and a Linux CI runner has no business asserting
about macOS pins. The skip names the platform so it is never mistaken for a pass.
"""

from __future__ import annotations

import platform
import re
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
#: Deliberately a name GitHub's dependency graph recognises. See REPRODUCIBILITY.md:
#: at `constraints/darwin-arm64.txt` the file was never scanned, so Dependabot matched
#: CVEs against pyproject.toml's seven open ranges and ignored ~175 transitive packages.
PINS = REPO_ROOT / "requirements.txt"


def _platform_tag() -> str:
    return f"{sys.platform}-{platform.machine()}"


def _recorded_platform() -> str | None:
    """The platform named in the file's header, so a foreign machine can skip honestly."""
    if not PINS.exists():
        return None
    for line in PINS.read_text().splitlines():
        if line.startswith("#") and "Resolved on " in line:
            return line.split("Resolved on ", 1)[1].split(".")[0].strip()
    return None


def _constraints_path() -> Path | None:
    """The pin file, when it was resolved on this platform.

    Returns None on any other machine: these are exact versions including conda-provided
    packages, so a Linux runner asserting about macOS pins would be noise, not signal.
    """
    if not PINS.exists():
        return None
    recorded = _recorded_platform()
    return PINS if recorded in (None, _platform_tag()) else None


def _parse_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        pins[name.strip().lower().replace("_", "-")] = version.strip()
    return pins


def _declared_requirements() -> tuple[list[str], list[str]]:
    """Return (core, optional) requirement strings.

    The split matters. Core dependencies are installed in *every* environment, so a missing
    pin for one means the constraints file was generated somewhere unexpected. Optional
    extras are a different story: `py314_bayesmm` deliberately does not install the
    `biomodels` extra, because `libroadrunner` is PyPI-only and the most platform-fragile
    dependency in the project (CLAUDE.md, "Conda Environments"). An absent pin for an extra
    this environment never had is correct, not a defect — so extras are range-checked only
    when they are present.
    """
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    project = data.get("project", {})
    core = list(project.get("dependencies", []))
    optional: list[str] = []
    for extra in project.get("optional-dependencies", {}).values():
        optional.extend(extra)
    return core, optional


_REQ = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(.*)$")
_BOUND = re.compile(r"(>=|<=|==|!=|<|>)\s*([0-9][0-9A-Za-z.*+-]*)")


def _version_tuple(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in text.split(".")[:4]:
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _satisfies(version: str, operator: str, bound: str) -> bool:
    left, right = _version_tuple(version), _version_tuple(bound)
    if operator == ">=":
        return left >= right
    if operator == ">":
        return left > right
    if operator == "<=":
        return left <= right
    if operator == "<":
        return left < right
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    return True  # pragma: no cover - unreachable for the operators pip allows here


def test_the_pin_file_has_a_scanner_readable_name():
    """The name is the feature.

    GitHub's dependency graph only reads recognised manifest filenames. This file used to be
    `constraints/darwin-arm64.txt`, which the scanner ignores — so Dependabot watched the seven
    ranges in pyproject.toml and none of the ~175 transitive packages. Renaming it was the
    whole fix; a future tidy-up that moves it back would silently undo that.
    """
    assert PINS.name == "requirements.txt", (
        f"the pin file is named {PINS.name!r}; GitHub's dependency graph only reads known "
        "manifest names, so renaming it silently drops ~175 packages out of vulnerability "
        "scanning. See REPRODUCIBILITY.md."
    )
    assert PINS.exists(), "requirements.txt is missing"
    assert sum(1 for line in PINS.read_text().splitlines() if "==" in line) > 50, (
        "requirements.txt holds almost no pins — it is supposed to be a full environment record"
    )


def test_the_file_warns_against_installing_it_into_a_conda_env():
    """A root requirements.txt invites `pip install -r`, which breaks a conda environment."""
    header = PINS.read_text()[:2000]
    assert "DO NOT" in header and "conda env create" in header, (
        "the header must warn against `pip install -r` and point at the real install path; "
        "this file lists conda-provided packages and reinstalling them with pip breaks the env"
    )


def test_pins_satisfy_every_declared_range():
    path = _constraints_path()
    if path is None:
        pytest.skip(
            f"requirements.txt records pins resolved on {_recorded_platform()}, "
            f"not this platform ({_platform_tag()}); exact versions are not comparable"
        )

    pins = _parse_pins(path)
    core, optional = _declared_requirements()
    violations: list[str] = []
    missing_core: list[str] = []

    def check(requirement: str, *, required: bool) -> None:
        match = _REQ.match(requirement)
        if match is None:  # pragma: no cover - malformed requirement
            return
        name, rest = match.group(1).lower().replace("_", "-"), match.group(2)
        if name not in pins:
            if required:
                missing_core.append(name)
            return  # an extra this environment does not install; nothing to check
        for operator, bound in _BOUND.findall(rest):
            if not _satisfies(pins[name], operator, bound):
                violations.append(
                    f"{name}=={pins[name]} violates '{requirement.strip()}' "
                    f"(fails {operator}{bound})"
                )

    for requirement in core:
        check(requirement, required=True)
    for requirement in optional:
        check(requirement, required=False)

    assert not violations, (
        "Pinned versions disagree with the ranges pyproject.toml declares:\n  "
        + "\n  ".join(violations)
        + f"\n\nEither a range changed without regenerating {path.name}, or the pins were "
        "edited by hand. Regenerate from an environment you have just verified green — see "
        "the header of that file."
    )
    assert not missing_core, (
        f"pyproject declares {sorted(set(missing_core))} as a CORE dependency, but "
        f"{path.name} does not pin it. Every environment installs the core set, so a missing "
        "pin means this file was generated somewhere unexpected."
    )


def test_the_local_package_is_not_pinned_against_itself():
    """`pip install -e . -c <file>` fails outright if the file pins the package being built."""
    path = _constraints_path()
    if path is None:
        pytest.skip(f"pins were resolved on {_recorded_platform()}, not {_platform_tag()}")
    assert "bayesian-metamodeling" not in _parse_pins(path), (
        "the constraints file must not pin bayesian-metamodeling itself — "
        "`pip install -e . -c <file>` would refuse to install the editable package"
    )
