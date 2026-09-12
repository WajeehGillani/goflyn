"""Conversational notes invoke the same explicit ingest API as /add."""

from rich.console import Console
from rich.text import Text

from goflight_memory.agent.prompts import HELP, WELCOME
from goflight_memory.agent.router import route
from goflight_memory.core.ingest import IngestError, ingest
from goflight_memory.core.models import IngestResult, Intent, QueryResult
from goflight_memory.core.query import QueryError, query
from goflight_memory.infra.config import Settings
from goflight_memory.infra.git import GitError
from goflight_memory.infra.lock import repository_lock
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.llm.client import LLMClient, LLMError


def show_status(console: Console, contributor: str, paths: ProjectPaths) -> None:
    with repository_lock(paths.memory_path(".write.lock")):
        source_count = sum(path.is_file() for path in paths.memory_path("raw").glob("source-*.md"))
        pages = [file for directory in ("operators", "aircraft", "customers")
                 for file in paths.memory_path(f"wiki/{directory}").glob("*.md")]
        conflicts = sum(file.read_text(encoding="utf-8").splitlines().count("Status: unresolved") for file in pages)
    console.print(
        f"Contributor: {contributor}\n"
        f"Raw sources: {source_count}\n"
        f"Wiki entity pages: {len(pages)}\n"
        f"Unresolved conflicts: {conflicts}\n"
        f"Project root: {paths.repository_root}\n"
        f"Memory root: {paths.memory_dir}",
        markup=False,
        highlight=False,
    )


def show_result(console: Console, result: IngestResult) -> None:
    if result.already_ingested:
        console.print(f"Memory › Already ingested as {result.source_id}; no duplicate created.", markup=False)
    else:
        console.print(f"Memory › Added as {result.source_id}.")
        for entity in result.created_entities + result.updated_entities:
            console.print(f"• {entity.name}", markup=False)
        console.print(f"{len(result.conflicts)} unresolved conflicts detected:")
        for conflict in result.conflicts:
            console.print(f"• {conflict.entity_name}.{conflict.field}", markup=False)
    console.print(f"Git commit: {result.git_commit[:7]}")


def show_query(console: Console, result: QueryResult, paths: ProjectPaths) -> None:
    console.print(f"Memory › {result.answer}", markup=False)
    if result.pages_used:
        console.print("\nPages used:")
        for name in result.pages_used:
            uri = paths.memory_path(f"wiki/{name}").as_uri()
            console.print(Text.assemble("• ", (name, f"link {uri}")))


def run_chat(settings: Settings) -> None:
    console = Console(highlight=False)
    console.print("GoFlight Team Memory", style="bold cyan")
    console.print(WELCOME)
    client = LLMClient(settings.api_key, settings.model)
    try:
        contributor = settings.contributor
        while not contributor:
            contributor = console.input("Contributor name › ").strip()
            if not contributor:
                console.print("Please enter a contributor name.")

        console.print(f"\nContributor: {contributor}", markup=False)
        console.print("Type naturally or /help.\n")

        while True:
            message = console.input("[bold]You › [/bold]")
            command = message.strip()
            if not command:
                continue
            if command == "/exit":
                break
            try:
                if command == "/help":
                    console.print(HELP, markup=False)
                elif command == "/status":
                    show_status(console, contributor, settings.paths)
                elif command == "/add":
                    note = console.input("Note › ")
                    show_result(console, ingest(note, contributor, paths=settings.paths, client=client))
                elif command.startswith("/"):
                    console.print("Unknown command. Type /help for available commands.")
                else:
                    decision = route(message, client)
                    if decision.intent == Intent.QUERY:
                        show_query(console, query(message, paths=settings.paths, client=client), settings.paths)
                    elif decision.intent == Intent.LINT:
                        console.print("Memory › Lint support will be implemented in Milestone 4.")
                    elif decision.intent == Intent.INGEST and decision.confidence >= 0.7:
                        show_result(console, ingest(message, contributor, paths=settings.paths, client=client))
                    else:
                        console.print("Memory › I can save operational notes and answer questions from the wiki. Type /help for commands.")
            except (IngestError, QueryError, LLMError, GitError, OSError, ValueError) as error:
                console.print(f"Memory › {error}", markup=False, style="red")
            console.print()
    except (EOFError, KeyboardInterrupt):
        console.print()
    console.print("Goodbye.")
