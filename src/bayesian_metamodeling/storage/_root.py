"""Where the stores live — one answer, in one place (D3).

Every registry and artifact directory used to be a module-level constant relative to the
process working directory (`Path("tmp/run_registry.json")`, `Path("tmp/surrogate_artifacts")`).
Two consequences, both real:

1. **Running `bayesmm` from a different directory silently used a different store.** A student
   who ran from `tutorials/` would wonder where their runs went. Nothing was wrong, and nothing
   said anything.
2. **The rule for "is this registry entry inside the store" was written twice, differently.**
   `run_store` anchored on `Path.cwd()`; `surrogate_store` anchored on the registry's own
   directory. Both are defensible; having both is not.

`store_root()` is now the single answer, and it is explicit: `MM_STORE_ROOT` if set, otherwise
the process working directory — which is exactly the previous behaviour, so nothing moves for
anyone who does not set it.

**Why not anchor on the source tree.** `Path(__file__).parents[3]` is the repo root only in a
source checkout; for a `pip install`ed package it points into `site-packages`, which is not
where anyone wants their sweep results. The working directory is the right default for a
CLI-first tool. The fix for the surprise in (1) is to make the root *nameable*, not to guess a
cleverer default.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Set this to pin the store location regardless of where `bayesmm` is invoked from.
STORE_ROOT_ENV_VAR = "MM_STORE_ROOT"


def store_root() -> Path:
    """The directory every registry and artifact path is resolved against.

    Read at call time, never cached: tests rebind it, and a long-lived process could legitimately
    change directory between calls.
    """
    configured = os.environ.get(STORE_ROOT_ENV_VAR, "").strip()
    return Path(configured).expanduser().resolve() if configured else Path.cwd().resolve()


def is_inside_store(path: Path, *, root: Path | None = None) -> bool:
    """Whether `path` sits under the store root — the containment rule, written once.

    Used before reading anything a registry names. A registry is a plain JSON file that anyone
    (or any earlier version of this package) can have written, and what it names can lead to
    `torch.load`, so an entry pointing somewhere unexpected is worth refusing rather than
    following.
    """
    anchor = (root or store_root()).resolve()
    return path.resolve().is_relative_to(anchor)
