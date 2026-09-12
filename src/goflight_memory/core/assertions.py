"""Small explicit entity grammar, not inference from an incidental person mention."""

import re

from goflight_memory.core.models import Entity


def explicit_entity(text: str) -> Entity | None:
    match = re.fullmatch(
        r"(?:/add\s+|add\s+|we have\s+)?(?:a\s+)?(?:new\s+)?"
        r"(customer|operator|aircraft)\s+(?:(?:called|named)\s+)?([^\n.!?]+)\.?",
        text.strip(), re.I,
    )
    if not match:
        return None
    name = match[2].strip()
    # A sentence describing attributes belongs to normal semantic extraction.
    if len(name) > 100 or re.search(r"\b(is|are|has|have|prefers?|requires?|operates?|based|yesterday|today)\b", name, re.I):
        return None
    if not re.fullmatch(r"[\w][\w '\-]*", name):
        return None
    return Entity(entity_type=match[1].lower(), name=name.upper() if match[1].lower() == "aircraft" else name)
