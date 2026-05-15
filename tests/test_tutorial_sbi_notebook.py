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
    # Cross-platform contract: T6's plot/comparison cells use `root` from the
    # `bootstrap()` helper rather than re-detecting the repo root with their
    # own `cwd` walk. We previously asserted the literal string `"repo_root
    # = cwd"`; the T6 pedagogical pass (commit 4651363) simplified that
    # cell to use `root` from bootstrap directly. Pin the new contract:
    # bootstrap is called and `root` is referenced; no `cwd` re-detection.
    assert "from bayesian_metamodeling.tutorial import bootstrap" in text
    assert "root = bootstrap()" in text
    # Tutorials are cross-platform: no %%bash, no POSIX-only PYTHONPATH prefix.
    # The pytest verification step runs through the in-notebook run_tool helper.
    assert "%%bash" not in text
    assert "PYTHONPATH=src" not in text
    # The optional appendix's pytest call is now `check=False` (demoted
    # from required to optional smoke check, per commit 4651363).
    assert (
        'run_tool(\n        "pytest", "-q", "tests/test_surrogate_backends.py"' in text
        or 'run_tool("pytest", "-q", "tests/test_surrogate_backends.py"' in text
    )
