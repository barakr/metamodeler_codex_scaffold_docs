"""Lazy import helpers for optional backend dependencies.

Single source of truth for `pymc`, `torch`, `sbi`, `arviz` import gating.
Used by both surrogate backends (raise actionable errors at fit time) and the
configurer's `diagnose()` (probe availability without raising).
"""

from __future__ import annotations

import importlib
import importlib.metadata
import warnings
from dataclasses import dataclass
from typing import Any

_INSTALL_HINTS: dict[str, str] = {
    "pymc": (
        "Install PyMC: `conda install -n <env> -c conda-forge pymc arviz` "
        "or `pip install 'metamodeler[pymc]'`."
    ),
    "arviz": (
        "Install ArviZ: `conda install -n <env> -c conda-forge arviz` "
        "or `pip install 'metamodeler[pymc]'`."
    ),
    "torch": (
        "Install PyTorch: `conda install -n <env> -c conda-forge pytorch` "
        "or `pip install 'metamodeler[sbi]'`."
    ),
    "sbi": (
        "Install SBI: `conda install -n <env> -c conda-forge sbi` "
        "or `pip install 'metamodeler[sbi]'`."
    ),
}


def install_hint(package: str) -> str:
    return _INSTALL_HINTS.get(package, f"Install '{package}'.")


def _import_pymc():
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="ArviZ is undergoing a major refactor*",
            category=FutureWarning,
        )
        return importlib.import_module("pymc")


def require_pymc():
    try:
        return _import_pymc()
    except ModuleNotFoundError as exc:
        raise RuntimeError(f"Backend 'pymc_gp' requires 'pymc'. {install_hint('pymc')}") from exc


def require_torch():
    try:
        return importlib.import_module("torch")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"Backend 'sbi_npe' requires 'torch' and 'sbi'. {install_hint('torch')}"
        ) from exc


def require_sbi():
    try:
        return importlib.import_module("sbi")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"Backend 'sbi_npe' requires 'sbi' and 'torch'. {install_hint('sbi')}"
        ) from exc


@dataclass
class ProbeResult:
    package: str
    installed: bool
    version: str | None
    import_error: str | None


def probe_package(package: str) -> ProbeResult:
    """Try to import `package` without raising; return availability + version.

    Used by `diagnose()` to report what is installed.
    """
    try:
        if package == "pymc":
            module: Any = _import_pymc()
        else:
            module = importlib.import_module(package)
    except Exception as exc:  # noqa: BLE001 — diagnostic must not propagate
        return ProbeResult(
            package=package,
            installed=False,
            version=None,
            import_error=f"{type(exc).__name__}: {exc}",
        )

    version = getattr(module, "__version__", None)
    if version is None:
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = None
    return ProbeResult(package=package, installed=True, version=version, import_error=None)
