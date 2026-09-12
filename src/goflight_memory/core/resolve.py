"""Explicit human decisions; no LLM may invoke or select a resolution here."""

import hashlib
import re
from datetime import datetime, timezone

from goflight_memory.core.ingest import atomic_write
from goflight_memory.core.models import Conflict, Evidence, Resolution, ResolveResult
from goflight_memory.infra.git import GitRepository
from goflight_memory.infra.lock import repository_lock, repository_read_lock
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.infra.sources import read_source
from goflight_memory.wiki.compile import load_pages
from goflight_memory.wiki.links import wiki_file
from goflight_memory.wiki.pages import conflicts_for, escape, parse_page, recorded_conflicts, render_page


class ResolveError(RuntimeError):
    pass


def conflict_revision(conflict: Conflict) -> str:
    return hashlib.sha256(conflict.model_dump_json().encode()).hexdigest()


def list_conflicts(*, paths: ProjectPaths) -> list[tuple[str, Conflict]]:
    """Read-only listing; callers retain IDs/revisions for short-lived confirmation."""
    result = []
    with repository_read_lock(paths.memory_path(".write.lock")):
        for directory in ("operators", "aircraft", "customers"):
            for file in sorted(paths.memory_path(f"wiki/{directory}").glob("*.md")):
                name = f"{directory}/{file.name}"
                text = wiki_file(paths, name).read_text(encoding="utf-8")
                page = parse_page(text)
                result.extend((name, c) for c in recorded_conflicts(page, text) if c.status == "unresolved")
    return sorted(result, key=lambda item: (item[0], item[1].conflict_id))


def resolve_conflict(conflict_id: str, resolution: str, reviewer: str, reason: str, *,
                     paths: ProjectPaths, expected_revision: str | None = None) -> ResolveResult:
    """The caller must be the identified human entry point, after explicit confirmation.

    The core API is an explicit write command, not an LLM tool. Authentication is
    intentionally out of scope; the reviewer is an accountable local-session label.
    """
    if not re.fullmatch(r"conflict-[0-9a-f]{16}", conflict_id):
        raise ResolveError("Invalid conflict ID")
    if any(not text.strip() or len(text) > 4000 for text in (resolution, reviewer, reason)):
        raise ResolveError("A nonempty resolution, reviewer, and reason are required (up to 4000 characters each)")
    if any(c in reviewer for c in "\r\n\0"):
        raise ResolveError("Reviewer must be a single line")
    with repository_lock(paths.memory_path(".write.lock")):
        git = GitRepository(paths.repository_root)
        git.preflight()
        sources = {metadata.source_id: metadata for file in sorted(paths.memory_path("raw").glob("source-*.md"))
                   for metadata, _ in [read_source(file)]}
        pages = load_pages(paths, sources)
        matches = [(name, page, c) for name, page in pages.items() for c in conflicts_for(page)
                   if c.conflict_id == conflict_id]
        if len(matches) != 1:
            raise ResolveError("Conflict not found or ambiguous; list conflicts again")
        name, page, conflict = matches[0]
        if conflict.status != "unresolved":
            raise ResolveError("Conflict is already resolved; no changes made")
        if expected_revision is not None and expected_revision != conflict_revision(conflict):
            raise ResolveError("Conflict evidence changed since review; list it again and reconfirm")
        decision = Resolution(
            conflict_id=conflict_id, value=resolution, reviewer=reviewer, reason=reason,
            resolved_at=datetime.now(timezone.utc),
            reviewed_values=list(dict.fromkeys(f.value for f in conflict.evidence)),
            reviewed_sources=[Evidence(source_id=s, contributor=c) for s, c in sorted({
                (f.source_id, f.contributor) for f in conflict.evidence
            })],
        )
        page.resolutions.append(decision)
        target = paths.memory_path(f"wiki/{name}")
        changelog = paths.memory_path("wiki/CHANGELOG.md")
        entry = ["", f"## Conflict Resolution — {conflict_id}", "",
                 f"Entity: [{escape(conflict.entity_name)}]({name})", f"Field: {escape(conflict.field)}",
                 f"Resolution: {escape(decision.value)}", f"Resolved by: {escape(decision.reviewer)}",
                 f"Reason: {escape(decision.reason)}", f"Resolved at: {decision.resolved_at.isoformat()}",
                 "", "Evidence reviewed:", ""]
        entry.extend(f"- [{e.source_id}](../raw/{e.source_id}.md) — {escape(e.contributor)}"
                     for e in decision.reviewed_sources)
        originals = {target: target.read_bytes(), changelog: changelog.read_bytes()}
        replacements = {target: render_page(page, pages).encode(),
                        changelog: originals[changelog] + ("\n".join(entry) + "\n").encode()}
        before = git.head()
        written = []
        try:
            for path, content in replacements.items():
                written.append(path)
                atomic_write(path, content)
            commit = git.commit(list(replacements),
                                f"resolve {conflict_id} by {decision.reviewer}\n\n"
                                f"Entity: {conflict.entity_name}\nField: {conflict.field}\n"
                                f"Resolution: {decision.value}\nReason: {decision.reason}")
        except BaseException as error:
            if git.head() != before:
                raise ResolveError("Git HEAD changed during resolution; inspect history before retrying") from error
            try:
                for path in reversed(written):
                    atomic_write(path, originals[path])
                git.unstage(list(replacements))
            except Exception as rollback_error:
                raise ResolveError("Resolution rollback failed; stop and inspect memory/Git") from rollback_error
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise ResolveError("Resolution failed; wiki and changelog changes rolled back") from error
        resolved = next(c for c in conflicts_for(page) if c.conflict_id == conflict_id)
        return ResolveResult(conflict=resolved, page=name, git_commit=commit)
