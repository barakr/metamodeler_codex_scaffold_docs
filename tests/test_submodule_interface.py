"""Contract tests between the framework and the `projects/tcr_signaling` submodule.

This is the only place the two are tested *together*. The framework's own suite
never sees the submodule (`testpaths = tests`, and CI checks out with
`submodules: false`), and the submodule's suite imports no framework code at
all — so without these, a change to the spec models could silently invalidate
every spec in the case study and nothing would notice.

The interface is the JSON specs, not the native binary: no CMake, no Metal, so
these run anywhere in about a second.

Skipped when the submodule isn't checked out, EXCEPT when
`REQUIRE_SUBMODULE_INTERFACE=1` — the CI job that exists to run these sets it,
so a broken checkout fails loudly instead of quietly passing as "all skipped".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bayesian_metamodeling.spec import MetaModelSpec, ModelSpec, SurrogateSpec

pytestmark = pytest.mark.integration

_SPECS_DIR = Path(__file__).resolve().parents[1] / "projects" / "tcr_signaling" / "specs"

# Spec filenames are prefixed by kind; that prefix selects the schema. Note this
# is why `bayesmm validate` alone is not a substitute — that subcommand only
# ever applies ModelSpec, so pointing it at a surrogate spec reports a bogus
# "Extra inputs are not permitted" rather than a real incompatibility.
_PREFIX_TO_MODEL = {
    "model.": ModelSpec,
    "surrogate.": SurrogateSpec,
    "metamodel.": MetaModelSpec,
}


def _submodule_present() -> bool:
    return _SPECS_DIR.is_dir() and any(_SPECS_DIR.glob("*.json"))


def _require_or_skip() -> None:
    if _submodule_present():
        return
    msg = (
        f"tcr_signaling submodule not checked out at {_SPECS_DIR}. "
        "Run: git submodule update --init projects/tcr_signaling"
    )
    if os.environ.get("REQUIRE_SUBMODULE_INTERFACE") == "1":
        pytest.fail(msg)
    pytest.skip(msg)


def _spec_files() -> list[Path]:
    return sorted(_SPECS_DIR.glob("*.json")) if _SPECS_DIR.is_dir() else []


def _model_for(path: Path):
    for prefix, model in _PREFIX_TO_MODEL.items():
        if path.name.startswith(prefix):
            return model
    return None


def test_submodule_is_checked_out():
    """Fails (not skips) under REQUIRE_SUBMODULE_INTERFACE=1 — see module docstring."""
    _require_or_skip()
    assert _spec_files(), "submodule present but ships no specs"


def test_every_spec_has_a_recognised_kind():
    """A spec whose prefix matches no schema would silently escape validation below."""
    _require_or_skip()
    unknown = [p.name for p in _spec_files() if _model_for(p) is None]
    assert not unknown, (
        f"specs with no recognised kind prefix {sorted(_PREFIX_TO_MODEL)}: {unknown}. "
        "Either rename them or teach _PREFIX_TO_MODEL about the new kind."
    )


@pytest.mark.parametrize("spec_path", _spec_files(), ids=lambda p: p.name)
def test_spec_validates_against_framework_schema(spec_path: Path):
    """Every case-study spec still satisfies the framework's current models."""
    _require_or_skip()
    model = _model_for(spec_path)
    if model is None:
        pytest.skip("covered by test_every_spec_has_a_recognised_kind")
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    model.model_validate(payload)


@pytest.mark.parametrize("spec_path", _spec_files(), ids=lambda p: p.name)
def test_spec_declares_a_schema_version(spec_path: Path):
    """Specs must carry schema_version so future migrations can be targeted."""
    _require_or_skip()
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    assert payload.get("schema_version"), f"{spec_path.name} has no schema_version"


def test_metamodel_references_only_existing_surrogates():
    """The metamodel couples surrogates by name; a rename on either side breaks it."""
    _require_or_skip()
    metamodels = [p for p in _spec_files() if p.name.startswith("metamodel.")]
    if not metamodels:
        pytest.skip("no metamodel spec in the submodule")

    surrogate_names = {
        json.loads(p.read_text(encoding="utf-8")).get("name")
        for p in _spec_files()
        if p.name.startswith("surrogate.")
    }
    for mm_path in metamodels:
        spec = MetaModelSpec.model_validate(json.loads(mm_path.read_text(encoding="utf-8")))
        referenced = {
            getattr(s, "name", None) or getattr(s, "surrogate", None)
            for s in getattr(spec, "surrogates", []) or []
        }
        missing = {r for r in referenced if r and r not in surrogate_names}
        assert not missing, (
            f"{mm_path.name} references surrogates that no spec defines: {sorted(missing)}. "
            f"Defined: {sorted(n for n in surrogate_names if n)}"
        )
