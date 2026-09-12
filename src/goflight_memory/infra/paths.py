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
