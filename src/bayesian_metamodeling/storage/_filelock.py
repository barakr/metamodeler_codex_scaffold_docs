"""File-based exclusive locking for registry write operations.

Cross-platform: uses `fcntl.flock()` on POSIX and `msvcrt.locking()` on
Windows. Both APIs provide an OS-level exclusive file lock with the same
practical semantics for our use (a lock held for the duration of one
read-modify-write cycle, released on context exit or process death).

Each call to `locked_registry()` opens its own file descriptor, so multiple
threads in the same process are serialized too — both backends behave
correctly when separate fds are used per acquirer.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

if os.name == "nt":
    import msvcrt  # type: ignore[import-not-found]

    def _acquire(fd: Any) -> None:
        # msvcrt locks a region of the file starting at the current position;
        # LK_LOCK blocks until the lock is granted. We always lock byte 0.
        fd.seek(0)
        msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)

    def _release(fd: Any) -> None:
        fd.seek(0)
        msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _acquire(fd: Any) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _release(fd: Any) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def locked_registry(path: Path) -> Iterator[None]:
    """Acquire an exclusive file lock around registry read-modify-write cycles."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Windows `msvcrt.locking()` requires the locked region to actually exist
    # in the file; `fcntl.flock()` doesn't care. Ensure there is at least one
    # byte at offset 0 before opening for locking. The conditional write is
    # idempotent — concurrent processes that both decide the file is empty
    # will write the same byte to the same offset, so the resulting file is
    # the same regardless of interleaving.
    if not lock_path.exists() or lock_path.stat().st_size == 0:
        lock_path.write_bytes(b" ")
    # Open in read+write binary without truncation so we don't erase the byte
    # that the lock relies on.
    fd = lock_path.open("rb+")
    try:
        _acquire(fd)
        yield
    finally:
        _release(fd)
        fd.close()
