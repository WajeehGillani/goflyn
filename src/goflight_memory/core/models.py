"""Small validated records shared by the future memory operations."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntityType(StrEnum):
    OPERATOR = "operator"
    AIRCRAFT = "aircraft"
    CUSTOMER = "customer"


class SourceMetadata(DomainModel):
    """Attribution only; unchanged raw source text is stored separately later."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: NonEmptyText
    contributor: NonEmptyText
    source_type: NonEmptyText
    created_at: AwareDatetime


class Entity(DomainModel):
    entity_type: EntityType
    name: NonEmptyText


class Fact(DomainModel):
    """One textual claim with one piece of attributed evidence."""

    entity_type: EntityType
    entity_name: NonEmptyText
    field: NonEmptyText
    value: NonEmptyText
    source_id: NonEmptyText
    contributor: NonEmptyText


class Conflict(DomainModel):
    """Evidence is retained in full; no resolution operation exists yet."""

    conflict_id: NonEmptyText
    entity_type: EntityType
    entity_name: NonEmptyText
    field: NonEmptyText
    evidence: list[Fact] = Field(min_length=2)
    status: Literal["unresolved", "resolved"] = "unresolved"

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        target = (self.entity_type, self.entity_name, self.field)
        if any(
            (fact.entity_type, fact.entity_name, fact.field) != target
            for fact in self.evidence
        ):
            raise ValueError("Conflict evidence must describe the same entity and field")
        if len({fact.value for fact in self.evidence}) < 2:
            raise ValueError("Conflict evidence must contain at least two distinct values")
        return self


class Intent(StrEnum):
    QUERY = "query"
    INGEST = "ingest"
    LINT = "lint"
    GENERAL = "general"


class RouterDecision(DomainModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class QueryResult(DomainModel):
    answer: NonEmptyText
    pages_used: list[NonEmptyText] = Field(default_factory=list)


class LintIssue(DomainModel):
    type: NonEmptyText
    page: NonEmptyText
    message: NonEmptyText
    severity: Literal["info", "warning", "error"]
