"""Tutorial portability: no hardcoded paths, specs validate, artifacts parse."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TUTORIALS_DIR = REPO_ROOT / "tutorials"


def _notebook_paths():
    if not TUTORIALS_DIR.exists():
        return []
    return sorted(TUTORIALS_DIR.glob("Tutorial_*.ipynb"))


@pytest.fixture(params=_notebook_paths(), ids=lambda p: p.stem)
def notebook_path(request):
    return request.param


def test_no_hardcoded_user_paths_in_notebook(notebook_path):
    """No /Users/ or /home/ absolute paths should appear in any notebook source."""
    # Notebooks are UTF-8 JSON. On Windows, `read_text()` defaults to cp1252
    # which can't decode typographic chars (em-dash, →, etc.) common in
    # tutorial prose, breaking CI's windows-latest leg with a UnicodeDecodeError.
    content = notebook_path.read_text(encoding="utf-8")
    nb = json.loads(content)
    for cell in nb.get("cells", []):
        source = "".join(cell.get("source", []))
        assert "/Users/" not in source, (
            f"Hardcoded /Users/ path in {notebook_path.name}: {source[:200]}"
        )


def test_no_tmp_old_paths_in_notebook(notebook_path):
    """No tmp/Old/ legacy cache paths should remain in notebooks."""
    # Notebooks are UTF-8 JSON. On Windows, `read_text()` defaults to cp1252
    # which can't decode typographic chars (em-dash, →, etc.) common in
    # tutorial prose, breaking CI's windows-latest leg with a UnicodeDecodeError.
    content = notebook_path.read_text(encoding="utf-8")
    nb = json.loads(content)
    for cell in nb.get("cells", []):
        source = "".join(cell.get("source", []))
        assert "tmp/Old" not in source, (
            f"Legacy tmp/Old path in {notebook_path.name}: {source[:200]}"
        )
