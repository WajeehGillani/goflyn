"""Read only a bounded set of compiled wiki pages, then synthesize a grounded answer."""

import re
from collections import deque

from goflight_memory.core.models import PageSelection, QueryResult, WikiPage
from goflight_memory.infra.lock import repository_read_lock
from goflight_memory.infra.paths import ProjectPaths
from goflight_memory.llm.client import LLMClient, LLMError
from goflight_memory.wiki.links import ENTITY_PAGE, extract_links, resolve_wiki_link, wiki_file
from goflight_memory.wiki.naming import normalized, page_name
from goflight_memory.wiki.pages import conflict_section, conflicts_for, parse_page, render_page

MAX_PAGES = 5
MAX_LINK_DEPTH = 2
MAX_PAGE_BYTES = 32_768
MAX_INDEX_BYTES = 65_536
UNKNOWN = "The GoFlight team memory does not currently contain the requested information in the selected wiki pages."


class QueryError(RuntimeError):
    pass


def read_markdown(paths: ProjectPaths, name: str, limit: int = MAX_PAGE_BYTES) -> str:
    # Read one byte beyond the cap to detect oversize files without loading them whole.
    with wiki_file(paths, name).open("rb") as handle:
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise ValueError(f"Wiki page exceeds the query size limit: {name}")
    return content.decode("utf-8")


def page_catalog(index: str) -> dict[str, str]:
    if not index.startswith("# GoFlight Team Memory\n") or any(
        f"## {section}" not in index.splitlines() for section in ("Operators", "Aircraft", "Customers")
    ):
        raise ValueError("Malformed wiki index")
    catalog = {}
    for link in extract_links(index):
        name = resolve_wiki_link("index.md", link.target)
        if name is None or not ENTITY_PAGE.fullmatch(name):
            raise ValueError(f"Invalid entity link in wiki index: {link.target}")
        if not link.label.strip():
            raise ValueError("Empty entity label in wiki index")
        if name in catalog and catalog[name] != link.label:
            raise ValueError("Ambiguous entity label in wiki index")
        catalog[name] = link.label
    return catalog


def exact_matches(question: str, catalog: dict[str, str]) -> list[str]:
    question = normalized(question)
    return [name for name, label in catalog.items()
            if re.search(rf"(?<!\w){re.escape(normalized(label))}(?!\w)", question)]


def relevant_link(question: str, name: str, catalog: dict[str, str]) -> bool:
    """Follow named targets or requested relationship types, not every citation/link."""
    if name in exact_matches(question, {name: catalog[name]}):
        return True
    words = set(re.findall(r"\w+", normalized(question)))
    kinds = set()
    if words & {"aircraft", "fleet", "jets", "fit", "compatible", "suit"}:
        kinds.update({"aircraft", "operators"})
    if words & {"operator", "operators", "operates"}:
        kinds.add("operators")
    if words & {"customer", "customers"}:
        kinds.add("customers")
    return name.split("/", 1)[0] in kinds


def checked_page(name: str, text: str) -> WikiPage:
    for heading in ("## Facts", "## Related entities", "## Conflicts", "## Sources"):
        if text.splitlines().count(heading) != 1:
            raise ValueError(f"Malformed sections in {name}")
    page = parse_page(text)
    if page_name(page.entity) != name:
        raise ValueError(f"Entity identity does not match wiki path: {name}")
    # Check the visible conflict block against facts without reading any raw source.
    if conflict_section(text) != conflict_section(render_page(page, {name: page})):
        raise ValueError(f"Malformed or inconsistent conflict section in {name}")
    return page


def query(question: str, *, paths: ProjectPaths, client: LLMClient,
          max_pages: int = MAX_PAGES, max_link_depth: int = MAX_LINK_DEPTH) -> QueryResult:
    if not question.strip() or len(question) > 4000:
        raise QueryError("Enter a nonempty question of at most 4000 characters")
    if not 1 <= max_pages <= MAX_PAGES or not 0 <= max_link_depth <= MAX_LINK_DEPTH:
        raise QueryError("Query limits must be within five pages and two link hops")
    try:
        with repository_read_lock(paths.memory_path(".write.lock")):
            catalog = page_catalog(read_markdown(paths, "index.md", MAX_INDEX_BYTES))
            if not catalog:
                return QueryResult(answer="The GoFlight team memory does not currently contain any entity pages.", supported=False)
            selected = exact_matches(question, catalog)
            if not selected:
                proposed = client.select_pages(question, catalog, max_pages)
                selection = PageSelection.model_validate(proposed.model_dump() if isinstance(proposed, PageSelection) else proposed)
                selected = list(dict.fromkeys(selection.pages))
            if any(name not in catalog for name in selected):
                raise ValueError("Page selection included a path outside the provided catalog")
            if len(selected) > max_pages:
                raise ValueError("Too many pages selected; narrow the question")
            if not selected:
                return QueryResult(answer="The GoFlight team memory does not currently contain relevant pages for this question.", supported=False)
            queue = deque((name, 0) for name in selected)
            queued = set(selected)
            context: dict[str, str] = {}
            parsed: dict[str, WikiPage] = {}
            while queue and len(context) < max_pages:
                name, depth = queue.popleft()
                text = read_markdown(paths, name)
                parsed[name] = checked_page(name, text)
                if normalized(parsed[name].entity.name) != normalized(catalog[name]):
                    raise ValueError(f"Index label does not match entity page: {name}")
                context[name] = text
                if depth >= max_link_depth:
                    continue
                for link in extract_links(text):
                    target = resolve_wiki_link(name, link.target)
                    if target in catalog and target not in queued and relevant_link(question, target, catalog):
                        queued.add(target)
                        queue.append((target, depth + 1))
        # All page bytes are now in memory; release the reader lock before synthesis.
        proposed = client.answer(question, context)
        result = QueryResult.model_validate(proposed.model_dump() if isinstance(proposed, QueryResult) else proposed)
        if any(name not in context for name in result.pages_used):
            raise ValueError("Answer cited a page that was not supplied as context")
        if result.supported and not result.pages_used:
            raise ValueError("A supported answer must cite its wiki pages")
        cited = list(dict.fromkeys(result.pages_used)) if result.supported else list(context)
        answer = result.answer if result.supported else UNKNOWN
        notes = []
        for name, page in parsed.items():
            for conflict in conflicts_for(page):
                values = list(dict.fromkeys(fact.value for fact in conflict.evidence))
                # Catch a common unsafe failure: asserting only one of the literal values.
                # Semantic grounding still belongs to the LLM; this is not an entailment proof.
                mentioned = [normalized(value) in normalized(answer) for value in values]
                if result.supported and any(mentioned) and not all(mentioned):
                    raise ValueError("Answer mentioned only one side of an unresolved conflict; retry the query")
                notes.append(f"{conflict.entity_name}.{conflict.field}: " + " vs ".join(values) + ".")
                if name not in cited:
                    cited.append(name)
        if notes:
            answer += "\n\nUnresolved conflicts in the consulted wiki pages:\n" + "\n".join(f"- {note}" for note in notes)
            answer += "\nThe memory has no resolved authoritative value for these fields."
        return QueryResult(answer=answer, pages_used=cited, supported=result.supported, has_conflict=bool(notes))
    except (ValueError, OSError, IndexError, LLMError) as error:
        raise QueryError(f"Query failed: {error}") from error
