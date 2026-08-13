"""Shape plumbing, output naming, and dependency-version lookup.

Split out of the former single-file `backends.py` (D2). Nothing here touches an optional
backend, so importing it never drags in pymc, sbi or torch.
"""

from __future__ import annotations

import importlib.metadata

import numpy as np


def _ensure_2d(y: np.ndarray) -> np.ndarray:
    """Promote a 1-D y vector to (N, 1) — single-output back-compat for callers."""
    if y.ndim == 1:
        return y.reshape(-1, 1)
    return y


def _named_or_squeezed(values_2d: np.ndarray, names: list[str]):
    """Format per-output columns for a summary dict.

    Single-output (D=1) collapses to a flat list — the historical contract that
    downstream consumers (`np.array(summary["mean"])`) depend on. Multi-output
    (D>=2) returns a dict keyed by output name. Mirrors the squeeze convention
    used by ``sample()``.
    """
    if len(names) == 1:
        return values_2d[:, 0].tolist()
    return {name: values_2d[:, i].tolist() for i, name in enumerate(names)}


def _resolve_output_names(output_names: list[str] | None, output_name: str | None) -> list[str]:
    """Accept either the multi-output ``output_names`` or legacy ``output_name``."""
    if output_names is not None:
        return output_names
    if output_name is not None:
        return [output_name]
    raise ValueError("Must pass either output_names=[...] or output_name=...")


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


def get_backend_dependency_versions(backend: str) -> dict[str, str]:
    versions = {
        "numpy": np.__version__,
        "scipy": _package_version("scipy"),
    }
    if backend == "pymc_gp":
        versions["pymc"] = _package_version("pymc")
        versions["arviz"] = _package_version("arviz")
    if backend == "sbi_npe":
        versions["sbi"] = _package_version("sbi")
        versions["torch"] = _package_version("torch")
    return versions
