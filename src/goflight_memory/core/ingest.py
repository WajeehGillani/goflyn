"""One locked transaction: preserve source, extract, compile, write, commit."""

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from goflight_memory.core.extract import extract
from goflight_memory.core.models import Evidence, IngestResult, SourceMetadata
from goflight_memory.core.assertions import explicit_entity
from goflight_memory.infra.git import GitRepository
from goflight_memory.infra.lock import repository_lock
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.infra.sources import next_source_id, read_source, save_source
from goflight_memory.llm.client import LLMClient
from goflight_memory.wiki.compile import load_pages, reconcile
from goflight_memory.wiki.pages import conflicts_for, escape, render_index, render_page


class IngestError(RuntimeError):
    pass


def atomic_write(path: Path, content: bytes) -> None:
    """Replace one complete file; the transaction owns cross-file rollback."""
    descriptor, temporary = tempfile.mkstemp(prefix=".ingest-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def ingest(text: str, contributor: str, *, paths: ProjectPaths, client: LLMClient) -> IngestResult:
    """Dependencies are explicit for isolated tests and alternate checkouts.

    An exact same-contributor/text submission is idempotent. A failed ingest keeps
    its immutable raw source pending, then retries that same source ID on resubmission.
    """
    if not text.strip() or not contributor.strip():
        raise IngestError("A nonempty note and contributor are required")
    contributor = contributor.strip()
    if any(character in contributor for character in "\r\n\0"):
        raise IngestError("Contributor must be a single line")
    paths.memory_path(".write.lock")
    with repository_lock(paths.lock_path):
        return _ingest_locked(text, contributor, paths, client)


def _ingest_locked(text: str, contributor: str, paths: ProjectPaths, client: LLMClient) -> IngestResult:
    git = GitRepository(paths.repository_root)
    sources = {}
    matching = None
    for path in sorted(paths.memory_path("raw").glob("source-*.md")):
        metadata, original = read_source(path)
        sources[metadata.source_id] = metadata
        if metadata.contributor == contributor and original == text:
            matching = (path, metadata)
    pending_path = matching[0] if matching and not git.tracked(matching[0]) else None
    git.preflight(pending_path)
    if matching and pending_path is None:
        return IngestResult(
            source_id=matching[1].source_id,
            git_commit=git.source_commit(matching[0]), already_ingested=True,
        )
    before_head = git.head()
    metadata = matching[1] if matching else SourceMetadata(
        source_id=next_source_id(paths.raw_dir), contributor=contributor,
        source_type="note", created_at=datetime.now(timezone.utc),
    )
    # No wiki modification can precede successful exclusive source creation.
    raw = pending_path or save_source(paths.raw_dir, metadata, text)
    sources[metadata.source_id] = metadata
    originals: dict[Path, bytes | None] = {}
    written: list[Path] = []
    staged: list[Path] = []
    try:
        schema = paths.schema_path.read_text(encoding="utf-8")
        extraction = extract(client, schema, metadata, text)
        pages = load_pages(paths, sources)
        old_names = set(pages)
        assertion = Evidence(source_id=metadata.source_id, contributor=contributor) if explicit_entity(text) else None
        reconcile(pages, extraction, assertion)
        replacements = {
            paths.memory_path(f"wiki/{name}"): render_page(page, pages).encode("utf-8")
            for name, page in sorted(pages.items())
        }
        index = paths.memory_path("wiki/index.md")
        replacements[index] = render_index(pages).encode("utf-8")
        replacements = {path: body for path, body in replacements.items()
                        if not path.exists() or path.read_bytes() != body}
        changed_names = [name for name in pages if paths.memory_path(f"wiki/{name}") in replacements]
        conflicts = [conflict for page in pages.values() for conflict in conflicts_for(page)
                     if conflict.status == "unresolved" and any(f.source_id == metadata.source_id for f in conflict.evidence)]
        changelog = paths.memory_path("wiki/CHANGELOG.md")
        summary = [
            "", f"## {metadata.source_id}", "",
            f"Contributor: {escape(contributor)}", f"Created at: {metadata.created_at.isoformat()}",
            f"Source: [{metadata.source_id}](../raw/{metadata.source_id}.md)", "", "Updated:", "",
        ]
        summary.extend(f"- [{escape(pages[name].entity.name)}]({name})" for name in sorted(changed_names))
        if not changed_names:
            summary.append("- No supported new wiki facts.")
        summary.extend(["", "Changes:", ""])
        summary.append("- Added new facts or supporting evidence; retained previous evidence."
                       if extraction.facts else "- Recorded an explicit entity assertion with source evidence."
                       if assertion else "- Preserved the raw note; no supported facts were extracted.")
        summary.extend(f"- Unresolved conflict: {escape(c.entity_name)}.{escape(c.field)} ({c.conflict_id})." for c in conflicts)
        if not conflicts:
            summary.append("- No unresolved conflicts detected in this source's facts.")
        replacements[changelog] = changelog.read_bytes() + ("\n".join(summary) + "\n").encode("utf-8")
        originals = {path: path.read_bytes() if path.exists() else None for path in replacements}
        for path, content in replacements.items():
            # Record before attempting replacement, including failures after os.replace.
            written.append(path)
            atomic_write(path, content)
        staged = [raw, *replacements]
        message = (
            f"ingest {metadata.source_id} by {contributor}\n\n"
            f"Source: {metadata.source_id}\nContributor: {contributor}\n"
            f"Pages: {', '.join(sorted(changed_names)) or 'none'}\nConflicts: {len(conflicts)}"
        )
        commit = git.commit(staged, message)
        return IngestResult(
            source_id=metadata.source_id,
            created_entities=[pages[name].entity for name in sorted(set(pages) - old_names)],
            updated_entities=[pages[name].entity for name in sorted(set(changed_names) & old_names)],
            pages_changed=[f"memory/wiki/{name}" for name in sorted(changed_names)],
            conflicts=conflicts, git_commit=commit,
        )
    except BaseException as error:
        # If Git advanced before a later error, never undo potentially committed data.
        if git.head() != before_head:
            raise IngestError("Git HEAD changed during ingest; files kept. Inspect history before retry") from error
        try:
            for path in reversed(written):
                previous = originals[path]
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, previous)
            git.unstage(staged)
        except Exception as rollback_error:
            raise IngestError(
                f"Ingest and rollback failed. Stop and inspect memory/Git. Raw source: {metadata.source_id}"
            ) from rollback_error
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise IngestError(
            f"Ingest failed ({type(error).__name__}: {error}). Wiki changes rolled back. "
            f"{metadata.source_id} remains pending; retry the exact note as {contributor}."
        ) from error
