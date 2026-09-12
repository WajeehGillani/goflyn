"""Bounded, inspectable field relevance and deterministic conflict-safe answers."""

import re

from goflight_memory.core.models import Conflict, WikiPage
from goflight_memory.wiki.naming import normalized
from goflight_memory.wiki.pages import conflicts_for, escape, evidence_text

FIELD_TERMS = {
    "home_base": r"\b(where|base|based|location|airport|departure|fit|suitability)\b",
    "minimum_booking_notice": r"\b(notice|lead time|advance|booking|bookings|requirements)\b",
    "type": r"\b(type|model|class|kind|fit|suitability)\b",
    "operator": r"\b(operator|operates?|fleet)\b",
    "availability": r"\b(available|availability|when|schedule|fit|suitability)\b",
    "aircraft_preferences": r"\b(prefer\w*|fit|suitability|compatible)\b",
    "airport_preferences": r"\b(prefer\w*|airport|departure|fit|suitability|compatible)\b",
    "travel_preferences": r"\b(prefer\w*|catering|cabin|fit|suitability|compatible)\b",
    "booking_requirements": r"\b(booking|bookings|requirements|manifest)\b",
    "contacts": r"\b(contact|contacts|phone|email|reach)\b",
    "operating_notes": r"\b(notes?|policy|policies|history|past|operating)\b",
}


def relevant_conflicts(question: str, answer: str, pages: dict[str, WikiPage]) -> list[tuple[str, Conflict]]:
    broad = bool(re.search(r"what do we know|tell me about|overview|summari[sz]e", question, re.I))
    result = []
    for name, page in pages.items():
        for conflict in conflicts_for(page):
            if conflict.status != "unresolved":
                continue
            terms = FIELD_TERMS.get(conflict.field, re.escape(conflict.field.replace("_", " ")))
            asked = broad or re.search(terms, question, re.I)
            relied = re.search(terms, answer, re.I) or any(normalized(f.value) in normalized(answer) for f in conflict.evidence)
            if asked or relied:
                result.append((name, conflict))
    return result


def conflict_safe(answer: str, conflicts: list[tuple[str, Conflict]]) -> bool:
    """A lexical guard, not an entailment proof; deterministic notices supply evidence."""
    for _, conflict in conflicts:
        mentioned = [normalized(value) in normalized(answer) for value in {f.value for f in conflict.evidence}]
        if any(mentioned) and not all(mentioned):
            return False
        if not re.search(r"unresolved|conflict|uncertain|unconfirmed|not confirmed|cannot.*authoritative", answer, re.I):
            return False
        if re.search(r"(?:is|are) (?:the )?(?:correct|authoritative)|newer.*(?:wins|correct)|"
                     r"\b(?:is|are) (?:now|currently)\b|\b(?:choose|recommend|use) (?:the )?(?:newer|latest)\b", answer, re.I):
            return False
    return True


def conflict_notice(conflicts: list[tuple[str, Conflict]]) -> str:
    lines = ["Unresolved conflicts in the relevant wiki fields:"]
    for _, conflict in conflicts:
        lines.append(f"{conflict.entity_name}.{conflict.field} ({conflict.conflict_id}):")
        lines.extend(f"- {fact.value} — {fact.source_id} — {fact.contributor}" for fact in conflict.evidence)
    lines.append("These conflicts remain unresolved; the memory has no authoritative current value for these fields.")
    return "\n".join(lines)


def current_context(page: WikiPage, original: str) -> str:
    """Do not offer superseded source values to synthesis as current facts."""
    resolved = {c.field: c.resolution for c in conflicts_for(page) if c.status == "resolved"}
    if not page.resolutions:
        return original
    lines = [f"# {escape(page.entity.name)}", f"Type: {page.entity.entity_type}", "", "## Current recorded facts"]
    for fact in page.facts:
        if fact.field not in resolved:
            lines.append(f"- {escape(fact.field)}: {escape(fact.value)} — {evidence_text(fact.evidence)}")
    for field, resolution in resolved.items():
        lines.extend([f"- {field}: {escape(resolution.value)} (human-resolved current value)",
                      f"  Reviewer: {escape(resolution.reviewer)}; reason: {escape(resolution.reason)}; "
                      f"recorded: {resolution.resolved_at.isoformat()}"])
    unresolved = [("", c) for c in conflicts_for(page) if c.status == "unresolved"]
    if unresolved:
        lines.append(conflict_notice(unresolved))
    lines.append("Historical conflicting evidence is preserved on the wiki page, not asserted as current here.")
    return "\n".join(lines)
