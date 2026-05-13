"""Lazy import probes used by the diagnostic.

`bayesian_metamodeling.surrogates.backends` keeps its own hardened
`_require_pymc` / `_require_torch` / `_require_sbi` (which set up isolated
HOME / MPLCONFIGDIR / XDG_CACHE_HOME and serialize via a threading lock).
This module only adds a non-raising probe used by `diagnose()`.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass
from typing import Any

_INSTALL_HINTS: dict[str, str] = {
    "pymc": (
        "Install PyMC: `conda install -n <env> -c conda-forge pymc arviz` "
        "or `pip install 'bayesian-metamodeling[pymc]'`."
    ),
    "arviz": (
        "Install ArviZ: `conda install -n <env> -c conda-forge arviz` "
        "or `pip install 'bayesian-metamodeling[pymc]'`."
    ),
    "torch": (
        "Install PyTorch: `conda install -n <env> -c conda-forge pytorch` "
        "or `pip install 'bayesian-metamodeling[sbi]'`."
    ),
    "sbi": (
        "Install SBI: `conda install -n <env> -c conda-forge sbi` "
        "or `pip install 'bayesian-metamodeling[sbi]'`."
    ),
}


def install_hint(package: str) -> str:
    return _INSTALL_HINTS.get(package, f"Install '{package}'.")


@dataclass
class ProbeResult:
    package: str
    installed: bool
    version: str | None
    import_error: str | None


def probe_package(package: str) -> ProbeResult:
    """Try to import `package` without raising; return availability + version.

    Used by `diagnose()` to report what is installed. Never raises on missing
    or broken packages — diagnostics must always succeed.
    """
    try:
        module: Any = importlib.import_module(package)
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
