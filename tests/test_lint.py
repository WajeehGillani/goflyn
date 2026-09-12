import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from rich.console import Console

from goflight_memory.agent.chat import run_chat, show_lint
from goflight_memory.agent.router import route
from goflight_memory.core.lint import LintError, lint
from goflight_memory.core.models import Entity, Evidence, Intent, LintReport, WikiFact, WikiPage
from goflight_memory.infra.config import Settings
from goflight_memory.infra.git import GitRepository
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.wiki.links import resolve_wiki_link
from goflight_memory.wiki.naming import page_name
from goflight_memory.wiki.pages import render_index, render_page


HEALTH_REQUESTS = [
    "Check the memory for problems.", "Is the wiki healthy?",
    "Are there any contradictions?", "Find problems in the team memory.",
    "Show unresolved conflicts.",
]


class LintTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.paths = ProjectPaths.resolve(temporary.name)
        self.paths.raw_dir.mkdir(parents=True)
        for source in ("source-001", "source-002"):
            (self.paths.raw_dir / f"{source}.md").write_text("Raw source fixture\n")
        self.operator = WikiPage(entity=Entity(entity_type="operator", name="Atlantic Air"), facts=[
            WikiFact(field="minimum_booking_notice", value=value,
                     evidence=[Evidence(source_id=source, contributor=contributor)])
            for value, source, contributor in (("24 hours", "source-001", "John"),
                                                ("48 hours", "source-002", "Sarah"))
        ])
        self.aircraft = WikiPage(entity=Entity(entity_type="aircraft", name="N123GF"))
        self.customer = WikiPage(entity=Entity(entity_type="customer", name="Acme Corp"))
        self.pages = {page_name(page.entity): page for page in (self.operator, self.aircraft, self.customer)}
        for name, page in self.pages.items():
            self.write(name, render_page(page, self.pages))
        self.write("index.md", render_index(self.pages))
        self.write("CHANGELOG.md", "# Memory Changelog\n")

    def write(self, name, text):
        path = self.paths.wiki_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def append(self, name, text):
        path = self.paths.wiki_dir / name
        self.write(name, path.read_text() + "\n" + text + "\n")

    def issues(self, kind):
        return [issue for issue in lint(paths=self.paths).issues if issue.type == kind]

    def test_unresolved_conflict_and_attribution(self):
        report = lint(paths=self.paths)
        self.assertEqual(report.pages_scanned, 5)
        self.assertEqual(report.unresolved_conflicts, 1)
        issue = report.issues[0]
        self.assertEqual(issue.page, "operators/atlantic-air.md")
        self.assertEqual(issue.severity, "warning")
        for detail in ("minimum_booking_notice", "24 hours", "48 hours", "source-001", "source-002", "John", "Sarah", "unresolved"):
            self.assertIn(detail, issue.message)
        self.assertEqual(report.issue_count, 1)
        self.assertFalse(report.is_clean)

    def test_resolved_historical_record_is_not_unresolved(self):
        name = "operators/atlantic-air.md"
        self.write(name, (self.paths.wiki_dir / name).read_text().replace("Status: unresolved", "Status: resolved"))
        report = lint(paths=self.paths)
        self.assertTrue(report.is_clean)
        self.assertEqual(report.unresolved_conflicts, 0)
        self.assertEqual(report.model_dump()["issue_count"], 0)

    def test_missing_record_is_malformed_not_inferred_contradiction(self):
        name = "operators/atlantic-air.md"
        text = (self.paths.wiki_dir / name).read_text()
        prefix, remainder = text.split("## Conflicts\n", 1)
        self.write(name, prefix + "## Conflicts\n\nNo unresolved conflicts.\n\n## Sources\n" + remainder.split("## Sources\n", 1)[1])
        self.assertEqual(len(self.issues("CONTRADICTION")), 0)
        self.assertEqual(len(self.issues("MALFORMED_PAGE")), 1)

    def test_mixed_recorded_statuses_on_one_page(self):
        self.operator.facts.extend([
            WikiFact(field="operating_notes", value=value,
                     evidence=[Evidence(source_id="source-001", contributor="John")])
            for value in ("Old policy", "New policy")
        ])
        text = render_page(self.operator, self.pages)
        self.write("operators/atlantic-air.md", text.replace("Status: unresolved", "Status: resolved", 1))
        report = lint(paths=self.paths)
        self.assertEqual(report.unresolved_conflicts, 1)
        self.assertEqual(report.issue_count, 1)
        self.assertIn("operating_notes", report.issues[0].message)

    def test_invalid_recorded_status_is_malformed(self):
        name = "operators/atlantic-air.md"
        self.write(name, (self.paths.wiki_dir / name).read_text().replace("Status: unresolved", "Status: unknown"))
        self.assertEqual(len(self.issues("MALFORMED_PAGE")), 1)
        self.assertEqual(len(self.issues("CONTRADICTION")), 0)

    def test_evidence_parser_requires_literal_parent_directories(self):
        name = "operators/atlantic-air.md"
        self.write(name, (self.paths.wiki_dir / name).read_text().replace("../../raw/", "aa/bb/raw/"))
        self.assertEqual(len(self.issues("MALFORMED_PAGE")), 1)
        self.assertGreater(len(self.issues("BROKEN_LINK")), 0)

    def test_index_only_incoming_is_not_orphan_and_infrastructure_excluded(self):
        self.assertEqual(self.issues("ORPHAN_PAGE"), [])
        self.write("index.md", "# Index\n")
        orphans = {issue.page for issue in self.issues("ORPHAN_PAGE")}
        self.assertEqual(orphans, set(self.pages))

    def test_truly_unreferenced_entity_is_orphan(self):
        page = WikiPage(entity=Entity(entity_type="customer", name="Orphan Demo"))
        self.write("customers/orphan-demo.md", render_page(page, {}))
        self.assertEqual([issue.page for issue in self.issues("ORPHAN_PAGE")], ["customers/orphan-demo.md"])

    def test_changelog_and_documentation_links_count(self):
        self.write("index.md", "# Index\n")
        self.append("CHANGELOG.md", "[Aircraft](aircraft/n123gf.md)")
        self.write("docs/guide.md", "[Operator](../operators/atlantic-air.md)\n[Customer](../customers/acme-corp.md)")
        self.assertEqual(self.issues("ORPHAN_PAGE"), [])
        self.assertEqual(self.issues("BROKEN_LINK"), [])

    def test_self_link_does_not_hide_orphan(self):
        self.write("index.md", "# Index\n")
        self.append("customers/acme-corp.md", "[Self](#facts)")
        self.assertIn("customers/acme-corp.md", {issue.page for issue in self.issues("ORPHAN_PAGE")})

    def test_relative_links_from_all_entity_directories_use_shared_resolver(self):
        for name in self.pages:
            self.append(name, "[Aircraft](../aircraft/n123gf.md#facts)")
            self.assertEqual(resolve_wiki_link(name, "../aircraft/n123gf.md#facts"), "aircraft/n123gf.md")
        self.assertEqual(self.issues("BROKEN_LINK"), [])

    def test_broken_target_reported_once_per_page_target(self):
        self.append("aircraft/n123gf.md", "[Missing](../operators/missing.md) [Again](../operators/missing.md)")
        issues = self.issues("BROKEN_LINK")
        self.assertEqual(len(issues), 1)
        self.assertIn("../operators/missing.md", issues[0].message)
        self.assertIn("missing", issues[0].message)

    def test_raw_source_links_do_not_count_as_wiki_edges(self):
        self.write("index.md", "[Acme Corp](../raw/source-001.md)")
        self.assertEqual(len(self.issues("ORPHAN_PAGE")), 3)
        self.assertEqual(self.issues("BROKEN_LINK"), [])

    def test_existing_sources_pass_and_raw_contents_are_not_read(self):
        original = Path.open
        def guarded(path, *args, **kwargs):
            self.assertNotIn("raw", path.parts)
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            self.assertEqual(self.issues("MISSING_SOURCE"), [])

    def test_missing_linked_and_bare_sources_deduplicated_per_page(self):
        self.append("customers/acme-corp.md", "source-007 [source-007](../../raw/source-007.md) source-008")
        report = lint(paths=self.paths)
        self.assertEqual(report.missing_sources, 2)
        self.assertEqual(report.broken_links, 0)
        self.assertIn("memory/raw/source-007.md", str(report.issues))

    def test_encoded_source_link_and_missing_raw_directory(self):
        self.append("customers/acme-corp.md", "[Evidence](../../raw/%73ource-009.md)")
        self.assertIn("source-009", str(self.issues("MISSING_SOURCE")))
        self.paths.raw_dir.rename(self.paths.memory_dir / "raw-backup")
        self.assertEqual(len(self.issues("MISSING_SOURCE")), 3)

    def test_invalid_source_reference_and_raw_path(self):
        self.append("customers/acme-corp.md", "source-7 [Evidence](../../raw/arbitrary.md)")
        self.assertEqual(len(self.issues("INVALID_SOURCE")), 2)

    def test_external_links_ignored_and_escaping_links_rejected(self):
        self.append("customers/acme-corp.md", "[Web](https://example.com/a.md) [Mail](mailto:a@example.com)")
        self.assertEqual(self.issues("BROKEN_LINK"), [])
        for target in ("../../../.env", "%2e%2e/%2e%2e/%2e%2e/.env", "/etc/passwd", "..\\secret.md", "../aircraft/n123gf.md?bad=1"):
            self.append("customers/acme-corp.md", f"[Unsafe]({target})")
        self.assertEqual(len(self.issues("BROKEN_LINK")), 5)

    def test_symlink_page_and_directory_never_read(self):
        outside = self.paths.repository_root / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("source-999")
        (self.paths.wiki_dir / "customers/unsafe.md").symlink_to(outside / "secret.md")
        (self.paths.wiki_dir / "unsafe").symlink_to(outside, target_is_directory=True)
        self.append("index.md", "[Unsafe](customers/unsafe.md)")
        report = lint(paths=self.paths)
        self.assertEqual(report.counts_by_type["READ_ERROR"], 1)
        self.assertEqual(report.counts_by_type["SCAN_ERROR"], 1)
        self.assertEqual(report.broken_links, 1)
        self.assertEqual(report.missing_sources, 0)

    def test_symlink_raw_source_not_accepted(self):
        (self.paths.raw_dir / "source-009.md").symlink_to(self.paths.wiki_dir / "index.md")
        self.append("index.md", "source-009")
        self.assertEqual(len(self.issues("MISSING_SOURCE")), 1)

    def test_malformed_and_unreadable_pages_do_not_stop_scan(self):
        self.write("customers/acme-corp.md", "# Broken page\n[source-009](../../raw/source-009.md)\n")
        (self.paths.wiki_dir / "aircraft/n123gf.md").write_bytes(b"\xff")
        report = lint(paths=self.paths)
        self.assertEqual(report.unresolved_conflicts, 1)
        self.assertEqual(report.counts_by_type["MALFORMED_PAGE"], 1)
        self.assertEqual(report.counts_by_type["READ_ERROR"], 1)
        self.assertEqual(report.missing_sources, 1)

    def test_permission_failure_becomes_issue(self):
        original = Path.read_text
        def unreadable(path, *args, **kwargs):
            if path.name == "acme-corp.md":
                raise PermissionError("permission denied")
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", unreadable):
            self.assertEqual(len(self.issues("READ_ERROR")), 1)

    def test_missing_wiki_directory_and_no_lock_created(self):
        with TemporaryDirectory() as directory:
            paths = ProjectPaths.resolve(directory)
            report = lint(paths=paths)
            self.assertFalse(report.is_clean)
            self.assertEqual(report.pages_scanned, 0)
            self.assertEqual(report.counts_by_type, {"SCAN_ERROR": 1})
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_symlink_wiki_root_is_execution_failure(self):
        with TemporaryDirectory() as directory:
            paths = ProjectPaths.resolve(directory)
            paths.memory_dir.mkdir()
            paths.wiki_dir.symlink_to(self.paths.wiki_dir, target_is_directory=True)
            with self.assertRaisesRegex(LintError, "Symlinks"):
                lint(paths=paths)

    def test_lint_is_deterministic_and_read_only_with_no_git_calls(self):
        git = GitRepository(self.paths.repository_root)
        git.run("init", "-q")
        git.run("config", "user.name", "Test")
        git.run("config", "user.email", "test@example.invalid")
        git.run("config", "commit.gpgsign", "false")
        git.run("add", ".")
        git.run("commit", "-qm", "fixture")
        def snapshot():
            return {path.relative_to(self.paths.repository_root): (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in self.paths.repository_root.rglob("*") if path.is_file()}
        head, before = git.head(), snapshot()
        with patch.object(GitRepository, "run", side_effect=AssertionError("Lint called Git")):
            first = lint(paths=self.paths)
            self.assertEqual(lint(paths=self.paths), first)
        self.assertEqual(snapshot(), before)
        self.assertEqual(git.head(), head)
        self.assertEqual(git.run("status", "--porcelain"), "")
        self.assertFalse(self.paths.lock_path.exists())

    def test_natural_requests_need_no_provider(self):
        client = Mock()
        client.classify.side_effect = AssertionError("Unexpected provider call")
        for request in HEALTH_REQUESTS:
            self.assertEqual(route(request, client).intent, Intent.LINT)
        client.classify.assert_not_called()

    def test_slash_and_conversation_call_same_core_and_repl_continues(self):
        output = io.StringIO()
        console = Console(file=output, width=120, color_system=None)
        settings = Settings(paths=self.paths, contributor="Wajeeh", api_key="")
        with patch("goflight_memory.agent.chat.Console", return_value=console), \
             patch.object(console, "input", side_effect=[*HEALTH_REQUESTS, "/lint", "/help", "/exit"]), \
             patch("goflight_memory.agent.chat.lint", wraps=lint) as operation, \
             patch("goflight_memory.llm.client.LLMClient.classify", side_effect=AssertionError("LLM called")):
            run_chat(settings)
        self.assertEqual(operation.call_count, 6)
        self.assertTrue(all(call.kwargs == {"paths": self.paths} for call in operation.call_args_list))
        self.assertEqual(output.getvalue().count("Contradictions: 1"), 6)
        self.assertEqual(output.getvalue().count("minimum_booking_notice"), 6)
        self.assertIn("Goodbye.", output.getvalue())

    def test_cli_recovers_from_lint_failure(self):
        output = io.StringIO()
        console = Console(file=output)
        with patch("goflight_memory.agent.chat.Console", return_value=console), \
             patch.object(console, "input", side_effect=["/lint", "/help", "/exit"]), \
             patch("goflight_memory.agent.chat.lint", side_effect=LintError("Cannot scan")):
            run_chat(Settings(paths=self.paths, contributor="Wajeeh"))
        self.assertIn("Cannot scan", output.getvalue())
        self.assertIn("Goodbye.", output.getvalue())

    def test_clean_display_and_derived_counts(self):
        report = LintReport(pages_scanned=5)
        output = io.StringIO()
        show_lint(Console(file=output, color_system=None), report)
        self.assertIn("Wiki health check passed.", output.getvalue())
        self.assertEqual(report.model_dump()["orphan_pages"], 0)


if __name__ == "__main__":
    unittest.main()
