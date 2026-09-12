"""A small, strict Markdown table format; Markdown remains the source of wiki state."""

import hashlib
import html
import re
from collections import defaultdict

from goflight_memory.core.models import Conflict, Entity, Evidence, Fact, WikiFact, WikiPage
from goflight_memory.wiki.naming import normalized, page_name

TABLE_HEADER = "| Field | Value | Evidence |\n| --- | --- | --- |"
EVIDENCE = re.compile(r"\[(source-[0-9]{3,})\]\(../../raw/\1\.md\) — (.+)")


def escape(value: str) -> str:
    value = html.escape(value, quote=False)
    # Encode Markdown punctuation and newlines, including the table separator.
    return re.sub(r"[\\`*_{}\[\]()#+.!|\r\n-]", lambda m: f"&#{ord(m[0])};", value)


def evidence_text(evidence: list[Evidence]) -> str:
    return "<br>".join(
        f"[{item.source_id}](../../raw/{item.source_id}.md) — {escape(item.contributor)}"
        for item in sorted(evidence, key=lambda item: (item.source_id, item.contributor))
    )


def conflicts_for(page: WikiPage) -> list[Conflict]:
    fields: dict[str, list[WikiFact]] = defaultdict(list)
    for fact in page.facts:
        fields[fact.field].append(fact)
    conflicts = []
    for field, facts in sorted(fields.items()):
        if len({normalized(fact.value) for fact in facts}) < 2:
            continue
        identity = f"{page.entity.entity_type}:{normalized(page.entity.name)}:{field}"
        conflict_id = "conflict-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
        conflicts.append(Conflict(
            conflict_id=conflict_id,
            entity_type=page.entity.entity_type,
            entity_name=page.entity.name,
            field=field,
            evidence=[
                Fact(
                    entity_type=page.entity.entity_type, entity_name=page.entity.name,
                    field=field, value=fact.value, source_id=item.source_id,
                    contributor=item.contributor,
                )
                for fact in facts for item in fact.evidence
            ],
        ))
    return conflicts


def related_facts(page: WikiPage, pages: dict[str, WikiPage]) -> list[tuple[WikiPage, WikiFact]]:
    """Link the explicit aircraft.operator fact in both directions with its evidence."""
    related = []
    for aircraft in pages.values():
        if aircraft.entity.entity_type != "aircraft":
            continue
        for fact in aircraft.facts:
            if fact.field != "operator":
                continue
            operator = next((candidate for candidate in pages.values() if
                candidate.entity.entity_type == "operator"
                and normalized(candidate.entity.name) == normalized(fact.value)), None)
            if operator is None:
                continue
            target = operator if page is aircraft else aircraft if page is operator else None
            if target is not None:
                related.append((target, fact))
    return related


def render_page(page: WikiPage, pages: dict[str, WikiPage]) -> str:
    lines = [f"# {escape(page.entity.name)}", "", f"Type: {page.entity.entity_type}", "", "## Facts", "", TABLE_HEADER]
    for fact in sorted(page.facts, key=lambda f: (f.field, normalized(f.value))):
        lines.append(f"| {escape(fact.field)} | {escape(fact.value)} | {evidence_text(fact.evidence)} |")
    related = related_facts(page, pages)
    links = sorted({
        f"- [{escape(target.entity.name)}](../{page_name(target.entity)}) — {evidence_text(fact.evidence)}"
        for target, fact in related
    })
    lines.extend(["", "## Related entities", "", *(links or ["None."]), "", "## Conflicts", ""])
    conflicts = conflicts_for(page)
    if not conflicts:
        lines.append("No unresolved conflicts.")
    for conflict in conflicts:
        lines.extend([
            f"### {conflict.conflict_id}", "", f"Field: {escape(conflict.field)}",
            "Status: unresolved", "",
        ])
        for fact in sorted(page.facts, key=lambda f: normalized(f.value)):
            if fact.field == conflict.field:
                lines.append(f"- **{escape(fact.value)}** — {evidence_text(fact.evidence)}")
        lines.append("")
    # A relationship-only page still displays all of its relationship evidence.
    sources = {(item.source_id, item.contributor)
               for fact in page.facts + [fact for _, fact in related] for item in fact.evidence}
    lines.extend(["", "## Sources", ""])
    lines.extend(f"- {evidence_text([Evidence(source_id=s, contributor=c)])}" for s, c in sorted(sources))
    return "\n".join(lines).rstrip() + "\n"


def parse_page(text: str) -> WikiPage:
    lines = text.splitlines()
    if len(lines) < 8 or not lines[0].startswith("# ") or not lines[2].startswith("Type: "):
        raise ValueError("Unsupported wiki page header")
    page = WikiPage(entity=Entity(name=html.unescape(lines[0][2:]), entity_type=lines[2][6:]))
    table = text.split("## Facts\n\n", 1)[1].split("\n\n## Related entities", 1)[0]
    if not table.startswith(TABLE_HEADER):
        raise ValueError("Unsupported wiki fact table")
    for line in table.splitlines()[2:]:
        cells = line.split(" | ")
        if len(cells) != 3 or not cells[0].startswith("| ") or not cells[-1].endswith(" |"):
            raise ValueError("Invalid wiki fact row")
        field, value, citations = cells[0][2:], cells[1], cells[2][:-2]
        evidence = []
        for citation in citations.split("<br>"):
            match = EVIDENCE.fullmatch(citation)
            if not match:
                raise ValueError("Invalid wiki evidence reference")
            evidence.append(Evidence(source_id=match[1], contributor=html.unescape(match[2])))
        page.facts.append(WikiFact(field=html.unescape(field), value=html.unescape(value), evidence=evidence))
    return page


def render_index(pages: dict[str, WikiPage]) -> str:
    lines = ["# GoFlight Team Memory"]
    for kind, title in (("operator", "Operators"), ("aircraft", "Aircraft"), ("customer", "Customers")):
        lines.extend(["", f"## {title}"])
        entries = [(name, page) for name, page in pages.items() if page.entity.entity_type == kind]
        if entries:
            lines.append("")
            lines.extend(f"- [{escape(page.entity.name)}]({name})" for name, page in sorted(entries))
    return "\n".join(lines) + "\n"
