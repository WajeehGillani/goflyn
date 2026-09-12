"""Inline links in the generated Markdown dialect; no filesystem browsing."""

import html
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from goflight_memory.infra.paths import ProjectPaths

ENTITY_PAGE = re.compile(r"(?:operators|aircraft|customers)/[a-z0-9]+(?:-[a-z0-9]+)*\.md")
INLINE_LINK = re.compile(r"(?<!!)\[([^\]\n]+)\]\(([^\s)]+)\)")


@dataclass(frozen=True)
class MarkdownLink:
    label: str
    target: str


def extract_links(markdown: str) -> list[MarkdownLink]:
    """Supports the inline, untitled links emitted by ingestion, not full CommonMark."""
    return [MarkdownLink(html.unescape(match[1]), match[2]) for match in INLINE_LINK.finditer(markdown)]


def is_valid_wiki_page(name: str) -> bool:
    return name in {"index.md", "CHANGELOG.md"} or bool(ENTITY_PAGE.fullmatch(name))


def resolve_wiki_link(current_page: str, target: str) -> str | None:
    """Return a canonical wiki-relative path; ignore external/raw/escaping links."""
    if not is_valid_wiki_page(current_page):
        raise ValueError("Invalid originating wiki page")
    target = unquote(html.unescape(target))
    if "\\" in target or any(ord(character) < 32 for character in target):
        return None
    try:
        url = urlsplit(target)
    except ValueError:
        return None
    if url.scheme or url.netloc or url.query or url.path.startswith("/"):
        return None
    name = posixpath.normpath(posixpath.join(posixpath.dirname(current_page), url.path)) if url.path else current_page
    return name if is_valid_wiki_page(name) else None


def wiki_file(paths: ProjectPaths, name: str) -> Path:
    """Validate the logical name and physical path, including every symlink parent."""
    if not is_valid_wiki_page(name):
        raise ValueError(f"Not a permitted wiki page: {name}")
    path = paths.memory_path(f"wiki/{name}")
    if not path.is_file():
        raise ValueError(f"Wiki page is missing: {name}")
    return path
