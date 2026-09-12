"""Fictional fixtures through production ingest; never reset existing memory."""

import argparse
from collections.abc import Iterator
from pathlib import Path

from pydantic import TypeAdapter
from rich.console import Console

from goflight_memory.agent.chat import show_result
from goflight_memory.core.ingest import IngestError, ingest
from goflight_memory.core.models import DomainModel, IngestResult, NonEmptyText
from goflight_memory.infra.config import load_settings
from goflight_memory.infra.git import GitError, GitRepository
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.llm.client import LLMClient, LLMError
from goflight_memory.wiki.pages import render_index


class DemoSource(DomainModel):
    contributor: NonEmptyText
    text: NonEmptyText


def read_samples() -> list[DemoSource]:
    fixture = ProjectPaths.resolve().repository_root / "samples/demo.json"
    return TypeAdapter(list[DemoSource]).validate_json(fixture.read_text(encoding="utf-8"))


def create_demo_repository(destination: Path, template: ProjectPaths) -> ProjectPaths:
    """Create only a new directory. Never copy secrets or reset a user's checkout."""
    source_git = GitRepository(template.repository_root)
    name, email = source_git.run("config", "user.name"), source_git.run("config", "user.email")
    if not name or not email:
        raise ValueError("Configure git user.name and user.email before creating the demo")
    schema = template.schema_path.read_text(encoding="utf-8")
    # mkdir's exclusive creation also rejects existing empty directories/symlinks.
    destination = destination.expanduser().absolute()
    destination.mkdir()
    paths = ProjectPaths.resolve(destination)
    for folder in ("raw", "wiki/operators", "wiki/aircraft", "wiki/customers"):
        directory = paths.memory_dir / folder
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".gitkeep").touch()
    paths.schema_path.write_text(schema, encoding="utf-8")
    (paths.wiki_dir / "index.md").write_text(render_index({}), encoding="utf-8")
    (paths.wiki_dir / "CHANGELOG.md").write_text("# Memory Changelog\n", encoding="utf-8")
    (paths.repository_root / ".gitignore").write_text(".env\n.env.*\nmemory/.write.lock\n", encoding="utf-8")
    git = GitRepository(paths.repository_root)
    git.run("init", "-q")
    git.run("config", "user.name", name)
    git.run("config", "user.email", email)
    git.run("add", "--", ".gitignore", "schema.md", "memory")
    git.run("commit", "-qm", "chore: initialize isolated demo memory")
    return paths


def load_demo(*, paths: ProjectPaths, client: LLMClient) -> Iterator[IngestResult]:
    for source in read_samples():
        yield ingest(source.text, source.contributor, paths=paths, client=client)


def main() -> int:
    parser = argparse.ArgumentParser(description="Load nine fictional notes through production ingest")
    parser.add_argument("--fresh", type=Path, metavar="NEW_DIRECTORY",
                        help="Create an isolated repository; refuse every existing destination")
    args = parser.parse_args()
    settings = load_settings()
    paths = settings.paths
    console = Console(highlight=False)
    ready = not args.fresh
    try:
        # Missing-key failure must not leave a newly created demo directory behind.
        if args.fresh and not settings.api_key:
            raise LLMError("Set OPENAI_API_KEY before creating a fresh demo")
        if args.fresh:
            paths = create_demo_repository(args.fresh, settings.paths)
            ready = True
        console.print(f"Fictional demo memory: {paths.repository_root}", markup=False)
        console.print("New notes use the configured LLM; committed exact retries need no API call.")
        for result in load_demo(paths=paths, client=LLMClient(settings.api_key, settings.model)):
            show_result(console, result)
        console.print("Demo loaded. Start goflight-memory --user Jack with GOFLIGHT_ROOT set to this directory.")
        return 0
    except (IngestError, LLMError, GitError, OSError, ValueError) as error:
        console.print(f"Demo failed: {error}\nNo existing memory was reset.", markup=False, style="red")
        if ready:
            console.print(f"Fix the cause and rerun without --fresh, using GOFLIGHT_ROOT={paths.repository_root}."
                          "\nProvide OPENAI_API_KEY again if needed. Exact retries reuse preserved sources.", markup=False)
        else:
            console.print("Setup did not finish. Inspect the requested destination before trying a new directory.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
