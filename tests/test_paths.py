import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from goflight_memory.infra.config import load_settings
from goflight_memory.infra.paths import ProjectPaths


class PathTests(unittest.TestCase):
    def test_default_paths_point_to_checkout(self) -> None:
        paths = ProjectPaths.resolve()
        self.assertEqual(paths.repository_root, Path(__file__).resolve().parents[1])
        self.assertTrue(paths.schema_path.is_file())
        self.assertTrue(paths.raw_dir.is_dir())
        self.assertTrue((paths.wiki_dir / "index.md").is_file())
        self.assertTrue((paths.wiki_dir / "CHANGELOG.md").is_file())
        for section in ("operators", "aircraft", "customers"):
            self.assertTrue((paths.wiki_dir / section).is_dir())

    def test_default_is_independent_of_current_directory(self) -> None:
        expected = ProjectPaths.resolve()
        original = Path.cwd()
        with TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertEqual(ProjectPaths.resolve(), expected)
            finally:
                os.chdir(original)

    def test_explicit_root_normalizes_without_writing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "checkout"
            paths = ProjectPaths.resolve(root / "unused" / "..")
            self.assertEqual(paths.repository_root, root.resolve())
            self.assertEqual(paths.raw_dir, root.resolve() / "memory" / "raw")
            self.assertEqual(paths.wiki_dir, root.resolve() / "memory" / "wiki")
            self.assertEqual(paths.schema_path, root.resolve() / "schema.md")
            self.assertEqual(paths.env_path, root.resolve() / ".env")
            self.assertFalse(root.exists())

    def test_configuration_precedence_and_selected_env_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("GOFLIGHT_USER=From File\n", encoding="utf-8")
            with patch.dict(os.environ, {"GOFLIGHT_ROOT": str(root)}, clear=True):
                settings = load_settings()
                self.assertEqual(settings.paths.repository_root, root.resolve())
                self.assertEqual(settings.contributor, "From File")
                os.environ["GOFLIGHT_USER"] = "From Shell"
                self.assertEqual(load_settings().contributor, "From Shell")
                self.assertEqual(load_settings(" From CLI ").contributor, "From CLI")

    def test_blank_contributor_requires_prompt(self) -> None:
        with TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"GOFLIGHT_ROOT": directory, "GOFLIGHT_USER": " "}, clear=True):
                self.assertIsNone(load_settings().contributor)
