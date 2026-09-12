"""The only module that imports the provider SDK. No tools or filesystem access."""

import json
from typing import TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from goflight_memory.agent.prompts import EXTRACTION, PAGE_SELECTION, QUERY_ANSWER, ROUTING
from goflight_memory.core.models import Extraction, PageSelection, QueryResult, RouterDecision

Result = TypeVar("Result", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, api_key: str, model: str = "gpt-4.1-mini"):
        self.api_key = api_key
        self.model = model

    def _structured(self, instruction: str, content: str, result_type: type[Result]) -> Result:
        if not self.api_key:
            raise LLMError("Set OPENAI_API_KEY in .env before using the LLM")
        try:
            with OpenAI(api_key=self.api_key, timeout=45, max_retries=0) as client:
                response = client.responses.parse(
                    model=self.model,
                    input=[
                        {"role": "system", "content": instruction},
                        {"role": "user", "content": content},
                    ],
                    text_format=result_type,
                    max_output_tokens=4000,
                    store=False,
                )
            if response.status != "completed" or response.output_parsed is None:
                raise LLMError("Model refused or returned an incomplete structured response")
            return response.output_parsed
        except (OpenAIError, ValidationError) as error:
            # Do not expose provider response bodies, credentials, or raw note text.
            raise LLMError(f"LLM request failed ({type(error).__name__}); check configuration and retry") from error

    def classify(self, text: str) -> RouterDecision:
        return self._structured(ROUTING, text, RouterDecision)

    def extract(self, schema: str, source_id: str, contributor: str, text: str) -> Extraction:
        return self._structured(
            EXTRACTION + "\nSchema.md:\n" + schema,
            json.dumps({"source_id": source_id, "contributor": contributor, "raw_note": text}),
            Extraction,
        )

    def select_pages(self, question: str, catalog: dict[str, str], limit: int) -> PageSelection:
        return self._structured(
            PAGE_SELECTION,
            json.dumps({"question": question, "catalog": catalog, "limit": limit}),
            PageSelection,
        )

    def answer(self, question: str, pages: dict[str, str]) -> QueryResult:
        return self._structured(
            QUERY_ANSWER, json.dumps({"question": question, "wiki_pages": pages}), QueryResult,
        )
