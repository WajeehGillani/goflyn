"""Validate the semantic proposal against Python-owned identities and provenance."""

from goflight_memory.core.models import Extraction, SourceMetadata
from goflight_memory.llm.client import LLMClient
from goflight_memory.wiki.naming import field_name, normalized

FIELDS = {
    "operator": {"contacts", "minimum_booking_notice", "booking_requirements", "operating_notes"},
    "aircraft": {"type", "operator", "home_base", "availability", "operating_notes"},
    "customer": {"aircraft_preferences", "airport_preferences", "travel_preferences", "operating_notes"},
}


def extract(client: LLMClient, schema: str, metadata: SourceMetadata, text: str) -> Extraction:
    proposed = client.extract(schema, metadata.source_id, metadata.contributor, text)
    # Revalidate even an injected client: the boundary is not the provider adapter.
    result = Extraction.model_validate(proposed.model_dump() if isinstance(proposed, Extraction) else proposed)
    entities = {(entity.entity_type, normalized(entity.name)) for entity in result.entities}
    for fact in result.facts:
        if fact.source_id != metadata.source_id or fact.contributor != metadata.contributor:
            raise ValueError("Extraction changed source or contributor identity")
        if (fact.entity_type, normalized(fact.entity_name)) not in entities:
            raise ValueError("Extraction fact refers to an undeclared entity")
        fact.field = field_name(fact.field)
        if fact.field not in FIELDS[fact.entity_type]:
            raise ValueError(f"Unsupported {fact.entity_type} field: {fact.field}")
    return result
