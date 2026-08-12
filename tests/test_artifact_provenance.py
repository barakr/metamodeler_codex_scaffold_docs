"""Recorded provenance is now compared, not just written (S4b), and typed on read (D7).

Artifacts have always carried `spec_digest` and `dataset_digest`. Nothing ever read them
back, which makes them book-keeping rather than provenance — `CLAUDE.md` rule 3 asks for the
latter.

The design decision worth pinning here is that drift **warns** rather than raises. Editing a
spec and re-evaluating before re-fitting is an ordinary mid-workflow state; refusing to load
would make edit-and-retry unusable. But it must not be silent, or a number gets attributed to
a model that never produced it.
"""

from __future__ import annotations

import json
import warnings

import pytest

from bayesian_metamodeling.storage.artifact import (
    ArtifactMismatchWarning,
    SurrogateArtifact,
    parse_artifact,
)


def _artifact(**overrides) -> SurrogateArtifact:
    payload = {
        "artifact_id": "abc123",
        "spec_name": "demo",
        "backend": "pymc_gp",
        "backend_payload": "tmp/x/backend_payload.json",
        "variable_lists": {"inputs": ["a"], "outputs": ["y"]},
        "spec_digest": "a" * 64,
        "dataset_digest": "b" * 64,
    }
    payload.update(overrides)
    return SurrogateArtifact.model_validate(payload)


class TestProvenanceDrift:
    def test_warns_when_the_spec_changed_since_the_fit(self):
        artifact = _artifact()
        with pytest.warns(ArtifactMismatchWarning, match="spec has changed"):
            drifted = artifact.warn_on_provenance_drift(
                expected_spec_digest="c" * 64, expected_dataset_digest=None
            )
        assert len(drifted) == 1
        assert "bayesmm surrogate fit" in drifted[0], "the warning must say how to fix it"

    def test_silent_when_digests_agree(self):
        artifact = _artifact()
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # any warning would fail the test
            assert (
                artifact.warn_on_provenance_drift(
                    expected_spec_digest="a" * 64, expected_dataset_digest="b" * 64
                )
                == []
            )

    def test_absent_digest_is_not_treated_as_drift(self):
        """Older artifacts predate the field. Absence is not evidence of a mismatch."""
        artifact = _artifact(spec_digest=None)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert (
                artifact.warn_on_provenance_drift(
                    expected_spec_digest="z" * 64, expected_dataset_digest=None
                )
                == []
            )

    def test_drift_warns_rather_than_raising(self):
        """Deliberate: edit-and-retry must stay usable."""
        artifact = _artifact()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            artifact.warn_on_provenance_drift(
                expected_spec_digest="c" * 64, expected_dataset_digest="d" * 64
            )  # must not raise


class TestTypedArtifactRead:
    def test_names_the_file_when_the_artifact_is_malformed(self):
        with pytest.raises(ValueError, match=r"Malformed surrogate artifact at /some/path"):
            parse_artifact({"spec_name": "demo"}, source="/some/path")

    def test_unknown_keys_are_preserved_not_rejected(self):
        """Unlike specs, artifacts are data at rest written by older versions.

        Forbidding unknown keys would make every field ever added a breaking change for
        existing stores, which is the opposite of what a provenance record is for.
        """
        artifact = parse_artifact(
            json.loads(
                json.dumps(
                    {
                        "artifact_id": "a",
                        "spec_name": "demo",
                        "backend": "pymc_gp",
                        "backend_payload": "p.json",
                        "a_field_from_the_future": 42,
                    }
                )
            ),
            source="x",
        )
        assert artifact.a_field_from_the_future == 42

    def test_missing_required_field_still_fails_loudly(self):
        with pytest.raises(ValueError, match="backend_payload"):
            parse_artifact({"artifact_id": "a", "spec_name": "d", "backend": "pymc_gp"}, source="x")
