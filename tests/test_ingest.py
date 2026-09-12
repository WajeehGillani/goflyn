import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from goflight_memory.core.ingest import IngestError, atomic_write, ingest
from goflight_memory.core.models import Entity, Extraction, Fact, SourceMetadata
from goflight_memory.infra.git import GitError, GitRepository
from goflight_memory.infra.lock import repository_lock
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.infra.sources import next_source_id, read_source, save_source
from goflight_memory.wiki.naming import normalized, page_name, slug
from goflight_memory.wiki.pages import conflicts_for, parse_page, render_page


class FakeLLM:
    """Offline semantic fixture; the real ingest/Git/filesystem code remains in use."""

    def __init__(self, base="Teterboro", notice="24 hours"):
        self.base = base
        self.notice = notice
        self.calls = 0

    def extract(self, schema, source_id, contributor, text):
        self.calls += 1
        entities = [Entity(entity_type="operator", name="Atlantic Air"), Entity(entity_type="aircraft", name="N123GF")]
        return Extraction(entities=entities, facts=[
            Fact(entity_type=kind, entity_name=name, field=field, value=value,
                 source_id=source_id, contributor=contributor)
            for kind, name, field, value in (
                ("aircraft", "N123GF", "operator", "Atlantic Air"),
                ("aircraft", "N123GF", "type", "Challenger 350"),
                ("aircraft", "N123GF", "home_base", self.base),
                ("operator", "Atlantic Air", "minimum_booking_notice", self.notice),
            )
        ])


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.paths = ProjectPaths.resolve(self.temporary.name)
        root = self.paths.repository_root
        for folder in ("raw", "wiki/operators", "wiki/aircraft", "wiki/customers"):
            directory = self.paths.memory_dir / folder
            directory.mkdir(parents=True, exist_ok=True)
            (directory / ".gitkeep").touch()
        checkout = ProjectPaths.resolve()
        for name in ("schema.md", "memory/wiki/index.md", "memory/wiki/CHANGELOG.md"):
            # Initial wiki fixtures stay independent of runtime demo data in the checkout.
            if name.endswith("index.md"):
                content = "# GoFlight Team Memory\n\n## Operators\n\n## Aircraft\n\n## Customers\n"
            elif name.endswith("CHANGELOG.md"):
                content = "# Memory Changelog\n"
            else:
                content = checkout.schema_path.read_text()
            (root / name).write_text(content, encoding="utf-8")
        (root / ".gitignore").write_text(".env\nmemory/.write.lock\n", encoding="utf-8")
        self.git = GitRepository(root)
        self.git.run("init", "-q")
        self.git.run("config", "user.name", "Test Committer")
        self.git.run("config", "user.email", "test@example.invalid")
        self.git.run("config", "commit.gpgsign", "false")
        self.git.run("add", ".")
        self.git.run("commit", "-qm", "test foundation")

    def add_note(self, text="First note", contributor="John", client=None):
        return ingest(text, contributor, paths=self.paths, client=client or FakeLLM())

    def wiki_snapshot(self):
        return {str(p.relative_to(self.paths.wiki_dir)): p.read_bytes()
                for p in self.paths.wiki_dir.rglob("*.md")}

    def aircraft(self):
        return parse_page((self.paths.wiki_dir / "aircraft/n123gf.md").read_text())

    def test_source_ids_and_exact_immutable_bytes(self):
        self.assertEqual(next_source_id(self.paths.raw_dir), "source-001")
        metadata = SourceMetadata(source_id="source-001", contributor='John: "Ops"', source_type="note", created_at=datetime.now(timezone.utc))
        note = "  Original note\r\nSecond line\n---\n\n  "
        path = save_source(self.paths.raw_dir, metadata, note)
        before = path.read_bytes()
        self.assertEqual(read_source(path), (metadata, note))
        self.assertTrue(before.endswith(note.encode()))
        with self.assertRaises(FileExistsError):
            save_source(self.paths.raw_dir, metadata, "Different note")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(next_source_id(self.paths.raw_dir), "source-002")
        (self.paths.raw_dir / "source-099.md").touch()
        self.assertEqual(next_source_id(self.paths.raw_dir), "source-100")

    def test_new_facts_index_links_and_git_attribution(self):
        result = self.add_note()
        self.assertEqual(result.source_id, "source-001")
        self.assertEqual(len(result.created_entities), 2)
        self.assertEqual(len(self.aircraft().facts), 3)
        aircraft = (self.paths.wiki_dir / "aircraft/n123gf.md").read_text()
        operator = (self.paths.wiki_dir / "operators/atlantic-air.md").read_text()
        self.assertIn("[Atlantic Air](../operators/atlantic-air.md)", aircraft)
        self.assertIn("[N123GF](../aircraft/n123gf.md)", operator)
        self.assertIn("[source-001](../../raw/source-001.md) — John", aircraft)
        self.assertIn("[N123GF](aircraft/n123gf.md)", (self.paths.wiki_dir / "index.md").read_text())
        self.assertIn("Contributor: John", (self.paths.wiki_dir / "CHANGELOG.md").read_text())
        self.assertEqual(self.git.run("log", "-1", "--format=%s"), "ingest source-001 by John")
        self.assertEqual(self.git.head(), result.git_commit)
        self.assertEqual(self.git.run("status", "--porcelain"), "")

    def test_same_fact_merges_provenance_and_index_is_unique(self):
        self.add_note()
        result = self.add_note("Confirmation", "Sarah", FakeLLM("  TETERBORO  ", "24 HOURS"))
        bases = [fact for fact in self.aircraft().facts if fact.field == "home_base"]
        self.assertEqual(len(bases), 1)
        self.assertEqual({e.contributor for e in bases[0].evidence}, {"John", "Sarah"})
        self.assertEqual(result.conflicts, [])
        index = (self.paths.wiki_dir / "index.md").read_text()
        self.assertEqual(index.count("operators/atlantic-air.md"), 1)
        self.assertEqual(index.count("aircraft/n123gf.md"), 1)

    def test_contradiction_retains_both_sources_and_stable_conflicts(self):
        first = self.add_note()
        raw = self.paths.raw_dir / "source-001.md"
        before = raw.read_bytes()
        result = self.add_note("Update", "Sarah", FakeLLM("Westchester", "48 hours"))
        self.assertEqual(raw.read_bytes(), before)
        self.assertEqual({c.field for c in result.conflicts}, {"home_base", "minimum_booking_notice"})
        self.assertTrue(all(c.status == "unresolved" for c in result.conflicts))
        for conflict in result.conflicts:
            self.assertEqual({f.source_id for f in conflict.evidence}, {"source-001", "source-002"})
            self.assertEqual({f.contributor for f in conflict.evidence}, {"John", "Sarah"})
        conflict_id = conflicts_for(self.aircraft())[0].conflict_id
        self.add_note("Another update", "Taylor", FakeLLM("White Plains", "48 hours"))
        self.assertEqual(conflicts_for(self.aircraft())[0].conflict_id, conflict_id)
        self.assertNotEqual(first.git_commit, result.git_commit)

    def test_successful_retry_is_idempotent_without_llm_call(self):
        first = self.add_note()
        client = FakeLLM()
        second = self.add_note(client=client)
        self.assertTrue(second.already_ingested)
        self.assertEqual(first.git_commit, second.git_commit)
        self.assertEqual(client.calls, 0)
        self.assertEqual(len(list(self.paths.raw_dir.glob("source-*.md"))), 1)

    def test_failed_extraction_keeps_raw_and_exact_retry_reuses_id(self):
        before = self.wiki_snapshot()
        with patch.object(FakeLLM, "extract", side_effect=RuntimeError("Provider unavailable")):
            with self.assertRaisesRegex(IngestError, "source-001 remains pending"):
                self.add_note()
        raw = self.paths.raw_dir / "source-001.md"
        raw_bytes = raw.read_bytes()
        self.assertEqual(before, self.wiki_snapshot())
        with self.assertRaises(GitError):
            self.add_note("Different note")
        result = self.add_note()
        self.assertEqual(result.source_id, "source-001")
        self.assertEqual(raw.read_bytes(), raw_bytes)

    def test_forged_provenance_is_rejected(self):
        before = self.wiki_snapshot()
        forged = FakeLLM().extract("", "source-999", "Impostor", "")
        with patch.object(FakeLLM, "extract", return_value=forged):
            with self.assertRaisesRegex(IngestError, "source or contributor"):
                self.add_note()
        self.assertEqual(before, self.wiki_snapshot())

    def test_invalid_llm_data_and_source_creation_failure_do_not_write_wiki(self):
        before = self.wiki_snapshot()
        with patch.object(FakeLLM, "extract", return_value={"entities": "invalid"}):
            with self.assertRaises(IngestError):
                self.add_note()
        self.assertEqual(before, self.wiki_snapshot())
        # Retry this pending source first, then exercise a new source creation failure.
        self.add_note()
        before = self.wiki_snapshot()
        client = FakeLLM()
        with patch("goflight_memory.core.ingest.save_source", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.add_note("Second note", client=client)
        self.assertEqual(client.calls, 0)
        self.assertEqual(before, self.wiki_snapshot())

    def test_commit_failure_rolls_back_wiki_and_only_own_staging(self):
        self.add_note()
        before, head = self.wiki_snapshot(), self.git.head()
        def fail_commit(repo, paths, message):
            repo.run("add", "--", *(str(p.relative_to(repo.root)) for p in paths))
            raise GitError("Commit failed")
        with patch.object(GitRepository, "commit", fail_commit):
            with self.assertRaisesRegex(IngestError, "Wiki changes rolled back"):
                self.add_note("Update", "Sarah", FakeLLM("Westchester", "48 hours"))
        self.assertEqual(self.wiki_snapshot(), before)
        self.assertEqual(self.git.head(), head)
        self.assertEqual(self.git.run("diff", "--cached", "--name-only"), "")
        result = self.add_note("Update", "Sarah", FakeLLM("Westchester", "48 hours"))
        self.assertEqual(result.source_id, "source-002")

    def test_failed_write_restores_previously_written_files(self):
        before = self.wiki_snapshot()
        calls = 0
        def fail_second(path, content):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("Disk full")
            atomic_write(path, content)
        with patch("goflight_memory.core.ingest.atomic_write", side_effect=fail_second):
            with self.assertRaises(IngestError):
                self.add_note()
        self.assertEqual(before, self.wiki_snapshot())
        self.assertEqual(self.git.run("diff", "--cached", "--name-only"), "")

    def test_unrelated_files_and_secrets_are_not_committed(self):
        unrelated = self.paths.repository_root / "scratch.txt"
        unrelated.write_text("user work")
        (self.paths.repository_root / ".env").write_text("OPENAI_API_KEY=test-only-placeholder")
        self.add_note()
        committed = self.git.run("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
        self.assertTrue(all(name.startswith("memory/") for name in committed))
        self.assertFalse(self.git.tracked(unrelated))
        self.assertFalse(self.git.tracked(self.paths.env_path))
        self.git.run("add", "scratch.txt")
        with self.assertRaisesRegex(GitError, "staged changes"):
            self.add_note("Next")
        self.assertEqual(self.git.run("diff", "--cached", "--name-only"), "scratch.txt")

    def test_dirty_memory_is_not_overwritten(self):
        self.add_note()
        file = self.paths.wiki_dir / "aircraft/n123gf.md"
        file.write_text(file.read_text() + "\nUser edit\n")
        before = file.read_bytes()
        with self.assertRaisesRegex(GitError, "memory edits"):
            self.add_note("Next")
        self.assertEqual(file.read_bytes(), before)

    def test_unrelated_file_staged_during_extraction_stays_out_of_runtime_commit(self):
        unrelated = self.paths.repository_root / "scratch.txt"
        unrelated.write_text("user work")
        extracted = FakeLLM().extract("", "source-001", "John", "")
        def stage_unrelated(*args):
            self.git.run("add", "scratch.txt")
            return extracted
        with patch.object(FakeLLM, "extract", side_effect=stage_unrelated):
            self.add_note()
        committed = self.git.run("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
        self.assertNotIn("scratch.txt", committed)
        self.assertEqual(self.git.run("diff", "--cached", "--name-only"), "scratch.txt")

    def test_customer_facts_create_an_attributed_customer_page(self):
        extracted = Extraction(
            entities=[Entity(entity_type="customer", name="Acme Corp")],
            facts=[Fact(entity_type="customer", entity_name="Acme Corp", field="airport_preferences",
                        value="Teterboro", source_id="source-001", contributor="John")],
        )
        with patch.object(FakeLLM, "extract", return_value=extracted):
            result = self.add_note()
        self.assertEqual(result.pages_changed, ["memory/wiki/customers/acme-corp.md"])
        self.assertIn("[Acme Corp](customers/acme-corp.md)", (self.paths.wiki_dir / "index.md").read_text())

    def test_no_supported_facts_preserves_source_without_filler_pages(self):
        with patch.object(FakeLLM, "extract", return_value=Extraction(entities=[], facts=[])):
            result = self.add_note()
        self.assertEqual(result.created_entities, [])
        self.assertEqual(result.pages_changed, [])
        self.assertEqual(read_source(self.paths.raw_dir / "source-001.md")[1], "First note")

    def test_slug_collision_does_not_merge_distinct_entities(self):
        extraction = Extraction(
            entities=[Entity(entity_type="operator", name=name) for name in ("Air Co!", "Air Co?")],
            facts=[Fact(entity_type="operator", entity_name=name, field="contacts", value="Dispatch",
                        source_id="source-001", contributor="John") for name in ("Air Co!", "Air Co?")],
        )
        with patch.object(FakeLLM, "extract", return_value=extraction):
            with self.assertRaisesRegex(IngestError, "filename collision"):
                self.add_note()
        self.assertFalse(list((self.paths.wiki_dir / "operators").glob("*.md")))

    def test_concurrent_ingests_read_latest_state_and_keep_both_updates(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self.add_note, "First", "John", FakeLLM()),
                executor.submit(self.add_note, "Second", "Sarah", FakeLLM("Westchester", "48 hours")),
            ]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual({r.source_id for r in results}, {"source-001", "source-002"})
        self.assertEqual(len(conflicts_for(self.aircraft())), 1)
        self.assertEqual(self.git.run("rev-list", "--count", "HEAD"), "3")
        self.assertEqual(self.git.run("status", "--porcelain"), "")

    def test_lock_blocks_another_process_and_releases(self):
        script = (
            "import sys; from pathlib import Path; "
            "from goflight_memory.infra.lock import repository_lock; "
            "print('attempting', flush=True)\n"
            "with repository_lock(Path(sys.argv[1])): print('acquired', flush=True)\n"
        )
        with repository_lock(self.paths.lock_path):
            child = subprocess.Popen([sys.executable, "-c", script, str(self.paths.lock_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.addCleanup(lambda: child.kill() if child.poll() is None else None)
            self.assertEqual(child.stdout.readline().strip(), "attempting")
            with self.assertRaises(subprocess.TimeoutExpired):
                child.wait(timeout=0.2)
        output, errors = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, errors)
        self.assertIn("acquired", output)


class FormatTests(unittest.TestCase):
    def test_normalization_and_safe_filenames(self):
        for name, expected in (("Atlantic Air", "atlantic-air"), ("Acme Corp", "acme-corp"), ("N123GF", "n123gf"), ("../Atlantic/Air", "atlantic-air")):
            self.assertEqual(slug(name), expected)
        self.assertEqual(page_name(Entity(entity_type="aircraft", name="N123GF")), "aircraft/n123gf.md")
        self.assertEqual(normalized(" TETERBORO\n "), normalized("Teterboro"))
        with self.assertRaises(ValueError):
            slug("../")

    def test_markdown_special_characters_round_trip_without_injected_structure(self):
        from goflight_memory.core.models import Evidence, WikiFact, WikiPage
        page = WikiPage(entity=Entity(entity_type="customer", name="Acme [VIP]"), facts=[
            WikiFact(field="travel_preferences", value="A | B\n## Fake\n<script>*Hi*</script>",
                     evidence=[Evidence(source_id="source-001", contributor="John [Ops] | A<br>B")])
        ])
        rendered = render_page(page, {page_name(page.entity): page})
        self.assertEqual(parse_page(rendered), page)
        self.assertNotIn("\n## Fake", rendered)
        self.assertNotIn("<script>", rendered)

    def test_memory_path_rejects_traversal_and_symlinks(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside:
            paths = ProjectPaths.resolve(directory)
            paths.memory_dir.mkdir()
            (paths.memory_dir / "raw").symlink_to(outside)
            for target in ("../outside", "raw/source-001.md", outside):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    paths.memory_path(target)
