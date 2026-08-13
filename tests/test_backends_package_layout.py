"""The backends split must not silently break monkeypatching (D2).

`backends.py` was 1300 lines; it is now a package. The split is safe only because of one
non-obvious property, and this file exists to keep that property from rotting.

**The hazard.** Nine names in `backends/__init__.py` are monkeypatched by the test suite —
`_require_torch` alone in twelve places. Python's `from x import f` copies a reference, so code
in a *sibling* module that imported the name at module scope keeps its own binding, and a patch
applied to the package silently stops taking effect. Nothing fails. The affected tests keep
passing, for the wrong reason.

That is precisely the defect class this package was reviewed for, so the split resolves those
names through the package **at call time** (`_models._runtime()`), and the tests below prove it
still works rather than assuming it.
"""

from __future__ import annotations

import numpy as np
import pytest

from bayesian_metamodeling.surrogates import backends


def test_the_public_surface_survived_the_split():
    """Every name importable before must still import from the same path."""
    for name in (
        "fit_backend_model",
        "save_backend_payload",
        "load_backend_model",
        "get_backend_dependency_versions",
        "LinearGaussianModel",
        "PymcPosteriorLinearModel",
        "SbiNPEPosteriorModel",
        "LegacyPickleArtifactWarning",
        "LegacyArtifactSchemaWarning",
        "STRICT_ARTIFACTS_ENV_VAR",
        "_ModelWrapper",
        "_deserialize_state_dict",
    ):
        assert hasattr(backends, name), (
            f"`backends.{name}` disappeared in the package split — it was importable from "
            "`bayesian_metamodeling.surrogates.backends` before, and something imports it"
        )


def test_patching_the_package_reaches_code_in_a_sibling_module(monkeypatch):
    """The property the whole split depends on.

    `SbiNPEPosteriorModel` lives in `_models.py` but calls `_require_torch`, which lives in
    `__init__.py` and is monkeypatched all over the suite. If `_models` ever switches to a
    module-scope `from ... import _require_torch`, this test fails — and without it, nothing
    would.
    """
    calls: list[str] = []

    class _Sentinel(Exception):
        pass

    class _FakeTorch:
        @staticmethod
        def manual_seed(_):
            raise _Sentinel("patched _require_torch reached _models.py")

    def fake_require_torch():
        calls.append("called")
        return _FakeTorch()

    monkeypatch.setattr(backends, "_require_torch", fake_require_torch)

    model = backends.SbiNPEPosteriorModel(
        posteriors=[object()],
        input_names=["a"],
        output_names=["y"],
        x_mean=np.array([0.0]),
        x_scale=np.array([1.0]),
        y_mean=np.array([0.0]),
        y_scale=np.array([1.0]),
    )
    with pytest.raises(_Sentinel):
        model.sample(inputs={"a": np.array([0.5])}, n=2, seed=0)

    assert calls, (
        "the patch on backends._require_torch never reached SbiNPEPosteriorModel. "
        "_models.py must resolve it through the package at call time (see _runtime()); a "
        "module-scope `from ... import _require_torch` copies the reference and silently "
        "defeats every monkeypatch in the suite"
    )


def test_the_split_out_modules_do_not_import_patched_names_at_module_scope():
    """A static guard, so the failure is caught even if no test exercises the call path."""
    import inspect

    from bayesian_metamodeling.surrogates.backends import _helpers, _models

    patched = (
        "_require_torch",
        "_require_sbi",
        "_require_pymc",
        "_build_sbi_inference",
        "_train_sbi_density_estimator",
        "_make_sbi_summary_writer",
        "_serialize_state_dict",
        "_deserialize_torch_object",
        "_fit_sbi_npe",
    )
    for module in (_models, _helpers):
        source = inspect.getsource(module)
        for name in patched:
            assert f"import {name}" not in source, (
                f"{module.__name__} imports the monkeypatched name `{name}` at module scope. "
                "That copies the reference, so patches applied to the package stop taking "
                "effect and the affected tests pass for the wrong reason. Resolve it through "
                "the package at call time instead."
            )
