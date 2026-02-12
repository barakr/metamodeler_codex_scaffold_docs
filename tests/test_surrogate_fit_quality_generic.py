import numpy as np

from metamodeler.surrogates import MockGaussianConditionalSurrogate


def _make_dataset(seed: int, noise: float, nonlinear: bool = False):
    rng = np.random.default_rng(seed)
    x = rng.uniform(-1.0, 1.0, size=(200, 1))
    y = 2.5 * x[:, 0] - 0.7
    if nonlinear:
        y = y + 0.3 * (x[:, 0] ** 2)
    y = y + rng.normal(0.0, noise, size=len(y))
    return x, y


def _fit_score(x: np.ndarray, y: np.ndarray) -> float:
    model = MockGaussianConditionalSurrogate.fit(x, y)
    preds = model.summary({"x": x[:, 0]})["mean"]
    preds_arr = np.asarray(preds)
    return float(np.mean((preds_arr - y) ** 2))


def test_generic_fit_quality_easy_case():
    x, y = _make_dataset(seed=1, noise=0.05)
    mse = _fit_score(x, y)
    assert mse < 0.02


def test_generic_fit_quality_medium_case():
    x, y = _make_dataset(seed=2, noise=0.15)
    mse = _fit_score(x, y)
    assert mse < 0.08


def test_generic_fit_quality_harder_case_nonlinear():
    x, y = _make_dataset(seed=3, noise=0.15, nonlinear=True)
    mse = _fit_score(x, y)
    assert mse < 0.2
