"""Sample the coupled joint distribution defined by a metamodel IR.

This is the step that was missing. `CompiledMetaModel.evaluate_log_prob` already
computes the full joint log-density — priors, couplings and surrogate likelihoods —
but nothing sampled from it: `sample_metamodel` draws each variable from its prior
independently and then overwrites coupled targets with `transform(source)`. That is
forward propagation, and it answers a different question. Declaring a Gaussian
coupling between two models' variables had no accompanying way to *sample the
coupled joint*.

What this module adds:

- `load_surrogates_for_ir` — turns the IR's surrogate references into callable
  models, so the likelihood factors stop being silently neutral.
- `sample_joint` — random-walk Metropolis over the joint log-density, with
  deterministic couplings handled as derived quantities rather than sampled ones.

Why Metropolis rather than NUTS: the joint density is an ordinary Python callable
over a dict of floats, and a fitted surrogate's `log_prob` is a black box with no
gradient. A gradient-free sampler is what that admits. The cost is efficiency, not
correctness — the chain targets the true joint, which the prior-propagation path
never did. Expressing the whole model as a PyTensor graph would unlock NUTS and is
the natural next step; it needs every surrogate backend to provide a symbolic
log_prob, which they do not today.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from bayesian_metamodeling.meta.compiler import CompiledMetaModel
from bayesian_metamodeling.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    SurrogateLikelihoodFactorIR,
)
from bayesian_metamodeling.storage.surrogate_store import SURROGATE_REGISTRY_PATH
from bayesian_metamodeling.surrogates.base import SurrogateModel

__all__ = [
    "derived_variables",
    "load_surrogates_for_ir",
    "sample_joint",
    "sample_joint_to_store",
]


def _resolve(path_str: str, *, near: Path | None = None) -> Path:
    """Resolve an artifact-relative path, falling back to the artifact's own tree.

    Artifacts record `backend_payload` as a path relative to the directory the fit
    ran in. That resolves correctly when sampling happens from the same place and
    not otherwise, so try the artifact's neighbourhood before giving up.
    """
    p = Path(path_str)
    if p.exists():
        return p
    if near is not None:
        for base in (near.parent, near.parent.parent, near.parent.parent.parent):
            candidate = base / p
            if candidate.exists():
                return candidate
    return p


def load_surrogates_for_ir(
    ir: MetamodelIR, spec_refs: list[str] | None = None
) -> dict[str, SurrogateModel]:
    """Rehydrate every surrogate the IR references, keyed by its `surrogate_ref`.

    `spec_refs` is the spec's own `surrogate_refs` list, and passing it matters:
    `build_ir_from_metamodel_spec` stores the resolved **artifact_id** in the IR and
    discards the path it came from, so an IR alone cannot always find its artifacts.
    Reading the spec's refs recovers the id -> path mapping. Three resolution routes
    are tried in order — a literal path, the spec's refs, then the surrogate registry.

    Raises rather than returning a partial map: a missing surrogate silently
    reduces the joint density to priors-plus-couplings, which is precisely the
    failure this module exists to end.
    """
    from bayesian_metamodeling.surrogates.backends import load_backend_model

    by_id: dict[str, Path] = {}
    for candidate in spec_refs or []:
        candidate_path = Path(candidate)
        if not candidate_path.exists():
            continue
        try:
            payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        artifact_id = payload.get("artifact_id")
        if artifact_id:
            by_id[str(artifact_id)] = candidate_path

    out: dict[str, SurrogateModel] = {}
    for factor in ir.factors:
        if not isinstance(factor, SurrogateLikelihoodFactorIR):
            continue
        ref = factor.surrogate_ref
        if ref in out:
            continue
        # `build_ir_from_metamodel_spec` stores the resolved ARTIFACT ID in the IR,
        # not the path from the spec — so accept either, exactly as the builder's own
        # `_resolve_surrogate_ref` does: a path if it exists, otherwise a registry
        # lookup by id.
        artifact_path = Path(ref)
        if not artifact_path.exists() and ref in by_id:
            artifact_path = by_id[ref]
        if not artifact_path.exists():
            registry: dict[str, str] = {}
            if SURROGATE_REGISTRY_PATH.exists():
                registry = json.loads(SURROGATE_REGISTRY_PATH.read_text(encoding="utf-8"))
            if ref not in registry:
                raise FileNotFoundError(
                    f"surrogate {ref!r} could not be resolved: not a readable path, not "
                    f"among the spec's surrogate_refs, and not a key in "
                    f"{SURROGATE_REGISTRY_PATH}. The joint density cannot be evaluated "
                    "without it; fit and publish the surrogate, and run from the "
                    "directory the fit used (these paths are relative)."
                )
            artifact_path = Path(registry[ref])
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        if "backend_payload" not in artifact:
            # Stub artifacts (e.g. examples/coupled/artifacts/*) declare a signature so
            # `meta build` can assemble an IR, but carry no fitted model. Propagation
            # never notices; joint sampling cannot proceed, and saying so beats a
            # KeyError three frames down.
            raise ValueError(
                f"surrogate artifact {artifact_path} has no 'backend_payload': it is a "
                "placeholder declaring inputs/outputs, not a fitted model. Joint sampling "
                "conditions on the surrogate likelihoods, so it needs a real fit — run "
                "`bayesmm surrogate fit` for this model, or use --method propagate, which "
                "does not evaluate surrogates."
            )
        payload_path = _resolve(str(artifact["backend_payload"]), near=artifact_path)
        if not payload_path.exists():
            raise FileNotFoundError(
                f"backend payload for {ref!r} not found at {payload_path}. The artifact "
                "records a path relative to where the fit ran; re-fit, or run from there."
            )
        out[ref] = load_backend_model(
            str(artifact["backend"]),
            payload_path,
            expected_inputs=list(factor.inputs),
            expected_outputs=list(factor.outputs),
        )
    return out


def derived_variables(ir: MetamodelIR) -> dict[str, CouplingFactorIR]:
    """Targets of deterministic couplings, which are computed rather than sampled.

    A deterministic coupling asserts `target == transform(source)` exactly. Proposing
    such a target freely would be rejected essentially always — the compiler applies a
    large penalty off the constraint surface — so the chain would stall. Computing it
    from its source instead is both correct and what "deterministic" means.
    """
    out: dict[str, CouplingFactorIR] = {}
    for factor in ir.factors:
        if (
            isinstance(factor, CouplingFactorIR)
            and factor.coupling_type == "deterministic_transform"
        ):
            out[factor.target] = factor
    return out


def _apply_transform(factor: CouplingFactorIR, source_value: float) -> float:
    if factor.transform.get("kind") == "affine":
        alpha = float(factor.transform.get("alpha", 1.0))
        beta = float(factor.transform.get("beta", 0.0))
        return alpha * source_value + beta
    return source_value


def _prior_moments(ir: MetamodelIR) -> dict[str, tuple[float, float]]:
    moments: dict[str, tuple[float, float]] = {var.name: (0.0, 1.0) for var in ir.variables}
    for factor in ir.factors:
        if (
            isinstance(factor, PriorFactorIR)
            and factor.distribution.get("kind", "normal") == "normal"
        ):
            moments[factor.variable] = (
                float(factor.distribution.get("loc", 0.0)),
                float(factor.distribution.get("scale", 1.0)),
            )
    return moments


def sample_joint(
    compiled: CompiledMetaModel,
    *,
    draws: int,
    tune: int,
    chains: int,
    seed: int,
    surrogates: dict[str, SurrogateModel] | None = None,
    target_accept: float = 0.3,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Random-walk Metropolis over the joint log-density.

    Returns `(samples, diagnostics)`. `samples[name]` has shape `(chains, draws)`.

    Proposal scales adapt during `tune` toward `target_accept` and are then frozen,
    so the retained draws come from a time-homogeneous chain — adapting throughout
    would leave the kernel non-Markovian and the draws subtly wrong.
    """
    ir = compiled.ir
    surrogates = surrogates or {}
    derived = derived_variables(ir)
    names = sorted(var.name for var in ir.variables)
    observed = {k: float(v) for k, v in (ir.observed or {}).items()}
    # Observed variables are clamped, not sampled: they leave the sample space entirely.
    # Their prior term, if they have one, is then a constant and cannot affect any
    # acceptance ratio — which is the honest meaning of "I measured this".
    free = [n for n in names if n not in derived and n not in observed]
    moments = _prior_moments(ir)

    def complete(values: dict[str, float]) -> dict[str, float]:
        """Fill deterministic targets from their sources, and pin observed values."""
        full = dict(values)
        full.update(observed)
        # Repeat so a chain of deterministic links resolves in order.
        for _ in range(len(derived) or 1):
            for target, factor in derived.items():
                if factor.source in full:
                    full[target] = _apply_transform(factor, float(full[factor.source]))
        return full

    def logp(values: dict[str, float]) -> float:
        full = complete(values)
        missing = [n for n in names if n not in full]
        if missing:
            raise KeyError(f"variables missing from the draw: {missing}")
        try:
            value = compiled.evaluate_log_prob(full, surrogates=surrogates)
        except Exception:
            return -math.inf
        return value if math.isfinite(value) else -math.inf

    rng = np.random.default_rng(seed)
    out = {name: np.zeros((chains, draws), dtype=float) for name in names}
    accepted_total = 0
    proposed_total = 0
    final_scales: dict[str, float] = {}

    for chain in range(chains):
        # Start at the prior mean, jittered per chain so chains are not identical.
        state = {
            n: moments[n][0] + (0.0 if chain == 0 else rng.normal(0.0, 0.1 * moments[n][1]))
            for n in free
        }
        scales = {n: max(moments[n][1], 1e-6) * 0.5 for n in free}
        current = logp(state)
        if not math.isfinite(current):
            raise ValueError(
                "joint log-density is -inf at the prior mean; the model is misspecified "
                "(check coupling sigmas and that surrogate inputs lie in their trained range)"
            )

        accepted = dict.fromkeys(free, 0)
        attempted = dict.fromkeys(free, 0)
        for step in range(tune + draws):
            for name in free:
                proposal = dict(state)
                proposal[name] = state[name] + rng.normal(0.0, scales[name])
                candidate = logp(proposal)
                attempted[name] += 1
                if math.log(rng.uniform()) < candidate - current:
                    state, current = proposal, candidate
                    accepted[name] += 1

            if step < tune and (step + 1) % 25 == 0:
                # Adapt toward target_accept, then freeze for the retained draws.
                for name in free:
                    rate = accepted[name] / max(attempted[name], 1)
                    scales[name] *= math.exp(rate - target_accept)
                    scales[name] = float(np.clip(scales[name], 1e-9, 1e6))
                    accepted[name] = attempted[name] = 0
            elif step >= tune:
                full = complete(state)
                for name in names:
                    out[name][chain, step - tune] = full[name]

        accepted_total += sum(accepted.values())
        proposed_total += sum(attempted.values())
        final_scales = dict(scales)

    ess = {name: _effective_sample_size(out[name]) for name in names}
    stuck = sorted(n for n, value in ess.items() if n in free and value < _MIN_ESS)

    diagnostics = {
        "method": "random_walk_metropolis",
        "accept_rate": (accepted_total / proposed_total) if proposed_total else float("nan"),
        "free_variables": free,
        "derived_variables": sorted(derived),
        "surrogates_loaded": sorted(surrogates),
        "proposal_scales": final_scales,
        "ess": ess,
        # Variables the chain failed to explore. See `_MIN_ESS` for why this is
        # reported separately from `accept_rate`.
        "poorly_mixed": stuck,
        # What was conditioned on. A stored result that does not say this cannot be
        # interpreted: the same model with and without an observation are different
        # questions with different answers.
        "observed": dict(observed),
    }
    return out, diagnostics


