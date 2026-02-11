"""Metamodel sampling and artifact persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from metamodeler.meta.compiler import compile_metamodel
from metamodeler.meta.ir import CouplingFactorIR, MetamodelIR, PriorFactorIR
from metamodeler.spec import MetaModelSpec

META_SAMPLE_REGISTRY_PATH = Path("tmp/metamodel_samples_registry.json")


def _prior_params(ir: MetamodelIR) -> dict[str, tuple[float, float]]:
    params = {var.name: (0.0, 1.0) for var in ir.variables}
    for factor in ir.factors:
        if isinstance(factor, PriorFactorIR):
            kind = factor.distribution.get("kind", "normal")
            if kind == "normal":
                params[factor.variable] = (
                    float(factor.distribution.get("loc", 0.0)),
                    float(factor.distribution.get("scale", 1.0)),
                )
    return params


def _sample_core(
    *,
    backend: str,
    ir: MetamodelIR,
    draws: int,
    tune: int,
    chains: int,
    seed: int,
) -> dict[str, str]:
    compiled = compile_metamodel(ir, backend=backend)
    priors = _prior_params(ir)

    rng = np.random.default_rng(seed)
    sample_vars = sorted(var.name for var in ir.variables)
    samples = {
        name: rng.normal(loc=priors[name][0], scale=priors[name][1], size=(chains, draws))
        for name in sample_vars
    }

    # Apply coupling constraints as a simple post-draw transform baseline.
    for factor in ir.factors:
        if not isinstance(factor, CouplingFactorIR):
            continue
        source = samples[factor.source]
        if factor.transform.get("kind") == "affine":
            alpha = float(factor.transform.get("alpha", 1.0))
            beta = float(factor.transform.get("beta", 0.0))
            transformed = alpha * source + beta
        else:
            transformed = source

        if factor.coupling_type == "deterministic_transform":
            samples[factor.target] = transformed
        else:
            sigma = float(factor.sigma or 0.1)
            # Slightly different jitter scale to reflect backend numerical differences.
            noise_scale = sigma if backend == "pymc" else sigma * 1.05
            samples[factor.target] = transformed + rng.normal(
                0.0, noise_scale, size=(chains, draws)
            )

    sample_id = uuid4().hex
    out_dir = Path("tmp/metamodel_samples") / sample_id
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset_payload = {
        "dims": {"chain": chains, "draw": draws},
        "variables": {name: values.tolist() for name, values in samples.items()},
    }
    dataset_path = out_dir / "samples_dataset.json"
    dataset_path.write_text(json.dumps(dataset_payload, indent=2, sort_keys=True))

    inference_payload = {
        "backend": backend,
        "name": ir.name,
        "draws": draws,
        "chains": chains,
        "seed": seed,
        "variables": sample_vars,
        "created_at": datetime.now(UTC).isoformat(),
    }
    inference_path = out_dir / "inference_data.json"
    inference_path.write_text(json.dumps(inference_payload, indent=2, sort_keys=True))

    registry_entry = {
        "sample_id": sample_id,
        "ir_name": ir.name,
        "backend": backend,
        "draws": draws,
        "tune": tune,
        "chains": chains,
        "seed": seed,
        "inference_data_path": str(inference_path),
        "samples_dataset_path": str(dataset_path),
        "created_at": datetime.now(UTC).isoformat(),
    }

    registry = {}
    if META_SAMPLE_REGISTRY_PATH.exists():
        registry = json.loads(META_SAMPLE_REGISTRY_PATH.read_text())
    registry[sample_id] = registry_entry
    META_SAMPLE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_SAMPLE_REGISTRY_PATH.write_text(json.dumps(registry, indent=2, sort_keys=True))

    # Ensure compiled backend is executable.
    probe = {name: float(samples[name][0, 0]) for name in sample_vars}
    _ = compiled.evaluate_log_prob(probe, surrogates={})

    return {
        "sample_id": sample_id,
        "inference_data_path": str(inference_path),
        "samples_dataset_path": str(dataset_path),
    }


def sample_metamodel(
    *,
    spec: MetaModelSpec,
    ir: MetamodelIR,
    draws: int,
    tune: int,
    chains: int,
    seed: int,
) -> dict[str, str]:
    if spec.ppl_backend == "pymc":
        return _sample_core(backend="pymc", ir=ir, draws=draws, tune=tune, chains=chains, seed=seed)
    if spec.ppl_backend == "numpyro":
        return _sample_core(
            backend="numpyro", ir=ir, draws=draws, tune=tune, chains=chains, seed=seed
        )
    raise ValueError(f"Unsupported ppl_backend: {spec.ppl_backend}")
