import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from goflight_memory.agent.router import route
from goflight_memory.core.models import Extraction, Intent, RouterDecision
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
