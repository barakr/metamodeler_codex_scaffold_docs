"""Every metamodel-sample registry entry must carry the same keys, whatever produced it.

Two code paths write into `tmp/metamodel_samples_registry.json` — `_sample_core` for
`--method propagate`, and `sample_joint_to_store` for `joint`/`nuts`. Readers iterate the
whole file: `bayesmm meta list` does, and so does
`test_metamodel_sampling_numpyro::test_meta_sample_numpyro_backend`, via

    any(entry["backend"] == "numpyro" for entry in registry.values())

`sample_joint_to_store` omitted `backend`, so that comprehension raised `KeyError` the
moment a joint sample existed alongside a propagated one.

What makes this worth a dedicated test is *why it survived*: the failure needs a joint
sample, a joint sample needs a fitted surrogate, and a fitted surrogate needs an optional
backend — which the default development environment did not have. Locally the offending
tests skipped; in CI, which installs both backends, they would have failed. The environment
gap hid it. `environment.yml` now carries both backends for exactly this reason.

So this test asserts the *schema agreement* rather than any one key: it writes one entry by
each path and requires them to share a common set. A future third sampler that forgets a
field fails here, not three layers downstream in whatever happens to read the registry next.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bayesian_metamodeling.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    VariableIR,
)

# Keys every reader is entitled to find on every entry, regardless of sampler.
REQUIRED = {"backend", "method", "draws", "chains", "seed", "samples_dataset_path"}


def _ir() -> MetamodelIR:
    return MetamodelIR(
        name="registry_schema_pair",
        variables=[VariableIR(name="x"), VariableIR(name="y")],
        factors=[
            PriorFactorIR(variable="x", distribution={"kind": "normal", "loc": 1.0, "scale": 0.5}),
            PriorFactorIR(variable="y", distribution={"kind": "normal", "loc": 0.0, "scale": 2.0}),
            CouplingFactorIR(
                coupling_type="gaussian_link",
                source="x",
                target="y",
                transform={"kind": "affine", "alpha": 1.5, "beta": -0.4},
                sigma=0.3,
            ),
        ],
    )


@pytest.mark.contract
def test_propagate_and_joint_write_the_same_registry_schema(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from bayesian_metamodeling.meta.joint_sampling import sample_joint_to_store
    from bayesian_metamodeling.meta.sampling import META_SAMPLE_REGISTRY_PATH, _sample_core

    ir = _ir()
    _sample_core(
        backend="pymc",
        ir=ir,
        spec_payload={"name": ir.name},
        dataset_digest="[]",
        draws=20,
        tune=5,
        chains=1,
        seed=0,
    )
    sample_joint_to_store(spec=None, ir=ir, draws=40, tune=20, chains=1, seed=0, surrogates={})

    registry = json.loads(Path(META_SAMPLE_REGISTRY_PATH).read_text(encoding="utf-8"))
    assert len(registry) == 2, f"expected one entry per sampler, got {sorted(registry)}"

    for sample_id, entry in registry.items():
        missing = REQUIRED - set(entry)
        assert not missing, (
            f"registry entry {sample_id} (method={entry.get('method')!r}) is missing "
            f"{sorted(missing)}. Every reader iterates this file — `bayesmm meta list` and "
            "the numpyro test both index `entry['backend']` — so a partial entry is a "
            "KeyError for someone, not a cosmetic gap."
        )

    # And the two paths must be distinguishable, or the schema agreement is useless.
    methods = {e["method"] for e in registry.values()}
    assert methods == {"prior_propagation", "random_walk_metropolis"}, methods


@pytest.mark.contract
def test_meta_list_survives_a_registry_holding_both_kinds(tmp_path, monkeypatch, capsys):
    """The reader that actually shipped: `bayesmm meta list` iterating a mixed registry."""
    monkeypatch.chdir(tmp_path)
    from bayesian_metamodeling.meta.joint_sampling import sample_joint_to_store
    from bayesian_metamodeling.meta.sampling import _sample_core, list_meta_samples

    ir = _ir()
    _sample_core(
        backend="pymc",
        ir=ir,
        spec_payload={"name": ir.name},
        dataset_digest="[]",
        draws=20,
        tune=5,
        chains=1,
        seed=0,
    )
    sample_joint_to_store(spec=None, ir=ir, draws=40, tune=20, chains=1, seed=0, surrogates={})

    listed = list_meta_samples()
    assert len(listed) == 2, listed
    assert all(row.get("backend") for row in listed), (
        f"`meta list` produced an entry with no backend: {listed}"
    )
