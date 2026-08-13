from __future__ import annotations

import builtins
import json
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import bayesian_metamodeling.surrogates.backends as backends


class FakeTensor:
    def __init__(self, data: Any) -> None:
        self._data = np.asarray(data, dtype=float)

    def detach(self) -> "FakeTensor":
        return self

    def cpu(self) -> "FakeTensor":
        return self

    def numpy(self) -> np.ndarray:
        return np.asarray(self._data, dtype=float)


class FakeTorch:
    float32 = np.float32

    def __init__(self) -> None:
        self.seed_calls: list[int] = []
        self.current_seed = 0

    def manual_seed(self, seed: int) -> None:
        value = int(seed)
        self.current_seed = value
        self.seed_calls.append(value)

    def as_tensor(self, data: Any, dtype: Any = None) -> FakeTensor:
        cast_dtype = np.float32 if dtype in (self.float32, np.float32) else dtype
        return FakeTensor(np.asarray(data, dtype=cast_dtype))


class SeedAwarePosterior:
    def __init__(self, torch_ref: FakeTorch) -> None:
        self.torch_ref = torch_ref
        self.theta_calls: list[np.ndarray] = []
        self.obs_calls: list[np.ndarray] = []

    def sample(self, shape: tuple[int], x: FakeTensor) -> FakeTensor:
        n = int(shape[0])
        obs = np.asarray(x.numpy(), dtype=float).reshape(-1)
        rng = np.random.default_rng(self.torch_ref.current_seed)
        draws = obs.sum() + rng.normal(0.0, 0.01, size=n)
        return FakeTensor(draws.reshape(n, 1))

    def log_prob(self, theta: FakeTensor, x: FakeTensor) -> FakeTensor:
        theta_arr = np.asarray(theta.numpy(), dtype=float).reshape(-1)
        obs_arr = np.asarray(x.numpy(), dtype=float).reshape(-1)
        self.theta_calls.append(theta_arr.copy())
        self.obs_calls.append(obs_arr.copy())
        value = theta_arr[0] - 0.5 * float(np.sum(obs_arr))
        return FakeTensor(np.array([value], dtype=float))


def _toy_sbi_model(*, posterior: Any, summary_samples: int = 8) -> backends.SbiNPEPosteriorModel:
    return backends.SbiNPEPosteriorModel(
        posterior=posterior,
        input_names=["a", "b"],
        output_name="y",
        x_mean=np.asarray([1.0, 10.0], dtype=float),
        x_scale=np.asarray([2.0, 5.0], dtype=float),
        y_mean=0.5,
        y_scale=2.0,
        summary_samples=summary_samples,
    )


def test_sbi_model_normalized_x_applies_mean_and_scale():
    model = _toy_sbi_model(posterior=object())
    x_norm = model._normalized_x({"a": [1.0, 3.0], "b": [10.0, 20.0]})
    assert np.allclose(x_norm, np.array([[0.0, 0.0], [1.0, 2.0]], dtype=float))


def test_sbi_model_sample_shape_and_seed_schedule(monkeypatch):
    fake_torch = FakeTorch()
    posterior = SeedAwarePosterior(fake_torch)
    model = _toy_sbi_model(posterior=posterior)
    monkeypatch.setattr(backends, "_require_torch", lambda: fake_torch)

    draws = model.sample({"a": [1.0, 3.0], "b": [10.0, 20.0]}, n=4, seed=11)
    assert draws.shape == (2, 4)
    assert fake_torch.seed_calls == [11, 12]


def test_sbi_model_sample_is_deterministic_for_same_seed(monkeypatch):
    fake_torch = FakeTorch()
    posterior = SeedAwarePosterior(fake_torch)
    model = _toy_sbi_model(posterior=posterior)
    monkeypatch.setattr(backends, "_require_torch", lambda: fake_torch)

    draws_a = model.sample({"a": [2.0], "b": [15.0]}, n=5, seed=21)
    draws_b = model.sample({"a": [2.0], "b": [15.0]}, n=5, seed=21)
    assert np.allclose(draws_a, draws_b)


