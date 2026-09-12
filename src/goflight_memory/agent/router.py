"""Placeholder only: semantic intent routing belongs to a later milestone."""

from goflight_memory.core.models import Intent, RouterDecision


def route(message: str) -> RouterDecision:
    """No classification is performed; zero confidence marks this as a stub."""
    return RouterDecision(intent=Intent.GENERAL, confidence=0.0)
