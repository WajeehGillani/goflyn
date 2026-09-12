"""Cooperative process/thread lock for one shared checkout (macOS/Linux)."""

import fcntl
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator


@contextmanager
def repository_lock(path: Path) -> Iterator[None]:
    # Keep this file: unlinking a lock allows different writers to lock different inodes.
    with path.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
