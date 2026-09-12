"""Minimal semantic routing; obvious questions and greetings need no API call."""

import re

from goflight_memory.core.models import Intent, RouterDecision
from goflight_memory.llm.client import LLMClient


def route(message: str, client: LLMClient) -> RouterDecision:
    stripped = message.strip()
    if "?" in stripped or re.match(r"^(what|who|where|when|why|how|tell me|show me)\b", stripped, re.I):
        return RouterDecision(intent=Intent.QUERY, confidence=1)
    if stripped.lower().rstrip("!.") in {"hi", "hello", "hey", "thanks", "thank you"}:
        return RouterDecision(intent=Intent.GENERAL, confidence=1)
    return client.classify(message)
