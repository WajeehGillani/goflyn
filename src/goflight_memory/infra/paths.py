"""Resolve paths without depending on the launch directory or creating files."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    repository_root: Path

    @classmethod
    def resolve(cls, root: str | Path | None = None) -> "ProjectPaths":
        # Supported installation: editable install from a source checkout.
        default_root = Path(__file__).resolve().parents[3]
        return cls(Path(root).expanduser().resolve() if root is not None else default_root)

    @property
    def memory_dir(self) -> Path:
        return self.repository_root / "memory"

    @property
    def raw_dir(self) -> Path:
        return self.memory_dir / "raw"

    @property
    def wiki_dir(self) -> Path:
        return self.memory_dir / "wiki"

    @property
    def schema_path(self) -> Path:
        return self.repository_root / "schema.md"

    @property
    def env_path(self) -> Path:
        return self.repository_root / ".env"

    @property
    def lock_path(self) -> Path:
        return self.memory_dir / ".write.lock"

    def memory_path(self, relative: str) -> Path:
        """Only deterministic application paths may reach the filesystem."""
        path = self.memory_dir / relative
        if path.is_absolute() and not path.is_relative_to(self.memory_dir):
            raise ValueError("Path is outside memory")
        if ".." in path.parts:
            raise ValueError("Parent traversal is not allowed")
        for part in (path, *path.parents):
            if part == self.repository_root:
                break
            if part.is_symlink():
                raise ValueError("Symlinks are not supported inside memory")
        return path
