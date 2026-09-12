import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rich.console import Console

from goflight_memory.agent.chat import show_status
from goflight_memory.core.ingest import IngestError
from goflight_memory.core.lint import lint
from goflight_memory.core.models import Entity, Extraction, Fact, QueryResult
from goflight_memory.core.query import query
from goflight_memory.demo import create_demo_repository, load_demo, main, read_samples
from goflight_memory.infra.config import Settings
from goflight_memory.infra.git import GitRepository
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.infra.sources import read_source


# Offline semantic proposals only: all storage/reconciliation/locking/Git is real.
SAMPLE_FACTS = [
    [("operator", "Atlantic Air", "minimum_booking_notice", "24 hours"),
     ("aircraft", "N123GF", "operator", "Atlantic Air"),
     ("aircraft", "N123GF", "type", "Challenger 350"),
     ("aircraft", "N123GF", "home_base", "Teterboro")],
    [("operator", "Atlantic Air", "minimum_booking_notice", "48 hours"),
     ("aircraft", "N123GF", "home_base", "Westchester")],
    [("customer", "Acme Corp", "aircraft_preferences", "Challenger-class aircraft"),
     ("customer", "Acme Corp", "airport_preferences", "Teterboro or Westchester")],
    [("operator", "SkyBridge Aviation", "minimum_booking_notice", "72 hours"),
     ("aircraft", "N777SB", "operator", "SkyBridge Aviation"),
     ("aircraft", "N777SB", "type", "Gulfstream G450"),
     ("aircraft", "N777SB", "home_base", "White Plains")],
    [("customer", "Northstar Capital", "aircraft_preferences", "Gulfstream aircraft"),
     ("customer", "Northstar Capital", "airport_preferences", "White Plains"),
     ("customer", "Northstar Capital", "travel_preferences", "Quiet cabin for working")],
    [("aircraft", "N123GF", "availability", "October 14 and 15, 2026; subject to confirmation")],
    [("aircraft", "N777SB", "availability", "October 16, 2026; subject to confirmation"),
     ("operator", "SkyBridge Aviation", "booking_requirements", "Passenger manifest before confirmation")],
    [("customer", "Acme Corp", "operating_notes", "Successfully used Atlantic Air before"),
     ("customer", "Acme Corp", "travel_preferences", "Vegetarian catering")],
    [("operator", "Atlantic Air", "booking_requirements", "Reconfirm availability before promising departure")],
]


class SampleClient:
    def __init__(self):
        self.calls = []

    def extract(self, schema, source_id, contributor, text):
        index = len(self.calls)
        sample = read_samples()[index]
        assert (contributor, text) == (sample.contributor, sample.text)
        self.calls.append(text)
        facts = SAMPLE_FACTS[index]
        return Extraction(
            entities=[Entity(entity_type=kind, name=name) for kind, name in sorted({(f[0], f[1]) for f in facts})],
            facts=[Fact(entity_type=kind, entity_name=name, field=field, value=value,
                        source_id=source_id, contributor=contributor) for kind, name, field, value in facts],
        )


class DemoTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.template = ProjectPaths.resolve(self.root / "template")
        self.template.repository_root.mkdir()
        self.template.schema_path.write_text(ProjectPaths.resolve().schema_path.read_text())
        git = GitRepository(self.template.repository_root)
        git.run("init", "-q")
        git.run("config", "user.name", "Test Author")
        git.run("config", "user.email", "test@example.invalid")
        self.paths = create_demo_repository(self.root / "demo", self.template)

    def test_fictional_dataset_has_nine_notes_and_two_contributors(self):
        samples = read_samples()
        self.assertEqual(len(samples), 9)
        self.assertEqual({s.contributor for s in samples}, {"John", "Sarah"})
        self.assertEqual(len({s.text for s in samples}), 9)

    def test_new_repository_is_empty_safe_and_does_not_copy_secrets(self):
        self.assertTrue(lint(paths=self.paths).is_clean)
        self.assertFalse(self.paths.env_path.exists())
        self.assertFalse(self.paths.lock_path.exists())
        self.assertEqual(GitRepository(self.paths.repository_root).run("status", "--porcelain"), "")
        for destination in (self.paths.repository_root, self.root, self.template.repository_root):
            with self.assertRaises(FileExistsError):
                create_demo_repository(destination, self.template)
        link = self.root / "link"
        link.symlink_to(self.paths.repository_root, target_is_directory=True)
        with self.assertRaises(FileExistsError):
            create_demo_repository(link, self.template)

    def test_full_sample_flow_and_idempotent_loader(self):
        client = SampleClient()
        results = list(load_demo(paths=self.paths, client=client))
        self.assertEqual(len(client.calls), 9)
        self.assertEqual(len({r.git_commit for r in results}), 9)
        for number, sample in enumerate(read_samples(), 1):
            metadata, text = read_source(self.paths.raw_dir / f"source-{number:03d}.md")
            self.assertEqual((metadata.contributor, text), (sample.contributor, sample.text))
        report = lint(paths=self.paths)
        self.assertEqual((report.pages_scanned, report.unresolved_conflicts), (8, 2))
        self.assertEqual((report.orphan_pages, report.broken_links, report.missing_sources), (0, 0, 0))
        git = GitRepository(self.paths.repository_root)
        before = {p: p.read_bytes() for p in self.paths.memory_dir.rglob("*") if p.is_file()}
        head = git.head()
        retried = list(load_demo(paths=self.paths, client=client))
        self.assertTrue(all(r.already_ingested for r in retried))
        self.assertEqual(len(client.calls), 9)
        class AnswerClient:
            def answer(self, question, pages):
                return QueryResult(answer="Recorded aircraft class appears consistent, but suitability is unconfirmed.",
                                   pages_used=list(pages))
        result = query("Would Atlantic Air's aircraft fit Acme Corp's known preferences?",
                       paths=self.paths, client=AnswerClient())
        self.assertEqual(set(result.pages_used), {"customers/acme-corp.md", "operators/atlantic-air.md", "aircraft/n123gf.md"})
        self.assertTrue(result.has_conflict)
        self.assertEqual(before, {p: p.read_bytes() for p in self.paths.memory_dir.rglob("*") if p.is_file()})
        self.assertEqual(head, git.head())
        self.assertEqual(git.run("rev-list", "--count", "HEAD"), "10")
        self.assertEqual(git.run("status", "--porcelain"), "")

    def test_failed_load_stops_and_keeps_exact_note_pending(self):
        class FailingClient:
            def extract(self, *args):
                raise ValueError("Invalid extraction")
        with self.assertRaises(IngestError):
            list(load_demo(paths=self.paths, client=FailingClient()))
        self.assertEqual(len(list(self.paths.raw_dir.glob("source-*.md"))), 1)
        self.assertEqual(read_source(self.paths.raw_dir / "source-001.md")[1], read_samples()[0].text)
        self.assertEqual(len(list(load_demo(paths=self.paths, client=SampleClient()))), 9)

    def test_missing_key_fresh_cli_does_not_create_destination(self):
        destination = self.root / "missing-key"
        with patch("sys.argv", ["demo", "--fresh", str(destination)]), \
             patch("goflight_memory.demo.load_settings", return_value=Settings(paths=self.template, contributor=None)), \
             patch("goflight_memory.demo.Console", return_value=Console(file=io.StringIO())):
            self.assertEqual(main(), 1)
        self.assertFalse(destination.exists())

    def test_status_is_read_only_and_rejects_symlink_page(self):
        console = Console(file=io.StringIO())
        show_status(console, "Jack", self.paths)
        self.assertFalse(self.paths.lock_path.exists())
        (self.paths.wiki_dir / "operators/unsafe.md").symlink_to(self.template.schema_path)
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            show_status(console, "Jack", self.paths)


if __name__ == "__main__":
    unittest.main()
