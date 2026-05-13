"""Surrogate fit/eval service functions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from metamodeler.spec import SurrogateSpec
from metamodeler.storage.surrogate_store import (
    find_latest_artifact_for_spec,
    persist_surrogate_artifact,
)
from metamodeler.surrogates.backends import (
    fit_backend_model,
    get_backend_dependency_versions,
    load_backend_model,
    save_backend_payload,
)
from metamodeler.surrogates.dataset import load_tabular_dataset


def _validate_eval_inputs(
    spec: SurrogateSpec, inputs_payload: dict[str, Any]
) -> dict[str, np.ndarray]:
    if not isinstance(inputs_payload, dict):
        raise ValueError("--inputs must be a JSON object mapping input names to numeric arrays.")

    missing = [name for name in spec.inputs if name not in inputs_payload]
    extras = sorted(set(inputs_payload.keys()) - set(spec.inputs))
    if missing or extras:
        raise ValueError(
            "Input keys mismatch for surrogate eval. "
            f"Missing={missing or '[]'} Extra={extras or '[]'} Expected={spec.inputs}."
        )

    parsed: dict[str, np.ndarray] = {}
    lengths: set[int] = set()
    for name in spec.inputs:
        values = inputs_payload[name]
        if not isinstance(values, list):
            raise ValueError(f"Input '{name}' must be a JSON array of numbers.")
        if len(values) == 0:
            raise ValueError(f"Input '{name}' cannot be an empty array.")
        arr = np.asarray(values, dtype=float).reshape(-1)
        parsed[name] = arr
        lengths.add(int(arr.shape[0]))

    if len(lengths) != 1:
        raise ValueError("All input arrays must have the same length for surrogate eval.")

    return parsed


def _load_and_validate_artifact(spec: SurrogateSpec) -> dict[str, Any]:
    _, artifact_path = find_latest_artifact_for_spec(spec.name)
    artifact = json.loads(artifact_path.read_text())

    artifact_backend = artifact.get("backend")
    if artifact_backend != spec.backend:
        raise ValueError(
            f"Surrogate backend mismatch for spec '{spec.name}': "
            f"artifact backend is '{artifact_backend}', requested backend is '{spec.backend}'."
        )

    variable_lists = artifact.get("variable_lists", {})
    artifact_inputs = list(variable_lists.get("inputs", []))
    artifact_outputs = list(variable_lists.get("outputs", []))

    if artifact_inputs != spec.inputs:
        raise ValueError(
            "Surrogate artifact input signature mismatch: "
            f"artifact has {artifact_inputs}, spec expects {spec.inputs}."
        )
    if artifact_outputs != spec.outputs:
        raise ValueError(
            "Surrogate artifact output signature mismatch: "
            f"artifact has {artifact_outputs}, spec expects {spec.outputs}."
        )

    payload_path = Path(str(artifact.get("backend_payload", "")))
    if not payload_path.exists():
        raise ValueError(f"Surrogate backend payload is missing: {payload_path}")

    return artifact


def fit_surrogate(spec: SurrogateSpec) -> dict[str, str]:
    x, y, dataset_digest = load_tabular_dataset(spec)

    model = fit_backend_model(
        backend=spec.backend,
        x=x,
        y=y,
        input_names=spec.inputs,
        output_names=spec.outputs,
        backend_config=spec.backend_config,
        seed=spec.seed,
    )

    tmp_payload = Path("tmp") / "_surrogate_backend_payload.json"
    tmp_payload.parent.mkdir(parents=True, exist_ok=True)
    save_backend_payload(model, tmp_payload)
    dependency_versions = get_backend_dependency_versions(spec.backend)

    return persist_surrogate_artifact(
        spec=spec,
        dataset_digest=dataset_digest,
        payload_path=tmp_payload,
        dependency_versions=dependency_versions,
    )


def eval_surrogate(spec: SurrogateSpec, inputs_payload: dict[str, list[float]], n: int) -> dict:
    if n <= 0:
        raise ValueError("--n must be a positive integer.")

    artifact = _load_and_validate_artifact(spec)
    model = load_backend_model(
        spec.backend,
        Path(artifact["backend_payload"]),
        expected_inputs=spec.inputs,
        expected_outputs=spec.outputs,
    )
    inputs = _validate_eval_inputs(spec, inputs_payload)
    samples = model.sample(inputs=inputs, n=n, seed=spec.seed)
    summary = model.summary(inputs=inputs)

    # samples is always (N, n, D); preview the leading slice along all 3 axes.
    preview_n = min(3, samples.shape[0])
    preview_k = min(5, samples.shape[1])
    preview_d = min(3, samples.shape[2]) if samples.ndim == 3 else 1
    if samples.ndim == 3:
        samples_preview = samples[:preview_n, :preview_k, :preview_d].tolist()
    else:
        samples_preview = samples[:preview_n, :preview_k].tolist()

    return {
        "artifact_id": artifact["artifact_id"],
        "backend": spec.backend,
        "n": n,
        "sample_shape": list(samples.shape),
        "summary": summary,
        "samples_preview": samples_preview,
    }