# A coordinate-wise random walk cannot climb a ridge. When a surrogate likelihood is
# very sharp — a `pymc_gp` fit of an exactly-linear truth has predictive sd ~1e-5 —
# the posterior concentrates on a thin manifold, tuning shrinks every proposal scale
# to match, and the chain then explores a ~1e-5 sliver of a distribution whose real
# width is O(1). The damning part is that `accept_rate` looks perfectly healthy while
# this happens (0.29 in the case that motivated this), because the moves it accepts
# are all tiny. Reporting such a run as a result is exactly the silent-no-op failure
# CLAUDE.md rule 12 is about, so the diagnostics name it.
#
# 20 is deliberately low: this is a "this chain told you nothing" alarm, not a
# convergence standard. Anything near it is already unusable.
_MIN_ESS = 20.0


def _effective_sample_size(samples: np.ndarray) -> float:
    """n / (1 + 2 * sum of positive autocorrelations), summed over chains.

    Deliberately the crude initial-positive-sequence estimator rather than an ArviZ
    dependency: this runs on every joint sample, ArviZ is an optional extra, and the
    number is used as an alarm threshold rather than a reported statistic.
    """
    total = 0.0
    for chain in np.atleast_2d(np.asarray(samples, dtype=float)):
        n = chain.size
        if n < 4:
            total += float(n)
            continue
        centered = chain - chain.mean()
        variance = float(centered.var())
        if variance <= 0.0:  # a genuinely frozen coordinate
            continue
        max_lag = min(n - 2, 200)
        tau = 1.0
        for lag in range(1, max_lag + 1):
            rho = float(np.dot(centered[:-lag], centered[lag:]) / ((n - lag) * variance))
            if rho <= 0.05:
                break
            tau += 2.0 * rho
        total += n / tau
    return total