def test_sbi_model_sample_changes_for_different_seed(monkeypatch):
    fake_torch = FakeTorch()
    posterior = SeedAwarePosterior(fake_torch)
    model = _toy_sbi_model(posterior=posterior)
    monkeypatch.setattr(backends, "_require_torch", lambda: fake_torch)

    draws_a = model.sample({"a": [2.0], "b": [15.0]}, n=5, seed=21)
    draws_b = model.sample({"a": [2.0], "b": [15.0]}, n=5, seed=22)
    assert not np.allclose(draws_a, draws_b)


def test_sbi_model_sample_denormalizes_output(monkeypatch):
    fake_torch = FakeTorch()

    class ConstantPosterior:
        def sample(self, shape: tuple[int], x: FakeTensor) -> FakeTensor:  # noqa: ARG002
            n = int(shape[0])
            return FakeTensor(np.full((n, 1), 0.25, dtype=float))

    model = _toy_sbi_model(posterior=ConstantPosterior())
    monkeypatch.setattr(backends, "_require_torch", lambda: fake_torch)
    draws = model.sample({"a": [1.0], "b": [10.0]}, n=3, seed=0)
    # denormalization: y = theta_norm * y_scale + y_mean => 0.25*2 + 0.5 = 1.0
    assert np.allclose(draws, np.ones((1, 3), dtype=float))


def test_sbi_model_log_prob_applies_affine_jacobian(monkeypatch):
    fake_torch = FakeTorch()
    posterior = SeedAwarePosterior(fake_torch)
    model = _toy_sbi_model(posterior=posterior)
    monkeypatch.setattr(backends, "_require_torch", lambda: fake_torch)

    logp = model.log_prob(
        {"a": [3.0], "b": [20.0]},
        {"y": [4.5]},
    )
    # x_norm = [1, 2], y_norm = (4.5 - 0.5) / 2 = 2.0
    # posterior returns y_norm - 0.5*sum(x_norm) = 2 - 1.5 = 0.5
    # model corrects to original space by subtracting log(y_scale)
    expected = 0.5 - np.log(2.0)
    assert np.allclose(logp, np.array([expected], dtype=float))


def test_sbi_model_log_prob_raises_on_length_mismatch(monkeypatch):
    fake_torch = FakeTorch()
    posterior = SeedAwarePosterior(fake_torch)
    model = _toy_sbi_model(posterior=posterior)
    monkeypatch.setattr(backends, "_require_torch", lambda: fake_torch)

    with pytest.raises(ValueError, match="Output length must match"):
        model.log_prob({"a": [1.0, 2.0], "b": [10.0, 11.0]}, {"y": [0.1]})


def test_sbi_model_log_prob_uses_normalized_targets(monkeypatch):
    fake_torch = FakeTorch()
    posterior = SeedAwarePosterior(fake_torch)
    model = _toy_sbi_model(posterior=posterior)
    monkeypatch.setattr(backends, "_require_torch", lambda: fake_torch)

    model.log_prob({"a": [1.0, 5.0], "b": [10.0, 20.0]}, {"y": [0.5, 2.5]})
    # y_norm = (y - 0.5) / 2.0
    assert np.allclose(posterior.theta_calls[0], np.array([0.0], dtype=float))
    assert np.allclose(posterior.theta_calls[1], np.array([1.0], dtype=float))


def test_sbi_model_summary_uses_configured_draws(monkeypatch):
    model = _toy_sbi_model(posterior=object(), summary_samples=7)
    called: dict[str, int] = {}

    def fake_sample(inputs: dict[str, np.ndarray], n: int, seed: int) -> np.ndarray:  # noqa: ARG001
        called["n"] = n
        called["seed"] = seed
        return np.asarray(
            [
                [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0],
                [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0],
            ],
            dtype=float,
        )

    monkeypatch.setattr(model, "sample", fake_sample)
    summary = model.summary({"a": [1.0, 2.0], "b": [10.0, 20.0]})

    assert called == {"n": 7, "seed": 0}
    assert summary["posterior_draws"] == 7
    assert summary["n"] == 2
    assert np.allclose(summary["mean"], np.array([7.0, 8.0], dtype=float))


