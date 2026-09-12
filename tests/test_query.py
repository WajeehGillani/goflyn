import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rich.console import Console

from goflight_memory.agent.chat import show_query
from goflight_memory.core.models import Entity, Evidence, PageSelection, QueryResult, WikiFact, WikiPage
from goflight_memory.core.query import MAX_PAGE_BYTES, QueryError, query, read_markdown
from goflight_memory.infra.git import GitRepository
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.llm.client import LLMError
from goflight_memory.wiki.links import extract_links, resolve_wiki_link, wiki_file
from goflight_memory.wiki.naming import page_name
from goflight_memory.wiki.pages import render_index, render_page


class FakeQueryLLM:
    def __init__(self, selected=None, result=None):
        self.selected = selected or []
        self.result = result
        self.selections = []
        self.contexts = []
        self.corrections = []
        self.corrected = None

    def select_pages(self, question, catalog, limit):
        self.selections.append((question, dict(catalog), limit))
        return PageSelection(pages=self.selected, reason="Test selection")

    def answer(self, question, pages):
        self.contexts.append(dict(pages))
        return self.result or QueryResult(
            answer="Recorded details support only a cautious comparison; unresolved information needs review.",
            pages_used=list(pages),
        )

    def correct_answer(self, question, pages, previous, conflicts):
        self.corrections.append((question, pages, previous, conflicts))
        return self.corrected or self.result


def wiki_fact(field, value, source="source-001", contributor="John"):
    return WikiFact(field=field, value=value, evidence=[Evidence(source_id=source, contributor=contributor)])


class QueryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.paths = ProjectPaths.resolve(temporary.name)
        for directory in ("operators", "aircraft", "customers"):
            (self.paths.wiki_dir / directory).mkdir(parents=True)
        pages = [
            WikiPage(entity=Entity(entity_type="operator", name="Atlantic Air"), facts=[
                wiki_fact("minimum_booking_notice", "24 hours"),
                wiki_fact("minimum_booking_notice", "48 hours", "source-002", "Sarah"),
            ]),
            WikiPage(entity=Entity(entity_type="aircraft", name="N123GF"), facts=[
                wiki_fact("operator", "Atlantic Air"), wiki_fact("type", "Challenger 350"),
                wiki_fact("home_base", "Teterboro"),
                wiki_fact("home_base", "Westchester", "source-002", "Sarah"),
            ]),
            WikiPage(entity=Entity(entity_type="customer", name="Acme Corp"), facts=[
                wiki_fact("aircraft_preferences", "Challenger-class aircraft"),
                wiki_fact("airport_preferences", "Teterboro or Westchester"),
            ]),
        ]
        self.write_pages(pages)
        self.client = FakeQueryLLM()

    def write_pages(self, pages):
        catalog = {page_name(page.entity): page for page in pages}
        for name, page in catalog.items():
            (self.paths.wiki_dir / name).write_text(render_page(page, catalog), encoding="utf-8")
        (self.paths.wiki_dir / "index.md").write_text(render_index(catalog), encoding="utf-8")

    def ask(self, question, **kwargs):
        return query(question, paths=self.paths, client=self.client, **kwargs)

    def test_exact_name_selects_expected_page_without_selection_call(self):
        result = self.ask("What does Acme Corp prefer?")
        self.assertEqual(self.client.selections, [])
        self.assertEqual(result.pages_used, ["customers/acme-corp.md"])
        self.assertEqual(set(self.client.contexts[0]), set(result.pages_used))

    def test_name_match_has_word_boundaries_and_handles_case(self):
        self.ask("What does ACME CORP prefer?")
        self.assertEqual(self.client.selections, [])
        self.ask("What does Acme Corporation prefer?")
        self.assertEqual(len(self.client.selections), 1)

    def test_question_about_aircraft_follows_relevant_operator_link(self):
        result = self.ask("Which aircraft does Atlantic Air operate?")
        self.assertEqual(set(result.pages_used), {"operators/atlantic-air.md", "aircraft/n123gf.md"})
        self.assertEqual(self.client.selections, [])

    def test_multi_entity_question_uses_customer_operator_and_aircraft(self):
        result = self.ask("Would Atlantic Air's aircraft fit Acme Corp's known preferences?")
        self.assertEqual(set(result.pages_used), {"customers/acme-corp.md", "operators/atlantic-air.md", "aircraft/n123gf.md"})
        self.assertIn("Challenger 350", self.client.contexts[0]["aircraft/n123gf.md"])
        self.assertTrue(result.has_conflict)

    def test_irrelevant_link_is_not_followed(self):
        self.ask("Does Atlantic Air allow pets?")
        self.assertEqual(list(self.client.contexts[0]), ["operators/atlantic-air.md"])

    def graph(self, edges):
        pages = [WikiPage(entity=Entity(entity_type="operator", name=f"Node{i}")) for i in range(len(edges))]
        self.write_pages(pages)
        for i, targets in enumerate(edges):
            path = self.paths.wiki_dir / f"operators/node{i}.md"
            links = "\n".join(f"- [Node{target}](../operators/node{target}.md)" for target in targets)
            if links:
                path.write_text(path.read_text().replace("## Related entities\n\nNone.", f"## Related entities\n\n{links}"))

    def test_traversal_respects_page_cap(self):
        self.graph([list(range(1, 8)), [], [], [], [], [], [], []])
        result = self.ask("Which operators relate to Node0?", max_pages=3)
        self.assertEqual(len(result.pages_used), 3)
        self.assertEqual(len(self.client.contexts[0]), 3)

    def test_traversal_respects_depth_and_zero_depth(self):
        self.graph([[1], [2], [3], []])
        result = self.ask("Which operators relate to Node0?")
        self.assertEqual(result.pages_used, ["operators/node0.md", "operators/node1.md", "operators/node2.md"])
        result = self.ask("Which operators relate to Node0?", max_link_depth=0)
        self.assertEqual(result.pages_used, ["operators/node0.md"])

    def test_duplicate_links_and_cycles_do_not_read_a_page_twice(self):
        self.graph([[1, 1], [0, 2], [1]])
        with patch("goflight_memory.core.query.read_markdown", wraps=read_markdown) as reader:
            self.ask("Which operators relate to Node0?")
        names = [call.args[1] for call in reader.call_args_list]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), {"index.md", "operators/node0.md", "operators/node1.md", "operators/node2.md"})

    def test_ambiguous_selection_is_from_catalog_only(self):
        self.client.selected = ["aircraft/n123gf.md", "operators/atlantic-air.md"]
        self.ask("Which operator has the Challenger near New York?")
        self.assertEqual(len(self.client.selections), 1)
        catalog = self.client.selections[0][1]
        self.assertEqual(catalog["aircraft/n123gf.md"], "N123GF")
        self.assertNotIn("Challenger 350", str(catalog))

    def test_invalid_selected_paths_are_rejected_before_reading(self):
        for path in ("../../.env", "../raw/source-001.md", "/etc/passwd", "operators/invented.md", "operators/atlantic-air.md#facts"):
            with self.subTest(path=path):
                self.client.selected = [path]
                with self.assertRaisesRegex(QueryError, "outside the provided catalog"):
                    self.ask("Find something relevant")
        self.assertEqual(self.client.contexts, [])

    def test_raw_sources_are_never_opened_and_citations_stay_wiki_relative(self):
        # There is deliberately no raw directory; compiled citations must suffice.
        original_open = Path.open
        opened = []
        def guarded_open(path, *args, **kwargs):
            self.assertNotIn("raw", path.parts)
            opened.append(path)
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", guarded_open):
            result = self.ask("Which aircraft does Atlantic Air operate?")
        self.assertTrue(all(path == self.paths.lock_path or path.is_relative_to(self.paths.wiki_dir) for path in opened))
        self.assertFalse(any("raw" in page for page in result.pages_used))

    def test_unknown_status_cannot_emit_an_unsupported_policy_answer(self):
        self.client.result = QueryResult(answer="Yes, pets are allowed.", pages_used=["operators/atlantic-air.md"], supported=False)
        result = self.ask("Does Atlantic Air allow pets?")
        self.assertFalse(result.supported)
        self.assertIn("does not currently contain", result.answer)
        self.assertNotIn("pets are allowed", result.answer)
        self.assertEqual(result.pages_used, ["operators/atlantic-air.md"])

    def test_conflict_values_are_appended_even_if_model_omits_them(self):
        self.client.result = QueryResult(answer="The current base is uncertain.", pages_used=["aircraft/n123gf.md"], has_conflict=False)
        result = self.ask("Where is N123GF based?")
        self.assertTrue(result.has_conflict)
        for phrase in ("Teterboro", "Westchester", "Unresolved", "no authoritative current value"):
            self.assertIn(phrase, result.answer)

    def test_one_sided_conflict_answer_retries_once_then_falls_back(self):
        self.client.result = QueryResult(answer="N123GF is based at Westchester.", pages_used=["aircraft/n123gf.md"])
        result = self.ask("Where is N123GF based?")
        self.assertEqual(len(self.client.corrections), 1)
        self.assertEqual(len(self.client.contexts), 1)
        self.assertIn("Teterboro", result.answer)
        self.assertIn("Westchester", result.answer)
        self.assertIn("source-001", result.answer)
        self.assertNotIn("Query failed", result.answer)

    def test_complete_relevant_answer_needs_no_retry(self):
        self.client.result = QueryResult(answer="Teterboro and Westchester conflict; the base remains unresolved.",
                                         pages_used=["aircraft/n123gf.md"])
        result = self.ask("Where is N123GF based?")
        self.assertTrue(result.has_conflict)
        self.assertEqual(self.client.corrections, [])

    def test_corrective_answer_and_evidence_are_used(self):
        self.client.result = QueryResult(answer="N123GF is based at Westchester.", pages_used=["aircraft/n123gf.md"])
        self.client.corrected = QueryResult(answer="Corrected: Teterboro and Westchester conflict and remain unresolved.",
                                            pages_used=["aircraft/n123gf.md"])
        result = self.ask("Where is N123GF based?")
        self.assertIn("Corrected:", result.answer)
        self.assertEqual(len(self.client.corrections), 1)
        self.assertEqual({f.source_id for f in self.client.corrections[0][3][0].evidence}, {"source-001", "source-002"})

    def test_both_values_do_not_excuse_choosing_a_winner(self):
        for unsafe in ("Teterboro and Westchester conflict, but Westchester is correct.",
                       "Despite an unresolved conflict with Teterboro, N123GF is currently based at Westchester.",
                       "Teterboro and Westchester conflict; use the latest report."):
            with self.subTest(answer=unsafe):
                self.client.corrections.clear()
                self.client.result = QueryResult(answer=unsafe, pages_used=["aircraft/n123gf.md"])
                result = self.ask("Where is N123GF based?")
                self.assertEqual(len(self.client.corrections), 1)
                self.assertNotIn(unsafe, result.answer)
                self.assertIn("no authoritative current value", result.answer)

    def test_retry_provider_failure_or_invalid_citation_falls_back(self):
        self.client.result = QueryResult(answer="Westchester is the base.", pages_used=["aircraft/n123gf.md"])
        with patch.object(self.client, "correct_answer", side_effect=LLMError("provider unavailable")) as retry:
            result = self.ask("Where is N123GF based?")
        self.assertEqual(retry.call_count, 1)
        self.assertIn("source-001", result.answer)
        self.assertNotIn("provider unavailable", result.answer)
        self.client.corrected = QueryResult(answer="Teterboro and Westchester remain unresolved.", pages_used=["../raw/source-001.md"])
        self.assertIn("source-001", self.ask("Where is N123GF based?").answer)

    def test_unrelated_base_conflict_does_not_affect_aircraft_type(self):
        self.client.result = QueryResult(answer="N123GF is a Challenger 350.", pages_used=["aircraft/n123gf.md"])
        result = self.ask("What type of aircraft is N123GF?")
        self.assertFalse(result.has_conflict)
        self.assertNotIn("Teterboro", result.answer)
        self.assertEqual(self.client.corrections, [])

    def test_answer_reliance_triggers_guard_even_for_unrelated_question(self):
        self.client.result = QueryResult(answer="N123GF is a Challenger 350 based at Westchester.", pages_used=["aircraft/n123gf.md"])
        result = self.ask("What type of aircraft is N123GF?")
        self.assertEqual(len(self.client.corrections), 1)
        self.assertTrue(result.has_conflict)

    def test_retry_and_fallback_preserve_files(self):
        before = {p: p.read_bytes() for p in self.paths.memory_dir.rglob("*") if p.is_file()}
        self.client.result = QueryResult(answer="Westchester is correct.", pages_used=["aircraft/n123gf.md"])
        self.ask("Where is N123GF based?")
        self.assertEqual(before, {p: p.read_bytes() for p in self.paths.memory_dir.rglob("*") if p.is_file()})
        self.assertFalse(self.paths.lock_path.exists())

    def test_unread_citation_and_missing_citation_are_rejected(self):
        for pages in (["../raw/source-001.md"], ["aircraft/n123gf.md"], []):
            with self.subTest(pages=pages):
                self.client.result = QueryResult(answer="A preference is recorded.", pages_used=pages)
                with self.assertRaises(QueryError):
                    self.ask("What does Acme Corp prefer?")

    def test_empty_wiki_and_empty_selection_return_unknown_without_synthesis(self):
        self.ask("What does Unknown Aviation prefer?")
        self.assertEqual(self.client.contexts, [])
        self.write_pages([])
        result = self.ask("What do we know?")
        self.assertFalse(result.supported)
        self.assertEqual(result.pages_used, [])
        self.assertEqual(self.client.contexts, [])

    def test_malformed_page_conflict_and_missing_page_fail_clearly(self):
        file = self.paths.wiki_dir / "aircraft/n123gf.md"
        original = file.read_text()
        for content in ("# broken", original.replace("Status: unresolved", "Status: resolved")):
            file.write_text(content)
            with self.assertRaises(QueryError):
                self.ask("Where is N123GF based?")
        file.unlink()
        with self.assertRaisesRegex(QueryError, "missing"):
            self.ask("Where is N123GF based?")
        self.assertEqual(self.client.contexts, [])

    def test_oversize_page_is_rejected_instead_of_truncated(self):
        (self.paths.wiki_dir / "aircraft/n123gf.md").write_text("x" * (MAX_PAGE_BYTES + 1))
        with self.assertRaisesRegex(QueryError, "size limit"):
            self.ask("Where is N123GF based?")

    def test_mislabeled_index_does_not_answer_from_a_different_entity(self):
        index = self.paths.wiki_dir / "index.md"
        index.write_text(index.read_text().replace("[Acme Corp]", "[Other Corp]"))
        with self.assertRaisesRegex(QueryError, "Index label does not match"):
            self.ask("What does Other Corp prefer?")
        self.assertEqual(self.client.contexts, [])

    def test_writer_starting_without_existing_lock_causes_retry(self):
        def select_with_writer(*args):
            self.paths.lock_path.touch()
            return PageSelection(pages=["customers/acme-corp.md"], reason="Test writer race")
        with patch.object(self.client, "select_pages", side_effect=select_with_writer):
            with self.assertRaisesRegex(QueryError, "retry the query"):
                self.ask("Which customer has recorded preferences?")
        self.assertEqual(self.client.contexts, [])

    def test_llm_selection_and_answer_failures_are_reported(self):
        with patch.object(self.client, "select_pages", side_effect=LLMError("selection unavailable")):
            with self.assertRaisesRegex(QueryError, "selection unavailable"):
                self.ask("Find relevant equipment")
        with patch.object(self.client, "answer", side_effect=LLMError("answer unavailable")):
            with self.assertRaisesRegex(QueryError, "answer unavailable"):
                self.ask("Where is N123GF based?")

    def test_query_preserves_all_files_and_git_history(self):
        git = GitRepository(self.paths.repository_root)
        git.run("init", "-q")
        git.run("config", "user.name", "Query Test")
        git.run("config", "user.email", "query@example.invalid")
        git.run("config", "commit.gpgsign", "false")
        git.run("add", ".")
        git.run("commit", "-qm", "query test fixture")
        before = {p.relative_to(self.paths.memory_dir): p.read_bytes() for p in self.paths.memory_dir.rglob("*") if p.is_file()}
        head = git.head()
        self.ask("Would Atlantic Air's aircraft fit Acme Corp's known preferences?")
        after = {p.relative_to(self.paths.memory_dir): p.read_bytes() for p in self.paths.memory_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(head, git.head())
        self.assertEqual(git.run("status", "--porcelain"), "")
        self.assertFalse(self.paths.lock_path.exists())

    def test_cli_output_includes_relative_page_citations(self):
        output = io.StringIO()
        result = self.ask("What does Acme Corp prefer?")
        show_query(Console(file=output, width=100), result, self.paths)
        self.assertIn("Pages used:", output.getvalue())
        self.assertIn("customers/acme-corp.md", output.getvalue())


class LinkTests(unittest.TestCase):
    def test_generated_links_and_fragments(self):
        links = extract_links("[Atlantic Air](../operators/atlantic-air.md) [evidence](../../raw/source-001.md)")
        self.assertEqual(len(links), 2)
        self.assertEqual(resolve_wiki_link("aircraft/n123gf.md", links[0].target), "operators/atlantic-air.md")
        self.assertEqual(resolve_wiki_link("aircraft/n123gf.md", "#facts"), "aircraft/n123gf.md")

    def test_raw_external_and_traversal_links_are_not_wiki_pages(self):
        for target in ("../../raw/source-001.md", "../../../.env", "https://example.com/a.md", "file:///etc/passwd", "/operators/air.md", "//example.com/a.md", "..\\operators\\air.md", "%2e%2e/%2e%2e/raw/source-001.md"):
            with self.subTest(target=target):
                self.assertIsNone(resolve_wiki_link("aircraft/n123gf.md", target))

    def test_physical_symlink_cannot_escape_wiki(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside:
            paths = ProjectPaths.resolve(directory)
            (paths.wiki_dir / "operators").mkdir(parents=True)
            other = Path(outside) / "air.md"
            other.write_text("Private content")
            (paths.wiki_dir / "operators/air.md").symlink_to(other)
            with self.assertRaises(ValueError):
                wiki_file(paths, "operators/air.md")
