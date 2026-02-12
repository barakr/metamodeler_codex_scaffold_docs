from __future__ import annotations

import pytest

from metamodeler.surrogates.backends import get_backend_dependency_versions


def _has_pymc() -> bool:
    versions = get_backend_dependency_versions("pymc_gp")
    return versions.get("pymc") != "not_installed"


def _has_sbi() -> bool:
    versions = get_backend_dependency_versions("sbi_npe")
    return versions.get("sbi") != "not_installed" and versions.get("torch") != "not_installed"


def available_fit_backend() -> tuple[str, dict]:
    if _has_sbi():
        return (
            "sbi_npe",
            {
                "density_estimator": "maf",
                "max_num_epochs": 80,
                "training_batch_size": 32,
                "learning_rate": 5e-4,
                "summary_samples": 128,
            },
        )
    if _has_pymc():
        return (
            "pymc_gp",
            {
                "draws": 80,
                "tune": 80,
                "chains": 1,
                "target_accept": 0.9,
            },
        )
    pytest.skip("No optional surrogate backend available (need either sbi/torch or pymc)")


def has_any_optional_backend() -> bool:
    return _has_sbi() or _has_pymc()