def test_make_sbi_summary_writer_falls_back_without_tensorboard(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ):
        if name == "torch.utils.tensorboard":
            raise ImportError("blocked tensorboard import")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    writer = backends._make_sbi_summary_writer()
    assert isinstance(writer, backends._NoOpSummaryWriter)
    assert str(Path(writer.log_dir).resolve()).startswith(
        str((tmp_path / "tmp" / "sbi-logs").resolve())
    )
    writer.add_scalar("metric", 1.0, 1)
    writer.close()


# --- _TrackerCompatWriter (sbi 0.26+ tracker shim) ---


class _RecordingWriter:
    """Stand-in for tensorboard SummaryWriter that records add_scalar calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, int]] = []
        self.closed = False

    def add_scalar(self, name: str, value: Any, step: int) -> None:
        self.calls.append((name, value, step))

    def close(self) -> None:
        self.closed = True


def test_tracker_compat_writer_translates_log_metric_to_add_scalar():
    """sbi >=0.26 calls `tracker.log_metric(name, value, step=...)`; the wrapper
    must route that to the underlying writer's `add_scalar(name, value, step)`."""
    inner = _RecordingWriter()
    wrapper = backends._TrackerCompatWriter(inner)

    wrapper.log_metric("loss", 0.5, step=3)
    wrapper.log_metric("loss", 0.25)  # step=None -> 0

    assert inner.calls == [("loss", 0.5, 3), ("loss", 0.25, 0)]


def test_tracker_compat_writer_forwards_other_attrs():
    """Anything other than `log_metric` (incl. `add_scalar`, `close`, custom
    attrs) must pass straight through to the inner writer untouched."""
    inner = _RecordingWriter()
    wrapper = backends._TrackerCompatWriter(inner)

    wrapper.add_scalar("acc", 0.9, 1)
    assert inner.calls == [("acc", 0.9, 1)]

    wrapper.close()
    assert inner.closed is True


def test_make_sbi_summary_writer_wraps_real_writer_with_tracker_compat(monkeypatch, tmp_path):
    """When tensorboard IS importable, the returned writer must be a
    `_TrackerCompatWriter` so the underlying `SummaryWriter` works as both an
    sbi <0.26 `summary_writer` AND an sbi >=0.26 `tracker`."""
    monkeypatch.chdir(tmp_path)

    # Inject a fake `torch.utils.tensorboard` module exposing a fake
    # SummaryWriter that records construction args.
    fake_tb = types.ModuleType("torch.utils.tensorboard")
    constructed: list[str] = []

    class FakeSummaryWriter:
        def __init__(self, log_dir: str) -> None:
            constructed.append(log_dir)
            self.log_dir = log_dir

        def add_scalar(self, name: str, value: Any, step: int) -> None:
            pass

    fake_tb.SummaryWriter = FakeSummaryWriter

    fake_torch = sys.modules.get("torch") or types.ModuleType("torch")
    fake_torch_utils = types.ModuleType("torch.utils")
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "torch.utils", fake_torch_utils)
    monkeypatch.setitem(sys.modules, "torch.utils.tensorboard", fake_tb)

    writer = backends._make_sbi_summary_writer()

    assert isinstance(writer, backends._TrackerCompatWriter)
    assert len(constructed) == 1
    # Wrapper exposes the new interface...
    assert callable(writer.log_metric)
    # ...and forwards the legacy interface unchanged.
    assert callable(writer.add_scalar)


def test_build_sbi_inference_prefers_npe(monkeypatch):
    marker = object()
    monkeypatch.setattr(backends, "_require_sbi", lambda: object())
    monkeypatch.setattr(backends, "_make_sbi_summary_writer", lambda: marker)

    fake_inference = types.ModuleType("sbi.inference")

    class FakeNPE:
        def __init__(self, density_estimator: str, summary_writer: Any) -> None:
            self.density_estimator = density_estimator
            self.summary_writer = summary_writer

    class FakeSNPE:
        def __init__(self, prior: Any, density_estimator: str, summary_writer: Any) -> None:  # noqa: ARG002
            raise AssertionError("SNPE fallback should not be used when NPE is available")

    fake_inference.NPE = FakeNPE
    fake_inference.SNPE = FakeSNPE
    fake_sbi = types.ModuleType("sbi")
    fake_sbi.inference = fake_inference
    monkeypatch.setitem(sys.modules, "sbi", fake_sbi)
    monkeypatch.setitem(sys.modules, "sbi.inference", fake_inference)

    inference = backends._build_sbi_inference("maf")
    assert isinstance(inference, FakeNPE)
    assert inference.density_estimator == "maf"
    assert inference.summary_writer is marker


