"""Read-only conversational shell; memory operations are not connected yet."""

from rich.console import Console

from goflight_memory.agent.prompts import HELP, NOT_IMPLEMENTED, WELCOME
from goflight_memory.infra.config import Settings
from goflight_memory.infra.paths import ProjectPaths


def show_status(console: Console, contributor: str, paths: ProjectPaths) -> None:
    # Raw files exclude hidden placeholders; define a record format in Milestone 2.
    source_count = sum(
        path.is_file() and not any(part.startswith(".") for part in path.relative_to(paths.raw_dir).parts)
        for path in paths.raw_dir.rglob("*")
    )
    page_count = sum(path.is_file() for path in paths.wiki_dir.rglob("*.md"))
    console.print(
        f"Contributor: {contributor}\n"
        f"Raw sources: {source_count}\n"
        f"Wiki Markdown pages: {page_count} (includes index and changelog)\n"
        f"Project root: {paths.repository_root}\n"
        f"Memory root: {paths.memory_dir}",
        markup=False,
        highlight=False,
    )


def run_chat(settings: Settings) -> None:
    console = Console(highlight=False)
    console.print("GoFlight Team Memory", style="bold cyan")
    console.print(WELCOME)
    try:
        contributor = settings.contributor
        while not contributor:
            contributor = console.input("Contributor name › ").strip()
            if not contributor:
                console.print("Please enter a contributor name.")

        console.print(f"\nContributor: {contributor}", markup=False)
        console.print("Type naturally or /help.\n")

        while True:
            message = console.input("[bold]You › [/bold]").strip()
            if not message:
                continue
            if message == "/exit":
                break
            if message == "/help":
                console.print(HELP, markup=False)
            elif message == "/status":
                show_status(console, contributor, settings.paths)
            elif message.startswith("/"):
                console.print("Unknown command. Type /help for available commands.")
            else:
                console.print(f"Memory › {NOT_IMPLEMENTED}")
            console.print()
    except (EOFError, KeyboardInterrupt):
        console.print()
    console.print("Goodbye.")
