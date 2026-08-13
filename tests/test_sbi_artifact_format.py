"""The sbi artifact format stores weights, not a pickled object (S1a).

Why this exists: `sbi_npe` surrogates used to be saved with `torch.save` on the live
posterior object and loaded with `weights_only=False` — i.e. pickle. Pickle *executes code
while deserialising*, so opening someone's surrogate was equivalent to running their program.
The `hasattr(obj, "sample")` check that sat next to it could not help: it inspected the return
value of an operation whose danger is its side effects.

v3 stores the density estimator's `state_dict` (tensors only) plus the recipe to rebuild the
architecture, and loads with `weights_only=True`. Nothing in the file can run.

**Backward compatibility is deliberate.** Artifacts fitted before the change still load, so
nobody's local work breaks — but never silently: they warn, and `MM_STRICT_ARTIFACTS=1` turns
that into an error so CI can prove the repository itself never depends on the unsafe path.

On the prior, since it looks like an omission: `_fit_sbi_npe` passes no prior, so sbi derives
an `ImproperEmpirical` one. Measured on sbi 0.26.1 it is improper and flat — `log_prob` is
`0.0` even at theta = 1e6 — and neither `log_prob` nor `sample` changes when it is rebuilt
from wildly different moments. Only its dimension matters, so no training data is carried in
the artifact and no fitted result moves.
"""

from __future__ import annotations

import base64
import io
import json
import pickle
import warnings

import numpy as np
import pytest

from tests.backend_support import _has_sbi

pytestmark = pytest.mark.optional_backend


def _skip_without_sbi():
    if not _has_sbi():
        pytest.skip("needs sbi")


class TestLegacyPickleFormat:
    """v2 artifacts still load — loudly, and refusably."""

    def test_warns_that_the_artifact_is_executable(self, monkeypatch):
        _skip_without_sbi()
        import bayesian_metamodeling.surrogates.backends as backends

        monkeypatch.delenv(backends.STRICT_ARTIFACTS_ENV_VAR, raising=False)

        class _Posterior:
            def sample(self, *a, **k):  # pragma: no cover - never called
                raise NotImplementedError

            def log_prob(self, *a, **k):  # pragma: no cover - never called
                raise NotImplementedError

        fake_torch = type("T", (), {"load": staticmethod(lambda *a, **k: _Posterior())})
        monkeypatch.setattr(backends, "_require_torch", lambda: fake_torch)

        blob = base64.b64encode(b"irrelevant").decode("ascii")
        with pytest.warns(backends.LegacyPickleArtifactWarning, match="runs code contained"):
            backends._deserialize_torch_object(blob)

    def test_strict_mode_refuses_it(self, monkeypatch):
        _skip_without_sbi()
        import bayesian_metamodeling.surrogates.backends as backends

        monkeypatch.setenv(backends.STRICT_ARTIFACTS_ENV_VAR, "1")
        blob = base64.b64encode(b"irrelevant").decode("ascii")
        with pytest.raises(ValueError, match="Refusing to load a legacy pickled"):
            backends._deserialize_torch_object(blob)

    def test_the_warning_says_how_to_fix_it(self, monkeypatch):
        _skip_without_sbi()
        import bayesian_metamodeling.surrogates.backends as backends

        monkeypatch.setenv(backends.STRICT_ARTIFACTS_ENV_VAR, "1")
        with pytest.raises(ValueError) as excinfo:
            backends._deserialize_torch_object(base64.b64encode(b"x").decode("ascii"))
        message = str(excinfo.value)
        assert "bayesmm surrogate fit" in message, "must name the command that rewrites it"
        assert "only load artifacts you fitted yourself" in message


class TestSafeLoadRefusesCode:
    """The security property, tested directly rather than inferred from the format."""

    def test_a_pickled_object_in_a_v3_slot_is_refused(self):
        _skip_without_sbi()
        import torch

        from bayesian_metamodeling.surrogates.backends import _deserialize_state_dict

        # A payload that is a pickled Python object rather than a tensor container. Under
        # the old `weights_only=False` load this would be reconstructed (and, for a crafted
        # payload, would execute). `weights_only=True` must refuse it.
        buffer = io.BytesIO()
        torch.save({"not_a_tensor": _Marker()}, buffer)
        blob = base64.b64encode(buffer.getvalue()).decode("ascii")

        with pytest.raises(Exception) as excinfo:
            _deserialize_state_dict(blob)
        assert "weights_only" in str(excinfo.value) or "Unsupported" in str(excinfo.value), (
            f"expected torch to refuse the non-tensor payload, got: {excinfo.value}"
        )

    def test_raw_pickle_is_refused(self):
        _skip_without_sbi()
        from bayesian_metamodeling.surrogates.backends import _deserialize_state_dict

        blob = base64.b64encode(pickle.dumps(_Marker())).decode("ascii")
        with pytest.raises(Exception):
            _deserialize_state_dict(blob)