def test_build_sbi_inference_falls_back_to_snpe(monkeypatch):
    """When sbi exposes only the legacy SNPE (no NPE), fall back to SNPE."""
    marker = object()
    monkeypatch.setattr(backends, "_require_sbi", lambda: object())
    monkeypatch.setattr(backends, "_make_sbi_summary_writer", lambda: marker)

    fake_inference = types.ModuleType("sbi.inference")

    class FakeSNPE:
        def __init__(self, prior: Any, density_estimator: str, summary_writer: Any) -> None:
            self.prior = prior
            self.density_estimator = density_estimator
            self.summary_writer = summary_writer

    # No `NPE` attribute -> `from sbi.inference import NPE` raises ImportError,
    # which is the genuine "old sbi" signal that should trigger the SNPE path.
    fake_inference.SNPE = FakeSNPE
    fake_sbi = types.ModuleType("sbi")
    fake_sbi.inference = fake_inference
    monkeypatch.setitem(sys.modules, "sbi", fake_sbi)
    monkeypatch.setitem(sys.modules, "sbi.inference", fake_inference)

    inference = backends._build_sbi_inference("nsf")
    assert isinstance(inference, FakeSNPE)
    assert inference.prior is None
    assert inference.density_estimator == "nsf"
    assert inference.summary_writer is marker


def test_build_sbi_inference_uses_tracker_kwarg(monkeypatch):
    """sbi >= 0.26 renamed `summary_writer` -> `tracker`; the new name must be used.

    Regression test: an sbi-0.26-style NPE that only accepts `tracker` (passing
    `summary_writer` would warn/raise) must still be constructed correctly.
    """
    marker = object()
    monkeypatch.setattr(backends, "_require_sbi", lambda: object())
    monkeypatch.setattr(backends, "_make_sbi_summary_writer", lambda: marker)

    fake_inference = types.ModuleType("sbi.inference")

    class FakeNPE:
        # sbi 0.26-style signature: `tracker`, no `summary_writer`.
        def __init__(self, density_estimator: str, tracker: Any) -> None:
            self.density_estimator = density_estimator
            self.tracker = tracker

    fake_inference.NPE = FakeNPE
    fake_sbi = types.ModuleType("sbi")
    fake_sbi.inference = fake_inference
    monkeypatch.setitem(sys.modules, "sbi", fake_sbi)
    monkeypatch.setitem(sys.modules, "sbi.inference", fake_inference)

    inference = backends._build_sbi_inference("maf")
    assert isinstance(inference, FakeNPE)
    assert inference.density_estimator == "maf"
    assert inference.tracker is marker


def test_train_sbi_density_estimator_uses_full_kwargs():
    class Trainer:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def train(self, **kwargs: Any) -> str:
            self.calls.append(kwargs)
            return "density"

    class Inference:
        def __init__(self) -> None:
            self.trainer = Trainer()
            self.append_args: tuple[Any, Any] | None = None

        def append_simulations(self, theta: Any, x: Any) -> Trainer:
            self.append_args = (theta, x)
            return self.trainer

    inference = Inference()
    result = backends._train_sbi_density_estimator(
        inference=inference,
        theta="theta",
        x="x",
        backend_config={
            "max_num_epochs": 10,
            "training_batch_size": 8,
            "learning_rate": 1e-3,
            "validation_fraction": 0.25,
            "stop_after_epochs": 4,
            "show_train_summary": True,
        },
    )

    assert result == "density"
    assert inference.append_args == ("theta", "x")
    assert inference.trainer.calls == [
        {
            "max_num_epochs": 10,
            "training_batch_size": 8,
            "learning_rate": 1e-3,
            "validation_fraction": 0.25,
            "stop_after_epochs": 4,
            "show_train_summary": True,
        }
    ]


