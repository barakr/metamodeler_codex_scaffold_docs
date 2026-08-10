"""Ruff's `target-version` must not exceed the package's `requires-python`.

Regression test for a bug found on 2026-08-07.

`[tool.ruff] target-version` was `py314` while `[project] requires-python` was
`>=3.12`. Ruff's formatter takes target-version as permission to emit newer syntax,
and at py314 it rewrites

    except (OSError, json.JSONDecodeError):   ->   except OSError, json.JSONDecodeError:

which is PEP 758, valid only from Python 3.14. On 3.12 and 3.13 it is a
SyntaxError. So running `make fmt` on a 3.14 dev box produced a module that CI —
which runs 3.12 — could not import, on all three operating systems. Worse, the
formatter re-broke the file every time it was fixed, which read like an editor
fighting back rather than a configuration mismatch.

The rule is simple and worth pinning: the formatter targets the OLDEST interpreter
the package claims to support, not the newest one installed locally.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _load_pyproject() -> dict:
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    pytest.skip("tomllib requires Python 3.11+")


def _version_tuple(py_target: str) -> tuple[int, int]:
    """'py312' -> (3, 12)."""
    m = re.fullmatch(r"py(\d)(\d+)", py_target)
    assert m, f"unrecognised ruff target-version: {py_target!r}"
    return int(m.group(1)), int(m.group(2))


def _min_requires_python(requires: str) -> tuple[int, int]:
    """'>=3.12' -> (3, 12). Only the lower bound matters here."""
    m = re.search(r">=\s*(\d+)\.(\d+)", requires)
    assert m, f"could not read a lower bound from requires-python={requires!r}"
    return int(m.group(1)), int(m.group(2))


@pytest.mark.contract
def test_ruff_target_version_does_not_exceed_requires_python():
    data = _load_pyproject()
    requires = data["project"]["requires-python"]
    target = data["tool"]["ruff"]["target-version"]

    minimum = _min_requires_python(requires)
    targeted = _version_tuple(target)

    assert targeted <= minimum, (
        f"[tool.ruff] target-version = {target!r} is newer than "
        f"[project] requires-python = {requires!r}. Ruff will format using syntax the "
        f"package's own minimum Python cannot parse — this shipped `except A, B:` "
        f"(PEP 758, 3.14+) into a codebase supporting 3.12, and CI could not import "
        f"the module. Set target-version to py{minimum[0]}{minimum[1]}."
    )