def sample_joint_to_store(
    *,
    spec: Any,
    ir: MetamodelIR,
    draws: int,
    tune: int,
    chains: int,
    seed: int,
    surrogates: dict[str, SurrogateModel] | None = None,
) -> dict[str, Any]:
    """Sample the joint and persist it in the same layout as `sample_metamodel`.

    Writing the identical files means `meta list`, the notebooks and anything else
    reading `samples_dataset.json` keep working regardless of which method produced
    the draws. The method and its accept rate go into `inference_data.json`, so a
    stored result says how it was made rather than leaving that to be inferred.
    """
    import json as _json
    from datetime import UTC, datetime
    from uuid import uuid4

    from bayesian_metamodeling.meta.compiler import compile_metamodel
    from bayesian_metamodeling.meta.sampling import META_SAMPLE_REGISTRY_PATH
    from bayesian_metamodeling.storage._filelock import locked_registry

    compiled = compile_metamodel(ir, backend=getattr(spec, "ppl_backend", "pymc"))
    samples, diagnostics = sample_joint(
        compiled, draws=draws, tune=tune, chains=chains, seed=seed, surrogates=surrogates
    )

    sample_id = uuid4().hex
    out_dir = Path("tmp/metamodel_samples") / sample_id
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset_path = out_dir / "samples_dataset.json"
    dataset_path.write_text(
        _json.dumps(
            {
                "dims": {"chain": chains, "draw": draws},
                "variables": {k: v.tolist() for k, v in samples.items()},
            },
            indent=2,
            sort_keys=True,
        )
    )

    inference_path = out_dir / "inference_data.json"
    inference_path.write_text(
        _json.dumps(
            {
                "backend": compiled.backend,
                "name": ir.name,
                "draws": draws,
                "tune": tune,
                "chains": chains,
                "seed": seed,
                "variables": sorted(samples),
                "created_at": datetime.now(UTC).isoformat(),
                **diagnostics,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )

    with locked_registry(META_SAMPLE_REGISTRY_PATH):
        registry = {}
        if META_SAMPLE_REGISTRY_PATH.exists():
            registry = _json.loads(META_SAMPLE_REGISTRY_PATH.read_text(encoding="utf-8"))
        registry[sample_id] = {
            "name": ir.name,
            "method": diagnostics["method"],
            "inference_data_path": str(inference_path),
            "samples_dataset_path": str(dataset_path),
            "created_at": datetime.now(UTC).isoformat(),
        }
        META_SAMPLE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        META_SAMPLE_REGISTRY_PATH.write_text(_json.dumps(registry, indent=2, sort_keys=True))

    return {
        "sample_id": sample_id,
        "inference_data_path": str(inference_path),
        "samples_dataset_path": str(dataset_path),
        "accept_rate": diagnostics["accept_rate"],
        # Surfaced so the CLI can warn; a stored dataset whose chain never moved is
        # worse than no dataset, because it looks like an answer.
        "poorly_mixed": diagnostics["poorly_mixed"],
        "ess": diagnostics["ess"],
    }
