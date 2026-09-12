"""Minimal semantic routing; obvious questions and greetings need no API call."""

import re

from goflight_memory.core.models import Intent, RouterDecision
from goflight_memory.llm.client import LLMClient


def route(message: str, client: LLMClient) -> RouterDecision:
    stripped = message.strip()
    if stripped.lower().rstrip("!?.") in {"hi", "hello", "hey", "thanks", "thank you", "what can you do", "how can you help"}:
        return RouterDecision(intent=Intent.GENERAL, confidence=1)
    health_request = re.match(r"^(?:please\s+)?(?:check|find|show|are there|is the|is our)\b", stripped, re.I)
    health_topic = re.search(r"\b(?:contradictions?|unresolved conflicts?|broken links?|missing sources?|orphan pages?)\b", stripped, re.I)
    memory_health = (re.search(r"\b(?:memory|wiki)\b", stripped, re.I)
                     and re.search(r"\b(?:problems?|health|healthy|check)\b", stripped, re.I))
    if health_request and (health_topic or memory_health):
        return RouterDecision(intent=Intent.LINT, confidence=1)
    if "?" in stripped or re.match(r"^(what|which|who|where|when|why|how|would|does|tell me|show me)\b", stripped, re.I):
        return RouterDecision(intent=Intent.QUERY, confidence=1)
    return client.classify(message)
