import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backend_support import optional_backend_status, skip_optional_backend_tests


def pytest_report_header(config: pytest.Config) -> str:
    status = optional_backend_status()
    return (
        "optional backend availability: "
        f"pymc={status['pymc']} sbi={status['sbi']} "
        f"skip_flag={status['skip_optional_backend_tests']} "
        "(set MM_SKIP_OPTIONAL_BACKEND_TESTS=1 to skip optional backend tests)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not skip_optional_backend_tests():
        return
    skip_marker = pytest.mark.skip(
        reason="MM_SKIP_OPTIONAL_BACKEND_TESTS is set; optional backend tests disabled."
    )
    for item in items:
        if "optional_backend" in item.keywords:
            item.add_marker(skip_marker)


def read_json(path: Path) -> dict:
    """Read and parse a JSON file."""
    return json.loads(path.read_text())


@pytest.fixture
def linear_run_store(tmp_path):
    """Create a minimal run store with linear data: y = a + b."""
    runs = tmp_path / "store" / "runs"
    runs.mkdir(parents=True)
    for i, x in enumerate([0.0, 1.0, 2.0]):
        run = runs / f"r{i}"
        run.mkdir()
        (run / "inputs.json").write_text(json.dumps({"a": x, "b": x + 1.0}))
        (run / "outputs.json").write_text(json.dumps({"y": x + (x + 1.0)}))
    return tmp_path / "store"


@pytest.fixture
def surrogate_spec_factory():
    """Factory for creating SurrogateSpec instances."""
    from bayesian_metamodeling.spec import SurrogateSpec

    def _factory(store: str, **overrides):
        base = {
            "schema_version": "1.0",
            "name": "test_spec",
            "kind": "conditional",
            "inputs": ["a", "b"],
            "outputs": ["y"],
            "backend": "pymc_gp",
            "backend_config": {},
            "dataset_ref": {"run_store_root": store},
            "seed": 0,
        }
        base.update(overrides)
        return SurrogateSpec.model_validate(base)

    return _factory