class _Marker:
    """A plain object; only used as a non-tensor payload."""


@pytest.mark.slow
class TestV3RoundTrip:
    """A real fit, saved and reloaded, must be numerically unchanged."""

    @staticmethod
    def _fit():
        from bayesian_metamodeling.surrogates.backends import fit_backend_model

        rng = np.random.default_rng(0)
        a = rng.uniform(-2, 2, 200)
        b = rng.uniform(-2, 2, 200)
        x = np.column_stack([a, b])
        y = (1.7 * a + 0.4 * b + 0.2 + rng.normal(0, 0.05, 200)).reshape(-1, 1)
        return fit_backend_model(
            backend="sbi_npe",
            x=x,
            y=y,
            input_names=["a", "b"],
            output_names=["y"],
            backend_config={
                "density_estimator": "maf",
                "max_num_epochs": 40,
                "training_batch_size": 32,
                "summary_samples": 64,
            },
            seed=0,
        )

    def test_payload_contains_weights_and_no_pickled_object(self, tmp_path):
        _skip_without_sbi()
        from bayesian_metamodeling.surrogates.backends import save_backend_payload

        path = tmp_path / "payload.json"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            save_backend_payload(self._fit(), path)
        payload = json.loads(path.read_text())

        assert payload["model_type"] == "sbi_npe_posterior_v3"
        assert payload["serialization"] == "state_dict_base64"
        assert "state_dicts_b64" in payload
        assert "posterior_blobs_b64" not in payload, "the pickled blob must be gone"
        assert payload["density_estimator"] == "maf"
        assert payload["x_dim"] == 2

    def test_reload_is_numerically_identical(self, tmp_path):
        """Not 'close' — identical. A rebuild that drifts is a silent scientific change."""
        _skip_without_sbi()
        from bayesian_metamodeling.surrogates.backends import (
            load_backend_model,
            save_backend_payload,
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = self._fit()
            query = {"a": np.array([0.5, 1.0]), "b": np.array([0.1, -0.3])}
            observed = {"y": np.array([1.1, 2.0])}
            before_lp = model.log_prob(inputs=query, outputs=observed)
            before_s = model.sample(inputs=query, n=32, seed=5)

            path = tmp_path / "payload.json"
            save_backend_payload(model, path)
            reloaded = load_backend_model(
                "sbi_npe", path, expected_inputs=["a", "b"], expected_outputs=["y"]
            )
            after_lp = reloaded.log_prob(inputs=query, outputs=observed)
            after_s = reloaded.sample(inputs=query, n=32, seed=5)

        assert np.array_equal(before_lp, after_lp), (
            f"log_prob changed across save/load: {before_lp} vs {after_lp}"
        )
        assert np.array_equal(before_s, after_s), "sample() changed across save/load"

    def test_multi_output_diagonal_round_trips(self, tmp_path):
        """`diagonal` stores D separate 1-D posteriors; the rebuild must handle each."""
        _skip_without_sbi()
        from bayesian_metamodeling.surrogates.backends import (
            fit_backend_model,
            load_backend_model,
            save_backend_payload,
        )

        rng = np.random.default_rng(1)
        a = rng.uniform(-2, 2, 160)
        x = a.reshape(-1, 1)
        y = np.column_stack([1.5 * a + 0.1, -0.8 * a + 2.0]) + rng.normal(0, 0.05, (160, 2))

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = fit_backend_model(
                backend="sbi_npe",
                x=x,
                y=y,
                input_names=["a"],
                output_names=["y1", "y2"],
                backend_config={
                    "density_estimator": "maf",
                    "max_num_epochs": 30,
                    "training_batch_size": 32,
                    "summary_samples": 32,
                    "output_correlation": "diagonal",
                },
                seed=0,
            )
            path = tmp_path / "payload.json"
            save_backend_payload(model, path)
            payload = json.loads(path.read_text())
            assert len(payload["state_dicts_b64"]) == 2, "one state dict per output"
            assert payload["theta_dim"] == 1, "diagonal fits D independent 1-D posteriors"

            query = {"a": np.array([0.25, -1.0])}
            before = model.sample(inputs=query, n=16, seed=3)
            reloaded = load_backend_model(
                "sbi_npe", path, expected_inputs=["a"], expected_outputs=["y1", "y2"]
            )
            after = reloaded.sample(inputs=query, n=16, seed=3)

        assert np.array_equal(before, after), "multi-output sample changed across save/load"
