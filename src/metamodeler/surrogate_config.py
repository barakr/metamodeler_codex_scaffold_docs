"""Validation rules for surrogate backend configuration."""

from __future__ import annotations

from typing import Any

_ALLOWED_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "pymc_gp": ("draws", "tune", "chains", "target_accept"),
    "sbi_npe": (
        "density_estimator",
        "max_num_epochs",
        "training_batch_size",
        "learning_rate",
        "validation_fraction",
        "stop_after_epochs",
        "show_train_summary",
        "summary_samples",
    ),
    "numpyro_gp": (),
}


def _must_be_positive_int(backend: str, key: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(
            "backend_config['{key}'] for backend '{backend}' must be a positive "
            "integer; got {value!r}.".format(key=key, backend=backend, value=value)
        )


def _must_be_probability(backend: str, key: str, value: Any) -> None:
    if not isinstance(value, (int, float)):
        raise ValueError(
            "backend_config['{key}'] for backend '{backend}' must be numeric in "
            "(0, 1); got {value!r}.".format(key=key, backend=backend, value=value)
        )
    numeric = float(value)
    if numeric <= 0.0 or numeric >= 1.0:
        raise ValueError(
            f"backend_config['{key}'] for backend '{backend}' must be in (0, 1); got {numeric}."
        )


def _must_be_bool(backend: str, key: str, value: Any) -> None:
    if not isinstance(value, bool):
        raise ValueError(
            f"backend_config['{key}'] for backend '{backend}' must be a boolean; got {value!r}."
        )


def _must_be_positive_float(backend: str, key: str, value: Any) -> None:
    if not isinstance(value, (int, float)):
        raise ValueError(
            "backend_config['{key}'] for backend '{backend}' must be a positive "
            "number; got {value!r}.".format(key=key, backend=backend, value=value)
        )
    numeric = float(value)
    if numeric <= 0.0:
        raise ValueError(
            f"backend_config['{key}'] for backend '{backend}' must be > 0; got {numeric}."
        )


def validate_backend_config(backend: str, backend_config: dict[str, Any]) -> dict[str, Any]:
    if backend not in _ALLOWED_CONFIG_KEYS:
        raise ValueError(f"Unsupported backend '{backend}'.")

    config = dict(backend_config)
    allowed = _ALLOWED_CONFIG_KEYS[backend]
    unknown = sorted(set(config.keys()) - set(allowed))
    if unknown:
        raise ValueError(
            f"Invalid backend_config key(s) for backend '{backend}': {unknown}. "
            f"Allowed keys: {list(allowed)}."
        )

    if backend == "pymc_gp":
        for key in ("draws", "tune", "chains"):
            if key in config:
                _must_be_positive_int(backend, key, config[key])
        if "target_accept" in config:
            _must_be_probability(backend, "target_accept", config["target_accept"])

    if backend == "sbi_npe":
        for key in (
            "max_num_epochs",
            "training_batch_size",
            "stop_after_epochs",
            "summary_samples",
        ):
            if key in config:
                _must_be_positive_int(backend, key, config[key])
        for key in ("learning_rate",):
            if key in config:
                _must_be_positive_float(backend, key, config[key])
        if "validation_fraction" in config:
            _must_be_probability(backend, "validation_fraction", config["validation_fraction"])
        if "show_train_summary" in config:
            _must_be_bool(backend, "show_train_summary", config["show_train_summary"])
        if "density_estimator" in config:
            value = config["density_estimator"]
            if not isinstance(value, str) or value not in {"maf", "nsf", "mdn"}:
                raise ValueError(
                    "backend_config['density_estimator'] for backend 'sbi_npe' "
                    "must be one of ['maf', 'nsf', 'mdn']."
                )

    if backend == "numpyro_gp" and config:
        raise ValueError(
            "Backend 'numpyro_gp' does not currently accept backend_config values in this scaffold."
        )

    return config


def allowed_backend_config_keys(backend: str) -> list[str]:
    return list(_ALLOWED_CONFIG_KEYS.get(backend, ()))
