"""Read-only, deterministic diagnostics of persisted Markdown and reference targets."""

import html
import os
import re
from pathlib import Path

from goflight_memory.core.models import LintIssue, LintReport
from goflight_memory.infra.lock import repository_read_lock
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.infra.sources import SOURCE_ID, source_path
from goflight_memory.wiki.links import (
    extract_links, is_external_link, resolve_local_link,
    resolve_wiki_link, wiki_file,
)
from goflight_memory.wiki.naming import page_name
from goflight_memory.wiki.pages import parse_page, recorded_conflicts

SOURCE_REFERENCE = re.compile(r"(?<![\w-])source-[\w-]+")
ENTITY_DIRECTORIES = {"operators", "aircraft", "customers"}


class LintError(RuntimeError):
    pass


def lint(*, paths: ProjectPaths) -> LintReport:
    """Scan under a cooperating read lock without creating even the lock file."""
    try:
        with repository_read_lock(paths.memory_path(".write.lock")):
            return scan_wiki(paths)
    except (OSError, ValueError) as error:
        raise LintError(f"Unable to check wiki health: {error}") from error


def scan_wiki(paths: ProjectPaths) -> LintReport:
    issues: list[LintIssue] = []

    def issue(kind: str, page: str, message: str, severity: str = "error") -> None:
        issues.append(LintIssue(type=kind, page=page, message=message, severity=severity))

    root = paths.memory_path("wiki")
    if not root.is_dir():
        issue("SCAN_ERROR", "wiki", "Wiki directory is missing: memory/wiki")
        return LintReport(pages_scanned=0, issues=issues)

    names: set[str] = set()

    def walk_error(error: OSError) -> None:
        issue("SCAN_ERROR", "wiki", f"Cannot scan directory: {error}")

    # Do not traverse symlink directories, including links back inside the wiki.
    for directory, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
        for child in sorted(directories[:]):
            path = Path(directory) / child
            if path.is_symlink():
                directories.remove(child)
                issue("SCAN_ERROR", path.relative_to(root).as_posix(), "Symlink directory was not scanned")
        directories.sort()
        names.update((Path(directory) / file).relative_to(root).as_posix()
                     for file in files if file.endswith(".md"))

    incoming: dict[str, set[str]] = {name: set() for name in names}
    entities = {name for name in names if name.split("/", 1)[0] in ENTITY_DIRECTORIES}
    for name in sorted(names):
        try:
            text = wiki_file(paths, name).read_text(encoding="utf-8")
        except (OSError, ValueError) as error:
            issue("READ_ERROR", name, f"Cannot read wiki page: {error}")
            continue

        if name in entities:
            try:
                page = parse_page(text)
                if page_name(page.entity) != name:
                    raise ValueError("Entity identity does not match its wiki path")
                for conflict in recorded_conflicts(page, text):
                    if conflict.status == "unresolved":
                        details = "\n".join(f"  {fact.value} — {fact.source_id} ({fact.contributor})"
                                            for fact in conflict.evidence)
                        issue("CONTRADICTION", name,
                              f"Field: {conflict.field}\nStatus: unresolved ({conflict.conflict_id})\n{details}",
                              "warning")
            except (ValueError, IndexError, KeyError) as error:
                issue("MALFORMED_PAGE", name, f"Cannot validate structured page: {error}")

        references = set(SOURCE_REFERENCE.findall(html.unescape(text)))
        for target in sorted({link.target for link in extract_links(text)}):
            if is_external_link(target):
                continue
            local = resolve_local_link(name, target)
            if local is not None and local.startswith("../raw/"):
                source = local.removeprefix("../raw/").removesuffix(".md")
                if local != f"../raw/{source}.md" or not SOURCE_ID.fullmatch(source):
                    issue("INVALID_SOURCE", name, f"Invalid raw-source link: {target}")
                else:
                    references.add(source)
                continue
            resolved = resolve_wiki_link(name, target)
            if resolved is None:
                issue("BROKEN_LINK", name, f"Target: {target}; not a safe internal wiki Markdown path")
                continue
            try:
                wiki_file(paths, resolved)
                if resolved != name and resolved in incoming:
                    incoming[resolved].add(name)
            except (OSError, ValueError) as error:
                issue("BROKEN_LINK", name, f"Target: {target}; {error}")

        for source in sorted(references):
            if not SOURCE_ID.fullmatch(source):
                issue("INVALID_SOURCE", name, f"Invalid source reference: {source}")
                continue
            try:
                raw = source_path(paths.memory_path("raw"), source)
                if not raw.is_file():
                    raise ValueError("file does not exist")
            except (OSError, ValueError) as error:
                issue("MISSING_SOURCE", name,
                      f"Source: {source}; expected memory/raw/{source}.md; {error}")

    for name in sorted(entities):
        if not incoming[name]:
            issue("ORPHAN_PAGE", name, "No incoming link from another wiki page (including index.md)", "warning")
    return LintReport(pages_scanned=len(names),
                      issues=sorted(issues, key=lambda item: (item.type, item.page, item.message)))
