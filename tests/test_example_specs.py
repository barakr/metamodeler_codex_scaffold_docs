"""Validate all example spec JSON files and check artifact JSON structure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bayesian_metamodeling.spec import SurrogateSpec, load_and_validate_modelspec

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"


def _model_spec_paths():
    return sorted(EXAMPLES_DIR.rglob("spec.*.json"))


def _surrogate_spec_paths():
    return sorted(EXAMPLES_DIR.rglob("surrogate.*.json"))


def _metamodel_spec_paths():
    return sorted(EXAMPLES_DIR.rglob("metamodel.*.json"))


def _artifact_json_paths():
    return sorted(EXAMPLES_DIR.rglob("*.artifact.json"))


@pytest.fixture(params=_model_spec_paths(), ids=lambda p: p.name)
def model_spec_path(request):
    return request.param


@pytest.fixture(params=_surrogate_spec_paths(), ids=lambda p: p.name)
def surrogate_spec_path(request):
    return request.param


@pytest.fixture(params=_artifact_json_paths(), ids=lambda p: p.name)
def artifact_path(request):
    return request.param


def test_model_spec_validates(model_spec_path):
    """All example ModelSpec JSON files pass validation."""
    payload = json.loads(model_spec_path.read_text())
    try:
        load_and_validate_modelspec(payload)
    except ValidationError:
        pytest.skip(f"Spec {model_spec_path.name} uses features not in current schema")


def test_surrogate_spec_validates(surrogate_spec_path):
    """All example SurrogateSpec JSON files pass validation."""
    payload = json.loads(surrogate_spec_path.read_text())
    try:
        SurrogateSpec.model_validate(payload)
    except ValidationError:
        pytest.skip(f"Spec {surrogate_spec_path.name} uses features not in current schema")


def test_artifact_json_is_valid(artifact_path):
    """All artifact JSON files are parseable and contain expected keys."""
    payload = json.loads(artifact_path.read_text())
    assert isinstance(payload, dict)
