"""A small, strict Markdown table format; Markdown remains the source of wiki state."""

import hashlib
import html
import json
import re
from collections import defaultdict

from goflight_memory.core.models import Conflict, Entity, Evidence, Fact, Resolution, WikiFact, WikiPage
from goflight_memory.wiki.naming import normalized, page_name

TABLE_HEADER = "| Field | Value | Evidence |\n| --- | --- | --- |"
EVIDENCE = re.compile(r"\[(source-[0-9]{3,})\]\(\.\./\.\./raw/\1\.md\) — (.+)")


def escape(value: str) -> str:
    value = html.escape(value, quote=False)
    # Encode Markdown punctuation and newlines, including the table separator.
    return re.sub(r"[\\`*_{}\[\]()#+.!|\r\n-]", lambda m: f"&#{ord(m[0])};", value)


def evidence_text(evidence: list[Evidence]) -> str:
    return "<br>".join(
        f"[{item.source_id}](../../raw/{item.source_id}.md) — {escape(item.contributor)}"
        for item in sorted(evidence, key=lambda item: (item.source_id, item.contributor))
    )


def parse_evidence(text: str) -> list[Evidence]:
    result = []
    for citation in text.split("<br>"):
        match = EVIDENCE.fullmatch(citation)
        if not match:
            raise ValueError("Invalid wiki evidence reference")
        result.append(Evidence(source_id=match[1], contributor=html.unescape(match[2])))
    return result


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
        resolution = next((r for r in reversed(page.resolutions) if r.conflict_id == conflict_id), None)
        # New distinct claims reopen the field; earlier human decisions remain history.
        resolved = resolution is not None and {normalized(f.value) for f in facts} <= {
            normalized(value) for value in resolution.reviewed_values
        }
        conflicts.append(Conflict(
            conflict_id=conflict_id,
            entity_type=page.entity.entity_type,
            entity_name=page.entity.name,
            field=field,
            status="resolved" if resolved else "unresolved",
            resolution=resolution if resolved else None,
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
            f"Status: {conflict.status}", "",
        ])
        for fact in sorted(page.facts, key=lambda f: normalized(f.value)):
            if fact.field == conflict.field:
                lines.append(f"- **{escape(fact.value)}** — {evidence_text(fact.evidence)}")
        lines.append("")
        for resolution in (r for r in page.resolutions if r.conflict_id == conflict.conflict_id):
            lines.extend([
                "#### Human resolution", "",
                f"Current value: {escape(resolution.value)}",
                f"Reviewer: {escape(resolution.reviewer)}",
                f"Reason: {escape(resolution.reason)}",
                f"Resolved at: {resolution.resolved_at.isoformat()}",
                f"Reviewed values: {escape(json.dumps(resolution.reviewed_values, ensure_ascii=False))}",
                f"Reviewed sources: {evidence_text(resolution.reviewed_sources)}", "",
            ])
    # A relationship-only page still displays all of its relationship evidence.
    sources = {(item.source_id, item.contributor)
               for fact in page.facts + [fact for _, fact in related] for item in fact.evidence}
    sources.update((item.source_id, item.contributor) for item in page.entity_evidence)
    lines.extend(["", "## Sources", ""])
    if page.entity_evidence:
        lines.extend([f"Entity assertion: {evidence_text(page.entity_evidence)}", ""])
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
        evidence = parse_evidence(citations)
        page.facts.append(WikiFact(field=html.unescape(field), value=html.unescape(value), evidence=evidence))
    for line in text.split("\n## Sources\n", 1)[-1].splitlines():
        if line.startswith("Entity assertion: "):
            page.entity_evidence.extend(parse_evidence(line.removeprefix("Entity assertion: ")))
    section = text.split("\n## Conflicts\n", 1)[-1].split("\n## Sources\n", 1)[0]
    for block in re.split(r"^### ", section, flags=re.M)[1:]:
        conflict_id = block.splitlines()[0]
        for record in block.split("#### Human resolution\n\n")[1:]:
            labels = ("Current value", "Reviewer", "Reason", "Resolved at", "Reviewed values", "Reviewed sources")
            rows = record.splitlines()
            if len(rows) < len(labels) or any(not row.startswith(label + ": ") for row, label in zip(rows, labels)):
                raise ValueError("Malformed human resolution record")
            values = [row.split(": ", 1)[1] for row in rows[:len(labels)]]
            page.resolutions.append(Resolution(
                conflict_id=conflict_id, value=html.unescape(values[0]), reviewer=html.unescape(values[1]),
                reason=html.unescape(values[2]), resolved_at=values[3],
                reviewed_values=json.loads(html.unescape(values[4])), reviewed_sources=parse_evidence(values[5]),
            ))
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


def conflict_section(markdown: str) -> str:
    return markdown.split("\n## Conflicts\n", 1)[1].split("\n## Sources\n", 1)[0]


def recorded_conflicts(page: WikiPage, markdown: str) -> list[Conflict]:
    """One persisted-conflict interpretation shared by ingest, query, lint and resolve."""
    for heading in ("## Facts", "## Related entities", "## Conflicts", "## Sources"):
        if markdown.splitlines().count(heading) != 1:
            raise ValueError(f"Missing or duplicate section: {heading}")
    section = conflict_section(markdown)
    statuses = dict(re.findall(
        r"^### (conflict-[0-9a-f]{16})\n\nField: [^\n]+\nStatus: (unresolved|resolved)$",
        section, re.M,
    ))
    expected = conflict_section(render_page(page, {page_name(page.entity): page}))
    # Pre-5.1 status-only historical records remain lint-readable, not authoritative.
    comparable = section if page.resolutions else re.sub(r"^Status: resolved$", "Status: unresolved", section, flags=re.M)
    if comparable != expected:
        raise ValueError("Malformed or inconsistent recorded conflict section")
    for resolution in page.resolutions:
        conflict = next((c for c in conflicts_for(page) if c.conflict_id == resolution.conflict_id), None)
        if conflict is None or not set(resolution.reviewed_values) <= {f.value for f in conflict.evidence}:
            raise ValueError("Human resolution refers to unknown evidence values")
        if not {(e.source_id, e.contributor) for e in resolution.reviewed_sources} <= {
            (f.source_id, f.contributor) for f in conflict.evidence
        }:
            raise ValueError("Human resolution refers to unknown source evidence")
    return [conflict.model_copy(update={"status": statuses[conflict.conflict_id]})
            for conflict in conflicts_for(page)]
