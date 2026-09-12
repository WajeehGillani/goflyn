"""Read known wiki pages, reconcile facts, and render changes entirely in memory."""

from goflight_memory.core.models import Evidence, Extraction, SourceMetadata, WikiFact, WikiPage
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.wiki.naming import normalized, page_name
from goflight_memory.wiki.pages import parse_page, recorded_conflicts, render_index, render_page


def load_pages(paths: ProjectPaths, sources: dict[str, SourceMetadata]) -> dict[str, WikiPage]:
    pages = {}
    originals = {}
    for directory in ("operators", "aircraft", "customers"):
        folder = paths.memory_path(f"wiki/{directory}")
        for file in sorted(folder.glob("*.md")):
            paths.memory_path(f"wiki/{directory}/{file.name}")
            text = file.read_text(encoding="utf-8")
            page = parse_page(text)
            recorded_conflicts(page, text)
            name = page_name(page.entity)
            if name != f"{directory}/{file.name}":
                raise ValueError("Wiki entity name/type does not match its path")
            seen = set()
            for evidence in page.entity_evidence + [e for r in page.resolutions for e in r.reviewed_sources]:
                source = sources.get(evidence.source_id)
                if source is None or source.contributor != evidence.contributor:
                    raise ValueError("Missing or mismatched entity/resolution source attribution")
            for fact in page.facts:
                identity = (fact.field, normalized(fact.value))
                if identity in seen:
                    raise ValueError("Wiki contains duplicate fact rows")
                seen.add(identity)
                for evidence in fact.evidence:
                    source = sources.get(evidence.source_id)
                    if source is None or source.contributor != evidence.contributor:
                        raise ValueError("Wiki evidence has missing or mismatched source attribution")
            pages[name] = page
            originals[name] = text
    for name, page in pages.items():
        if render_page(page, pages) != originals[name]:
            raise ValueError(f"Unsupported manual wiki edits in {name}; preserve/review before ingest")
    index = paths.memory_path("wiki/index.md").read_text(encoding="utf-8")
    if render_index(pages) != index:
        raise ValueError("Index differs from known entity pages; preserve/review before ingest")
    return pages


def reconcile(pages: dict[str, WikiPage], extraction: Extraction, assertion: Evidence | None = None) -> None:
    declared = {(e.entity_type, normalized(e.name)): e for e in extraction.entities}
    used = {(f.entity_type, normalized(f.entity_name)) for f in extraction.facts}
    if assertion is not None:
        used.update(declared)
    for fact in extraction.facts:
        if fact.entity_type == "aircraft" and fact.field == "operator":
            related = ("operator", normalized(fact.value))
            if related in declared:
                used.add(related)
    for key in sorted(used):
        entity = declared[key]
        name = page_name(entity)
        existing = pages.get(name)
        if existing and normalized(existing.entity.name) != normalized(entity.name):
            raise ValueError(f"Entity filename collision at {name}; use an unambiguous name")
        if existing is None:
            pages[name] = WikiPage(entity=entity)
        if assertion is not None and assertion not in pages[name].entity_evidence:
            pages[name].entity_evidence.append(assertion)
    for fact in extraction.facts:
        entity = declared[(fact.entity_type, normalized(fact.entity_name))]
        page = pages[page_name(entity)]
        evidence = Evidence(source_id=fact.source_id, contributor=fact.contributor)
        matching = next((old for old in page.facts if
            old.field == fact.field and normalized(old.value) == normalized(fact.value)), None)
        if matching:
            if evidence not in matching.evidence:
                matching.evidence.append(evidence)
        else:
            page.facts.append(WikiFact(field=fact.field, value=fact.value, evidence=[evidence]))
