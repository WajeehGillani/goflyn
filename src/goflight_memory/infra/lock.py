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


@contextmanager
def repository_read_lock(path: Path) -> Iterator[None]:
    """Coordinate with ingest without creating or writing even a lock file."""
    try:
        handle = path.open("r")
    except FileNotFoundError:
        # A fresh/read-only checkout may never have ingested locally.
        yield
        if path.exists():
            raise ValueError("An ingest started while reading memory; retry the query")
        return
    with handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
