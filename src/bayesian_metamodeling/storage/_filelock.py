"""File-based exclusive locking for registry write operations.

Two locks, because one is not enough:

- **Across processes**: an OS file lock — `fcntl.flock()` on POSIX,
  `msvcrt.locking()` on Windows — held for one read-modify-write cycle and
  released on context exit or process death.
- **Across threads in one process**: a plain `threading.Lock` per registry path.

The second one is not belt-and-braces. This module used to claim that opening a
fresh file descriptor per acquirer serialized threads as well, "both backends
behave correctly when separate fds are used per acquirer". That is true of
`fcntl.flock()` and **false** of `msvcrt.locking()`, whose locks are owned by the
*process*, not the descriptor. Worse, `LK_LOCK` does not block indefinitely: it
retries ten times at one-second intervals and then raises `OSError`.

So on Windows, four threads racing to update a registry did not queue up — three
of them raised and their writes were simply lost, leaving one key of four in the
file. Silent data loss in the registry, surfaced only because
`test_locked_registry_concurrent_writes` happened to assert all four keys.

Nesting `locked_registry()` for the same path within one thread is not supported
and will deadlock; registry updates are leaf operations, and a reentrant lock here
would only hide the fact that the OS-level lock cannot be reacquired either.
"""

from __future__ import annotations

import os
import threading
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


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(lock_path: Path) -> threading.Lock:
    """One lock per registry, so unrelated registries don't serialize against each other.

    Keyed by the resolved path: two callers naming the same file by different routes
    (relative vs absolute, or through a symlink) must contend on the same lock, or the
    in-process guard has a hole exactly where it matters.
    """
    key = str(lock_path.resolve())
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = _THREAD_LOCKS[key] = threading.Lock()
        return lock


@contextmanager
def locked_registry(path: Path) -> Iterator[None]:
    """Acquire an exclusive lock around registry read-modify-write cycles.

    Exclusive against other threads in this process *and* other processes.
    """
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
    # Threads first, then the OS. Taking the in-process lock before opening the
    # descriptor means only one thread ever contends for the OS lock on this
    # registry, which is precisely the case `msvcrt.locking()` cannot survive.
    with _thread_lock_for(lock_path):
        # Open in read+write binary without truncation so we don't erase the byte
        # that the lock relies on.
        fd = lock_path.open("rb+")
        try:
            _acquire(fd)
            yield
        finally:
            _release(fd)
            fd.close()
