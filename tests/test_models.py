import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from goflight_memory.core.models import (
    Conflict,
    Entity,
    EntityType,
    Fact,
    Intent,
    LintIssue,
    QueryResult,
    RouterDecision,
    SourceMetadata,
)


def fact(**changes: object) -> Fact:
    data = {
        "entity_type": "operator",
        "entity_name": "Test Operator",
        "field": "booking_notice",
        "value": "24 hours",
        "source_id": "source-a",
        "contributor": "Contributor A",
    }
    return Fact.model_validate(data | changes)


class ModelTests(unittest.TestCase):
    def test_entity_type_and_required_name(self) -> None:
        for entity_type in EntityType:
            self.assertEqual(Entity(entity_type=entity_type, name=" Example ").name, "Example")
        for data in (
            {"entity_type": "airport", "name": "Example"},
            {"entity_type": "operator", "name": "  "},
            {"entity_type": "operator", "name": "Example", "unexpected": True},
        ):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                Entity.model_validate(data)

    def test_source_requires_attribution_and_timezone(self) -> None:
        data = {
            "source_id": "source-a",
            "contributor": "Contributor A",
            "source_type": "call_note",
            "created_at": datetime(2026, 9, 12, tzinfo=timezone.utc),
        }
        source = SourceMetadata.model_validate(data)
        self.assertEqual(SourceMetadata.model_validate_json(source.model_dump_json()), source)
        for changes in (
            {"source_id": ""},
            {"contributor": " "},
            {"source_type": ""},
            {"created_at": datetime(2026, 9, 12)},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                SourceMetadata.model_validate(data | changes)
        with self.assertRaises(ValidationError):
            source.contributor = "Changed"

    def test_facts_require_evidence_and_text(self) -> None:
        for key in ("entity_name", "field", "value", "source_id", "contributor"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                fact(**{key: " "})
        data = fact().model_dump()
        del data["source_id"]
        with self.assertRaises(ValidationError):
            Fact.model_validate(data)

    def test_conflict_keeps_both_attributed_values(self) -> None:
        evidence = [fact(), fact(value="48 hours", source_id="source-b", contributor="Contributor B")]
        conflict = Conflict(
            conflict_id="conflict-a",
            entity_type="operator",
            entity_name="Test Operator",
            field="booking_notice",
            evidence=evidence,
        )
        self.assertEqual(conflict.status, "unresolved")
        self.assertEqual(conflict.evidence, evidence)
        self.assertEqual(Conflict.model_validate_json(conflict.model_dump_json()), conflict)

    def test_conflict_rejects_insufficient_or_unrelated_evidence(self) -> None:
        for evidence in (
            [fact()],
            [fact(), fact(source_id="source-b")],
            [fact(), fact(value="48 hours", field="home_base")],
            [fact(), fact(value="48 hours", entity_name="Other Operator")],
            [fact(), fact(value="48 hours", entity_type="customer")],
        ):
            with self.subTest(evidence=evidence), self.assertRaises(ValidationError):
                Conflict(
                    conflict_id="conflict-a",
                    entity_type="operator",
                    entity_name="Test Operator",
                    field="booking_notice",
                    evidence=evidence,
                )

    def test_router_confidence_is_bounded_and_finite(self) -> None:
        for confidence in (0, 0.5, 1):
            self.assertEqual(RouterDecision(intent="query", confidence=confidence).intent, Intent.QUERY)
        for confidence in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(confidence=confidence), self.assertRaises(ValidationError):
                RouterDecision(intent="query", confidence=confidence)

    def test_result_and_lint_records(self) -> None:
        result = QueryResult(answer="Unknown")
        result.pages_used.append("operators/example.md")
        self.assertEqual(QueryResult(answer="Unknown").pages_used, [])
        with self.assertRaises(ValidationError):
            QueryResult(answer=" ")
        issue = LintIssue(type="orphan", page="operators/example.md", message="No inbound link", severity="warning")
        self.assertEqual(issue.severity, "warning")
        with self.assertRaises(ValidationError):
            LintIssue(type="orphan", page="operators/example.md", message="No inbound link", severity="urgent")
