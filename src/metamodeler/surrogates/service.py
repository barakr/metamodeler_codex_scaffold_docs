"""Surrogate fit/eval service functions."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from metamodeler.spec import SurrogateSpec
from metamodeler.storage.surrogate_store import (
    find_latest_artifact_for_spec,
    persist_surrogate_artifact,
)
from metamodeler.surrogates.backends import (
    fit_backend_model,
    load_backend_model,
    save_backend_payload,
)
from metamodeler.surrogates.dataset import load_tabular_dataset


def fit_surrogate(spec: SurrogateSpec) -> dict[str, str]:
    x, y, dataset_digest = load_tabular_dataset(spec)

    model = fit_backend_model(
        backend=spec.backend,
        x=x,
        y=y,
        input_names=spec.inputs,
        output_name=spec.outputs[0],
    )

    tmp_payload = Path("tmp") / "_surrogate_backend_payload.json"
    tmp_payload.parent.mkdir(parents=True, exist_ok=True)
    save_backend_payload(model, tmp_payload)

    return persist_surrogate_artifact(
        spec=spec, dataset_digest=dataset_digest, payload_path=tmp_payload
    )


def eval_surrogate(spec: SurrogateSpec, inputs_payload: dict[str, list[float]], n: int) -> dict:
    _, artifact_path = find_latest_artifact_for_spec(spec.name)
    artifact = json.loads(artifact_path.read_text())

    model = load_backend_model(spec.backend, Path(artifact["backend_payload"]))
    inputs = {key: np.asarray(values, dtype=float) for key, values in inputs_payload.items()}
    samples = model.sample(inputs=inputs, n=n, seed=spec.seed)
    summary = model.summary(inputs=inputs)

    return {
        "artifact_id": artifact["artifact_id"],
        "backend": spec.backend,
        "n": n,
        "sample_shape": list(samples.shape),
        "summary": summary,
        "samples_preview": samples[: min(3, len(samples)), : min(5, n)].tolist(),
    }
