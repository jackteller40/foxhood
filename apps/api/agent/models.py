"""Model factory shared by the main agent and subagents."""
from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from core.config import settings


def make_model(max_tokens: int = 8000) -> ChatAnthropic:
    # This model rejects `temperature` (400: "Extra inputs are not permitted"), so we don't send it.
    return ChatAnthropic(model=settings.claude_model, max_tokens=max_tokens, max_retries=2)