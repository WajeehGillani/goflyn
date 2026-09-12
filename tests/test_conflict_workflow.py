import io
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from rich.console import Console

import test_ingest as fixtures
from goflight_memory.agent.chat import run_chat
from goflight_memory.agent.resolution import review_resolution, show_conflicts
from goflight_memory.agent.router import route
from goflight_memory.core.models import Entity, Extraction, Intent, QueryResult
from goflight_memory.core.query import query
from goflight_memory.core.lint import lint
from goflight_memory.core.resolve import ResolveError, conflict_revision, list_conflicts, resolve_conflict
from goflight_memory.infra.config import Settings
from goflight_memory.infra.git import GitError, GitRepository
from goflight_memory.infra.lock import repository_lock
from goflight_memory.infra.sources import read_source
from goflight_memory.wiki.pages import conflicts_for, parse_page, recorded_conflicts


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RepositoryTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.paths, self.git = self.fixture.paths, self.fixture.git
        self.output = io.StringIO()
        self.console = Console(file=self.output, width=140, color_system=None)

    def seed_conflicts(self):
        self.fixture.add_note()
        self.fixture.add_note("Updated bases", "Sarah", fixtures.FakeLLM("Westchester", "48 hours"))
        return next(c for _, c in list_conflicts(paths=self.paths) if c.field == "home_base")

    def snapshot(self):
        return {p.relative_to(self.paths.memory_dir): p.read_bytes() for p in self.paths.memory_dir.rglob("*") if p.is_file()}

    def resolve(self, conflict, value="Westchester", **kwargs):
        return resolve_conflict(conflict.conflict_id, value, "Wajeeh", "Operator confirmed the move", paths=self.paths, **kwargs)

    def test_explicit_supported_entities_preserve_source_without_inventing_facts(self):
        for text, page in (("new customer Wajeeh", "customers/wajeeh.md"),
                           ("Add new operator Falcon Air", "operators/falcon-air.md"),
                           ("Add aircraft N123AB.", "aircraft/n123ab.md"),
                           ("Add a new customer called Northstar Capital.", "customers/northstar-capital.md"),
                           ("We have a new operator called Falcon Charter.", "operators/falcon-charter.md")):
            client = Mock()
            client.extract.side_effect = AssertionError("Explicit grammar needs no provider")
            self.assertEqual(route(text, client).intent, Intent.INGEST)
            result = self.fixture.add_note(text, "Sarah", client)
            metadata, original = read_source(self.paths.raw_dir / f"{result.source_id}.md")
            self.assertEqual((metadata.contributor, original), ("Sarah", text))
            parsed = parse_page((self.paths.wiki_dir / page).read_text())
            self.assertEqual(parsed.facts, [])
            self.assertEqual(parsed.entity_evidence[0].source_id, result.source_id)
            self.assertIn(page, (self.paths.wiki_dir / "index.md").read_text())
        self.assertTrue(lint(paths=self.paths).is_clean)

    def test_duplicate_entity_merges_assertion_evidence(self):
        first = self.fixture.add_note("Add customer Wajeeh", "John")
        second = self.fixture.add_note("new customer Wajeeh", "Sarah")
        page = parse_page((self.paths.wiki_dir / "customers/wajeeh.md").read_text())
        self.assertEqual({e.source_id for e in page.entity_evidence}, {first.source_id, second.source_id})
        self.assertEqual((self.paths.wiki_dir / "index.md").read_text().count("customers/wajeeh.md"), 1)
        self.assertEqual(len(list((self.paths.wiki_dir / "customers").glob("*.md"))), 1)

    def test_vague_mention_does_not_create_entity(self):
        client = Mock()
        # Even a provider-proposed entity with no useful facts is not an explicit assertion.
        client.extract.return_value = Extraction(entities=[Entity(entity_type="customer", name="Wajeeh")], facts=[])
        result = self.fixture.add_note("I spoke with someone named Wajeeh yesterday.", "John", client)
        self.assertEqual(result.created_entities, [])
        self.assertTrue((self.paths.raw_dir / f"{result.source_id}.md").exists())
        self.assertFalse((self.paths.wiki_dir / "customers/wajeeh.md").exists())

    def test_inline_add_uses_production_pipeline(self):
        with patch("goflight_memory.agent.chat.Console", return_value=self.console), \
             patch.object(self.console, "input", side_effect=["/add new customer Wajeeh", "/exit"]):
            run_chat(Settings(paths=self.paths, contributor="Wajeeh"))
        self.assertTrue((self.paths.raw_dir / "source-001.md").exists())
        self.assertEqual(read_source(self.paths.raw_dir / "source-001.md")[1], "new customer Wajeeh")
        self.assertTrue((self.paths.wiki_dir / "customers/wajeeh.md").exists())

    def test_human_resolution_preserves_evidence_metadata_and_git(self):
        conflict = self.seed_conflicts()
        before = self.snapshot()
        result = self.resolve(conflict)
        self.assertEqual(result.conflict.status, "resolved")
        self.assertEqual(result.conflict.evidence, conflict.evidence)
        decision = result.conflict.resolution
        self.assertEqual((decision.value, decision.reviewer, decision.reason), ("Westchester", "Wajeeh", "Operator confirmed the move"))
        self.assertIsNotNone(decision.resolved_at.tzinfo)
        after = self.snapshot()
        changed = {str(p) for p in before if before[p] != after[p]}
        self.assertEqual(changed, {"wiki/aircraft/n123gf.md", "wiki/CHANGELOG.md"})
        self.assertEqual(self.git.head(), result.git_commit)
        self.assertEqual(self.git.run("log", "-1", "--format=%s"), f"resolve {conflict.conflict_id} by Wajeeh")
        self.assertEqual(lint(paths=self.paths).unresolved_conflicts, 1)
        text = (self.paths.wiki_dir / result.page).read_text()
        self.assertEqual(recorded_conflicts(parse_page(text), text)[0], result.conflict)

    def test_custom_qualified_statement_and_escaped_metadata_round_trip(self):
        conflict = self.seed_conflicts()
        value = "Teterboro on weekdays; Westchester on weekends"
        result = resolve_conflict(conflict.conflict_id, value, "Wajeeh", "Reviewed | evidence\nNo overwrite <script>", paths=self.paths)
        text = (self.paths.wiki_dir / result.page).read_text()
        self.assertEqual(parse_page(text).resolutions[0].reason, "Reviewed | evidence\nNo overwrite <script>")
        self.assertEqual(result.conflict.resolution.value, value)
        self.assertNotIn("<script>", text)

    def test_resolved_query_uses_current_value_without_unresolved_guard(self):
        conflict = self.seed_conflicts()
        self.resolve(conflict)
        client = Mock()
        client.answer.return_value = QueryResult(answer="N123GF's current recorded home base is Westchester.", pages_used=["aircraft/n123gf.md"])
        before, head = self.snapshot(), self.git.head()
        result = query("Where is N123GF based?", paths=self.paths, client=client)
        self.assertFalse(result.has_conflict)
        self.assertNotIn("Teterboro", result.answer)
        context = client.answer.call_args.args[1]["aircraft/n123gf.md"]
        self.assertNotIn("Teterboro", context)
        self.assertIn("human-resolved current value", context)
        client.correct_answer.assert_not_called()
        self.assertEqual((before, head), (self.snapshot(), self.git.head()))

    def test_invalid_already_resolved_and_empty_requests_do_not_write(self):
        conflict = self.seed_conflicts()
        with self.assertRaises(ResolveError):
            resolve_conflict("../bad", "X", "Human", "Reason", paths=self.paths)
        with self.assertRaises(ResolveError):
            resolve_conflict("conflict-0000000000000000", "X", "Human", "Reason", paths=self.paths)
        for value, reviewer, reason in (("", "Human", "Reason"), ("X", "", "Reason"), ("X", "Human", "")):
            with self.assertRaises(ResolveError):
                resolve_conflict(conflict.conflict_id, value, reviewer, reason, paths=self.paths)
        self.resolve(conflict)
        before, head = self.snapshot(), self.git.head()
        with self.assertRaisesRegex(ResolveError, "already resolved"):
            self.resolve(conflict)
        self.assertEqual((before, head), (self.snapshot(), self.git.head()))

    def test_new_values_reopen_but_do_not_erase_past_decisions(self):
        conflict = self.seed_conflicts()
        self.resolve(conflict)
        self.fixture.add_note("Same policy confirmed", "Alex", fixtures.FakeLLM())
        self.assertEqual(lint(paths=self.paths).unresolved_conflicts, 1)
        self.fixture.add_note("New location", "Taylor", fixtures.FakeLLM("White Plains", "48 hours"))
        reopened = next(c for _, c in list_conflicts(paths=self.paths) if c.field == "home_base")
        self.assertEqual(reopened.conflict_id, conflict.conflict_id)
        self.assertEqual(lint(paths=self.paths).unresolved_conflicts, 2)
        self.resolve(reopened, "White Plains")
        page = parse_page((self.paths.wiki_dir / "aircraft/n123gf.md").read_text())
        self.assertEqual(len(page.resolutions), 2)
        self.assertEqual(conflicts_for(page)[0].resolution.value, "White Plains")

    def test_stale_review_is_rejected_after_new_evidence(self):
        conflict = self.seed_conflicts()
        revision = conflict_revision(conflict)
        self.fixture.add_note("Confirmation", "Alex", fixtures.FakeLLM())
        with self.assertRaisesRegex(ResolveError, "changed since review"):
            self.resolve(conflict, expected_revision=revision)

    def test_confirmation_required_and_numbered_selection(self):
        conflict = self.seed_conflicts()
        listing = show_conflicts(self.console, self.paths)
        before, head = self.snapshot(), self.git.head()
        with patch.object(self.console, "input", return_value="no"):
            review_resolution("Number 1 should be Westchester. Confirmed move.", listing, "Wajeeh", self.paths, self.console)
        self.assertEqual((before, head), (self.snapshot(), self.git.head()))
        def confirm(prompt):
            self.assertEqual((before, head), (self.snapshot(), self.git.head()))
            self.assertIn("Proposed resolution: Westchester", self.output.getvalue())
            return "yes"
        with patch.object(self.console, "input", side_effect=confirm):
            review_resolution(f"For {conflict.conflict_id}, Westchester is correct. Confirmed move.", listing,
                              "Wajeeh", self.paths, self.console)
        self.assertEqual(lint(paths=self.paths).unresolved_conflicts, 1)

    def test_named_resolution_and_blank_cancel(self):
        self.seed_conflicts()
        before = self.snapshot()
        with patch.object(self.console, "input", return_value="yes"):
            review_resolution("Westchester is correct for the N123GF home-base conflict. Confirmed move.", [],
                              "Wajeeh", self.paths, self.console)
        self.assertNotEqual(before, self.snapshot())
        conflict = list_conflicts(paths=self.paths)[0][1]
        before = self.snapshot()
        with patch.object(self.console, "input", return_value=""):
            review_resolution(f"/resolve {conflict.conflict_id}", [], "Wajeeh", self.paths, self.console)
        self.assertEqual(before, self.snapshot())

    def test_commit_failure_rolls_back_and_does_not_stage_unrelated_files(self):
        conflict = self.seed_conflicts()
        scratch = self.paths.repository_root / "scratch.txt"
        scratch.write_text("Unrelated user work")
        before, head = self.snapshot(), self.git.head()
        def fail(repo, paths, message):
            repo.run("add", "--", *(str(p.relative_to(repo.root)) for p in paths))
            raise GitError("Commit failed")
        with patch.object(GitRepository, "commit", fail), self.assertRaisesRegex(ResolveError, "rolled back"):
            self.resolve(conflict)
        self.assertEqual((before, head), (self.snapshot(), self.git.head()))
        self.assertEqual(self.git.run("diff", "--cached", "--name-only"), "")
        self.resolve(conflict)
        self.assertFalse(self.git.tracked(scratch))
        self.assertEqual(set(self.git.run("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()),
                         {"memory/wiki/aircraft/n123gf.md", "memory/wiki/CHANGELOG.md"})

    def test_resolution_waits_for_existing_write_lock(self):
        conflict = self.seed_conflicts()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with repository_lock(self.paths.lock_path):
                future = executor.submit(self.resolve, conflict)
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.2)
            self.assertEqual(future.result(timeout=5).conflict.status, "resolved")

    def test_cli_retry_fallback_hides_internal_validation_text(self):
        self.seed_conflicts()
        client = Mock()
        client.answer.return_value = QueryResult(answer="N123GF is based at Westchester.", pages_used=["aircraft/n123gf.md"])
        client.correct_answer.return_value = client.answer.return_value
        before, head = self.snapshot(), self.git.head()
        with patch("goflight_memory.agent.chat.Console", return_value=self.console), \
             patch("goflight_memory.agent.chat.LLMClient", return_value=client), \
             patch.object(self.console, "input", side_effect=["Where is N123GF based?", "/exit"]):
            run_chat(Settings(paths=self.paths, contributor="Wajeeh"))
        for internal in ("Query failed", "only one side", "validation failed", "Retry required"):
            self.assertNotIn(internal, self.output.getvalue())
        self.assertIn("Teterboro", self.output.getvalue())
        self.assertEqual(client.correct_answer.call_count, 1)
        self.assertEqual((before, head), (self.snapshot(), self.git.head()))


if __name__ == "__main__":
    unittest.main()
