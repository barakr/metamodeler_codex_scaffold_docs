from __future__ import annotations

import os

import pytest

from metamodeler.surrogates.backends import get_backend_dependency_versions


def _has_pymc() -> bool:
    versions = get_backend_dependency_versions("pymc_gp")
    return versions.get("pymc") != "not_installed"


def _has_sbi() -> bool:
    versions = get_backend_dependency_versions("sbi_npe")
    return versions.get("sbi") != "not_installed" and versions.get("torch") != "not_installed"


def skip_optional_backend_tests() -> bool:
    value = os.getenv("MM_SKIP_OPTIONAL_BACKEND_TESTS", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def optional_backend_status() -> dict[str, bool]:
    return {
        "pymc": _has_pymc(),
        "sbi": _has_sbi(),
        "skip_optional_backend_tests": skip_optional_backend_tests(),
    }


def available_fit_backend() -> tuple[str, dict]:
    if skip_optional_backend_tests():
        pytest.skip("MM_SKIP_OPTIONAL_BACKEND_TESTS is set; optional backend tests disabled.")
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
    if skip_optional_backend_tests():
        return False
    return _has_sbi() or _has_pymc()
