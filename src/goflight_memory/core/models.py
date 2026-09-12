"""Small validated records shared by memory operations."""

from collections import Counter
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
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
    """Attribution only; unchanged raw source text is stored separately."""

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
    supported: bool = True
    has_conflict: bool = False


class PageSelection(DomainModel):
    pages: list[NonEmptyText]
    reason: NonEmptyText


class LintIssue(DomainModel):
    type: NonEmptyText
    page: NonEmptyText
    message: NonEmptyText
    severity: Literal["info", "warning", "error"]


class LintReport(DomainModel):
    pages_scanned: int = Field(ge=0)
    issues: list[LintIssue] = Field(default_factory=list)

    @computed_field
    @property
    def counts_by_type(self) -> dict[str, int]:
        return dict(sorted(Counter(issue.type for issue in self.issues).items()))

    @computed_field
    @property
    def unresolved_conflicts(self) -> int:
        return self.counts_by_type.get("CONTRADICTION", 0)

    @computed_field
    @property
    def orphan_pages(self) -> int:
        return self.counts_by_type.get("ORPHAN_PAGE", 0)

    @computed_field
    @property
    def broken_links(self) -> int:
        return self.counts_by_type.get("BROKEN_LINK", 0)

    @computed_field
    @property
    def missing_sources(self) -> int:
        return self.counts_by_type.get("MISSING_SOURCE", 0)

    @computed_field
    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @computed_field
    @property
    def is_clean(self) -> bool:
        return not self.issues


class Extraction(DomainModel):
    entities: list[Entity]
    facts: list[Fact]


class Evidence(DomainModel):
    source_id: NonEmptyText
    contributor: NonEmptyText


class WikiFact(DomainModel):
    field: NonEmptyText
    value: NonEmptyText
    evidence: list[Evidence] = Field(min_length=1)


class WikiPage(DomainModel):
    entity: Entity
    facts: list[WikiFact] = Field(default_factory=list)


class IngestResult(DomainModel):
    source_id: NonEmptyText
    created_entities: list[Entity] = Field(default_factory=list)
    updated_entities: list[Entity] = Field(default_factory=list)
    pages_changed: list[str] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    git_commit: NonEmptyText
    already_ingested: bool = False