def test_train_sbi_density_estimator_falls_back_on_typeerror():
    class Trainer:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def train(self, **kwargs: Any) -> str:
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise TypeError("unsupported kwarg set")
            return "fallback_density"

    class Inference:
        def __init__(self) -> None:
            self.trainer = Trainer()

        def append_simulations(self, theta: Any, x: Any) -> Trainer:  # noqa: ARG002
            return self.trainer

    inference = Inference()
    result = backends._train_sbi_density_estimator(
        inference=inference,
        theta="theta",
        x="x",
        backend_config={"max_num_epochs": 12, "training_batch_size": 9},
    )

    assert result == "fallback_density"
    assert set(inference.trainer.calls[0].keys()) == {
        "max_num_epochs",
        "training_batch_size",
        "learning_rate",
        "validation_fraction",
        "stop_after_epochs",
        "show_train_summary",
    }
    assert inference.trainer.calls[1] == {"max_num_epochs": 12, "training_batch_size": 9}


def test_fit_sbi_npe_normalizes_inputs_and_targets(monkeypatch):
    captured: dict[str, Any] = {}

    class ArrayTorch:
        float32 = np.float32

        def __init__(self) -> None:
            self.seed_calls: list[int] = []

        def manual_seed(self, seed: int) -> None:
            self.seed_calls.append(int(seed))

        def as_tensor(self, data: Any, dtype: Any = None) -> np.ndarray:  # noqa: ARG002
            return np.asarray(data, dtype=np.float32)

    class Inference:
        def __init__(self) -> None:
            self.density_inputs: list[Any] = []

        def build_posterior(self, density_estimator: Any) -> str:
            self.density_inputs.append(density_estimator)
            return "posterior_obj"

    array_torch = ArrayTorch()
    inference = Inference()

    def fake_train(*, inference: Any, theta: Any, x: Any, backend_config: dict[str, Any]) -> str:
        captured["theta"] = np.asarray(theta, dtype=float)
        captured["x"] = np.asarray(x, dtype=float)
        captured["backend_config"] = dict(backend_config)
        return "density_estimator"

    monkeypatch.setattr(backends, "_require_torch", lambda: array_torch)
    monkeypatch.setattr(backends, "_require_sbi", lambda: object())
    monkeypatch.setattr(backends, "_build_sbi_inference", lambda density_estimator: inference)
    monkeypatch.setattr(backends, "_train_sbi_density_estimator", fake_train)

    model = backends._fit_sbi_npe(
        x=np.asarray([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0]], dtype=float),
        y=np.asarray([1.0, 2.0, 3.0], dtype=float),
        input_names=["a", "b"],
        output_name="y",
        backend_config={"summary_samples": 64, "density_estimator": "nsf"},
        seed=123,
    )

    assert array_torch.seed_calls == [123]
    assert captured["theta"].shape == (3, 1)
    assert np.isclose(float(np.mean(captured["theta"])), 0.0, atol=1e-6)
    assert np.allclose(captured["x"][:, 1], np.zeros(3, dtype=float))
    assert model.posterior == "posterior_obj"
    assert np.allclose(model.x_scale, np.asarray([0.81649658, 1.0]), atol=1e-5)
    assert model.summary_samples == 64


def test_fit_sbi_npe_uses_default_summary_samples(monkeypatch):
    class ArrayTorch:
        float32 = np.float32

        def manual_seed(self, seed: int) -> None:  # noqa: ARG002
            return None

        def as_tensor(self, data: Any, dtype: Any = None) -> np.ndarray:  # noqa: ARG002
            return np.asarray(data, dtype=np.float32)

    class Inference:
        def build_posterior(self, density_estimator: Any) -> str:  # noqa: ARG002
            return "posterior_obj"

    monkeypatch.setattr(backends, "_require_torch", lambda: ArrayTorch())
    monkeypatch.setattr(backends, "_require_sbi", lambda: object())
    monkeypatch.setattr(backends, "_build_sbi_inference", lambda density_estimator: Inference())
    monkeypatch.setattr(
        backends,
        "_train_sbi_density_estimator",
        lambda **kwargs: "density_estimator",  # noqa: ARG005
    )

    model = backends._fit_sbi_npe(
        x=np.asarray([[0.0], [1.0], [2.0]], dtype=float),
        y=np.asarray([0.0, 1.0, 2.0], dtype=float),
        input_names=["a"],
        output_name="y",
        backend_config={},
        seed=1,
    )
    assert model.summary_samples == 256


