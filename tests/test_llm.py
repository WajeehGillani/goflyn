import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from goflight_memory.agent.router import route
from goflight_memory.core.models import Extraction, Intent, PageSelection, QueryResult, RouterDecision
from goflight_memory.llm.client import LLMClient, LLMError


class LLMTests(unittest.TestCase):
    def test_obvious_questions_and_greetings_do_not_call_provider(self):
        client = MagicMock(spec=LLMClient)
        for question in ("What do we know about Atlantic Air?", "Tell me about N123GF"):
            self.assertEqual(route(question, client).intent, Intent.QUERY)
        self.assertEqual(route("Hello!", client).intent, Intent.GENERAL)
        client.classify.assert_not_called()

    def test_statement_uses_semantic_classifier(self):
        client = MagicMock(spec=LLMClient)
        client.classify.return_value = RouterDecision(intent="ingest", confidence=0.99)
        message = "Atlantic Air requires 48 hours notice."
        self.assertEqual(route(message, client).intent, Intent.INGEST)
        client.classify.assert_called_once_with(message)

    def test_representative_query_ingest_and_general_routes(self):
        client = MagicMock(spec=LLMClient)
        client.classify.return_value = RouterDecision(intent="ingest", confidence=0.99)
        for question in ("Which aircraft does Atlantic Air operate?", "Would Atlantic Air's aircraft fit Acme Corp?", "Does Atlantic Air require 48 hours notice?", "Tell me about Atlantic Air."):
            self.assertEqual(route(question, client).intent, Intent.QUERY)
        for statement in ("Atlantic Air requires 48 hours notice.", "I spoke to Atlantic Air. They now require 48 hours notice."):
            self.assertEqual(route(statement, client).intent, Intent.INGEST)
        for message in ("Hello", "What can you do?"):
            self.assertEqual(route(message, client).intent, Intent.GENERAL)

    def test_query_provider_methods_use_structured_schema(self):
        with patch.object(LLMClient, "_structured") as structured:
            client = LLMClient("test-placeholder")
            client.select_pages("question", {"aircraft/n123gf.md": "N123GF"}, 5)
            self.assertIs(structured.call_args.args[2], PageSelection)
            client.answer("question", {"aircraft/n123gf.md": "Compiled facts"})
            self.assertIs(structured.call_args.args[2], QueryResult)
            self.assertIn("Compiled facts", structured.call_args.args[1])

    def test_provider_uses_validated_output_without_tools_or_storage(self):
        parsed = Extraction(entities=[], facts=[])
        with patch("goflight_memory.llm.client.OpenAI") as sdk:
            responses = sdk.return_value.__enter__.return_value.responses
            responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=parsed)
            result = LLMClient("test-placeholder").extract("Schema", "source-001", "John", "Original note")
            self.assertEqual(result, parsed)
            request = responses.parse.call_args.kwargs
            self.assertIs(request["text_format"], Extraction)
            self.assertFalse(request["store"])
            self.assertNotIn("tools", request)
            self.assertIn("source-001", request["input"][1]["content"])
            self.assertIn("John", request["input"][1]["content"])
            self.assertIn("Schema", request["input"][0]["content"])

    def test_missing_key_and_refusal_fail_explicitly(self):
        with self.assertRaisesRegex(LLMError, "OPENAI_API_KEY"):
            LLMClient("").classify("An operational note")
        with patch("goflight_memory.llm.client.OpenAI") as sdk:
            sdk.return_value.__enter__.return_value.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=None)
            with self.assertRaisesRegex(LLMError, "refused"):
                LLMClient("test-placeholder").classify("An operational note")
