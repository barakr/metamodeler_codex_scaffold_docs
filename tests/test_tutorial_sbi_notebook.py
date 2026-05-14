import json
from pathlib import Path


def _tutorial_source_text(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cells = payload.get("cells", [])
    lines: list[str] = []
    for cell in cells:
        lines.extend(cell.get("source", []))
    return "".join(lines)


def test_tutorial_6_uses_portable_paths_and_pytest_invocation():
    notebook_path = Path("tutorials/Tutorial_6.ipynb")
    text = _tutorial_source_text(notebook_path)

    assert "/Users/barak/Downloads/metamodeler_codex_scaffold_docs" not in text
    assert "repo_root = cwd" in text
    # Tutorials are cross-platform: no %%bash, no POSIX-only PYTHONPATH prefix.
    # The pytest verification step runs through the in-notebook run_tool helper.
    assert "%%bash" not in text
    assert "PYTHONPATH=src" not in text
    assert "run_tool('pytest', '-q', 'tests/test_surrogate_backends.py'" in text