def test_save_backend_payload_sbi_contains_required_fields(monkeypatch, tmp_path):
    # v3 saves the density estimator's weights rather than pickling the posterior, so the
    # stand-in has to expose the same shape the real object does: `.posterior_estimator`
    # with a `.state_dict()`. The serializer itself is stubbed; this test is about the
    # payload's structure, not torch.
    monkeypatch.setattr(backends, "_serialize_state_dict", lambda sd: "blob123")

    class _FakeEstimator:
        def state_dict(self):
            return {"fake": "weights"}

    class _FakePosterior:
        posterior_estimator = _FakeEstimator()

    model = backends.SbiNPEPosteriorModel(
        posterior=_FakePosterior(),
        input_names=["a"],
        output_name="y",
        x_mean=np.asarray([0.0]),
        x_scale=np.asarray([1.0]),
        y_mean=2.0,
        y_scale=3.0,
        summary_samples=19,
    )
    payload_path = tmp_path / "payload.json"
    backends.save_backend_payload(model, payload_path)
    payload = json.loads(payload_path.read_text())

    assert payload["model_type"] == "sbi_npe_posterior_v3"
    assert payload["serialization"] == "state_dict_base64"
    assert payload["state_dicts_b64"] == ["blob123"]
    assert "posterior_blobs_b64" not in payload, "the pickled blob must not come back"
    assert payload["summary_samples"] == 19
    assert payload["input_names"] == ["a"]
    assert payload["output_names"] == ["y"]


def test_load_backend_model_sbi_defaults_summary_samples(monkeypatch, tmp_path):
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "model_type": "sbi_npe_posterior",
                "serialization": "torch_save_base64",
                "posterior_blob_b64": "blob",
                "input_names": ["a"],
                "output_name": "y",
                "x_mean": [0.0],
                "x_scale": [1.0],
                "y_mean": 0.0,
                "y_scale": 1.0,
            }
        )
    )
    monkeypatch.setattr(backends, "_require_sbi", lambda: object())
    monkeypatch.setattr(
        backends, "_deserialize_torch_object", lambda serialized: {"ok": serialized}
    )

    wrapper = backends.load_backend_model(
        "sbi_npe",
        payload_path,
        expected_inputs=["a"],
        expected_output="y",
    )
    assert isinstance(wrapper.model, backends.SbiNPEPosteriorModel)
    assert wrapper.model.summary_samples == 256


def test_fit_backend_model_sbi_dispatches_to_sbi_fit(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_fit_sbi_npe(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "fitted"

    monkeypatch.setattr(backends, "_fit_sbi_npe", fake_fit_sbi_npe)

    result = backends.fit_backend_model(
        backend="sbi_npe",
        x=np.asarray([[0.0], [1.0]], dtype=float),
        y=np.asarray([0.0, 1.0], dtype=float),
        input_names=["a"],
        output_name="y",
        backend_config={"density_estimator": "maf", "max_num_epochs": 3},
        seed=7,
    )

    assert result == "fitted"
    assert captured["seed"] == 7
    assert captured["backend_config"]["density_estimator"] == "maf"
    assert captured["backend_config"]["max_num_epochs"] == 3


def test_fit_backend_model_sbi_rejects_invalid_density_estimator():
    with pytest.raises(ValueError, match="density_estimator"):
        backends.fit_backend_model(
            backend="sbi_npe",
            x=np.asarray([[0.0], [1.0]], dtype=float),
            y=np.asarray([0.0, 1.0], dtype=float),
            input_names=["a"],
            output_name="y",
            backend_config={"density_estimator": "bad_flow"},
            seed=0,
        )
