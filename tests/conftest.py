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
