"""Repo-root discovery and notebook bootstrap.

`bootstrap()` is the cross-platform replacement for the hardcoded
`cd /Users/barak/Downloads/metamodeler_codex_scaffold_docs` lines that used
to live in every tutorial's `%%bash` cell. Walks up from `Path.cwd()` looking
for the project's `pyproject.toml` (with `name = "bayesian-metamodeling"`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_MARKER = "pyproject.toml"
_PACKAGE_LINE = 'name = "bayesian-metamodeling"'


def _looks_like_repo_root(path: Path) -> bool:
    candidate = path / _MARKER
    if not candidate.is_file():
        return False
    try:
        content = candidate.read_text(encoding="utf-8")
    except OSError:
        return False
    return _PACKAGE_LINE in content


def find_repo_root(start: str | Path | None = None) -> Path:
    """Walk up from `start` (or `Path.cwd()`) and return the metamodeler repo root.

    Raises `FileNotFoundError` if no marker is found before reaching the filesystem root.
    """
    if start is None:
        start_path = Path.cwd()
    else:
        start_path = Path(start)
        if start_path.is_file():
            start_path = start_path.parent
    start_path = start_path.resolve()

    for candidate in [start_path, *start_path.parents]:
        if _looks_like_repo_root(candidate):
            return candidate

    raise FileNotFoundError(
        "Could not locate bayesian-metamodeling repo root. "
        f"Searched from {start_path} upward for a pyproject.toml containing {_PACKAGE_LINE!r}."
    )


def bootstrap(notebook_file: str | Path | None = None, *, chdir: bool = True) -> Path:
    """Locate the repo root, set CWD to it, and ensure `src` is on `sys.path`.

    Designed to be the first call in every tutorial notebook. Idempotent.
    Returns the repo root `Path`.
    """
    root = find_repo_root(notebook_file)

    if chdir and Path.cwd().resolve() != root:
        os.chdir(root)

    src_dir = str((root / "src").resolve())
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    return root
