"""Typed read model for a persisted surrogate artifact (D7, S4b).

Specs are Pydantic-validated with `extra="forbid"`; artifacts were read back as raw dicts
with `.get()`. That asymmetry meant a truncated or hand-edited artifact failed deep inside
numpy rather than at the boundary with a message naming the file. This module makes the read
path as typed as the write path.

It also closes S4: artifacts have always *recorded* `spec_digest` and `dataset_digest`, and
nothing ever compared them to anything. Recording provenance without checking it is
book-keeping, not provenance (rule 3).
"""

from __future__ import annotations

import warnings
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArtifactMismatchWarning(UserWarning):
    """A stored artifact no longer matches the spec or dataset it was fitted from.

    A **warning**, not an error, on purpose. Re-fitting is often exactly what the user is
    in the middle of doing, and refusing to load would make an ordinary edit-and-retry loop
    unusable. But it must be *said*: silently evaluating a surrogate fitted from a spec you
    have since changed is how a result gets attributed to the wrong model.
    """


class SurrogateArtifact(BaseModel):
    """What `persist_surrogate_artifact` writes, read back with the schema enforced.

    `extra="allow"` rather than `forbid`, deliberately and unlike the spec models: artifacts
    are *data at rest* written by earlier versions of this package. Forbidding unknown keys
    would make every field ever added a breaking change for existing stores, which is the
    opposite of what a provenance record is for. Unknown keys are preserved and ignored;
    missing *required* keys still fail loudly.
    """

    model_config = ConfigDict(extra="allow")

    artifact_id: str
    spec_name: str
    backend: str
    backend_payload: str
    variable_lists: dict[str, list[str]] = Field(default_factory=dict)
    spec_digest: str | None = None
    dataset_digest: str | None = None
    created_at: str | None = None
    dependency_versions: dict[str, str] = Field(default_factory=dict)

    @property
    def inputs(self) -> list[str]:
        return list(self.variable_lists.get("inputs", []))

    @property
    def outputs(self) -> list[str]:
        return list(self.variable_lists.get("outputs", []))

    def warn_on_provenance_drift(
        self, *, expected_spec_digest: str | None, expected_dataset_digest: str | None
    ) -> list[str]:
        """Compare recorded digests against the current spec/dataset; warn on any drift.

        Returns the list of emitted messages so callers (and tests) can assert on them
        rather than scraping the warning stream.
        """
        drifted: list[str] = []
        for label, recorded, expected in (
            ("spec", self.spec_digest, expected_spec_digest),
            ("dataset", self.dataset_digest, expected_dataset_digest),
        ):
            # A `None` on either side means "not recorded" — older artifacts predate the
            # field. Absence is not evidence of drift, so say nothing.
            if recorded is None or expected is None:
                continue
            if recorded != expected:
                message = (
                    f"Surrogate '{self.spec_name}': the {label} has changed since this "
                    f"artifact was fitted (recorded {recorded[:12]}…, current "
                    f"{expected[:12]}…). The surrogate still loads, but it was fitted from "
                    f"a different {label}. Re-run `bayesmm surrogate fit` to bring them "
                    f"back into agreement."
                )
                warnings.warn(message, ArtifactMismatchWarning, stacklevel=3)
                drifted.append(message)
        return drifted


def parse_artifact(payload: dict[str, Any], *, source: str) -> SurrogateArtifact:
    """Validate a raw artifact dict, naming the file when it does not fit the schema."""
    try:
        return SurrogateArtifact.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - re-raised with the path attached
        raise ValueError(f"Malformed surrogate artifact at {source}: {exc}") from exc
