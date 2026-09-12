"""Deterministic identity, value comparison, and safe filenames."""

import re
import unicodedata

from goflight_memory.core.models import Entity


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    result = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    if not result or len(result) > 120:
        raise ValueError("Entity name must yield a nonempty filename of at most 120 characters")
    return result


def page_name(entity: Entity) -> str:
    directory = {"operator": "operators", "aircraft": "aircraft", "customer": "customers"}[entity.entity_type]
    return f"{directory}/{slug(entity.name)}.md"


def field_name(field: str) -> str:
    return slug(field).replace("-", "_")
