"""Load the selected checkout's .env without overriding shell variables."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from goflight_memory.infra.paths import ProjectPaths


@dataclass(frozen=True)
class Settings:
    paths: ProjectPaths
    contributor: str | None


def load_settings(user: str | None = None) -> Settings:
    paths = ProjectPaths.resolve(os.environ.get("GOFLIGHT_ROOT") or None)
    load_dotenv(paths.env_path, override=False)
    contributor = user if user is not None else os.environ.get("GOFLIGHT_USER", "")
    return Settings(paths=paths, contributor=contributor.strip() or None)
