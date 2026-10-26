"""The one LLM every agent uses: gpt-6-luna through the Portkey gateway."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from .config import MODEL_NAME, MODEL_TIMEOUT_SECONDS, PORTKEY_BASE_URL

Effort = Literal["low", "medium", "high"]


class MissingAPIKey(RuntimeError):
    pass


def api_key_present() -> bool:
    return bool(os.getenv("PORTKEY_API_KEY", "").strip())


def portkey_headers(key: str) -> dict[str, str]:
    """The course gateway can answer a request it has seen before from its response cache. That replays an old run
    (same answer, near-zero time) while the provider-reported tokens get logged again as if spent, so by default every
    call asks for a fresh answer. Set PORTKEY_ALLOW_CACHE=1 to accept cached replies (cheaper demos)."""
    headers = {"x-portkey-api-key": key, "x-portkey-provider": "openai"}
    if os.getenv("PORTKEY_ALLOW_CACHE", "").strip() != "1":
        headers["x-portkey-cache-force-refresh"] = "true"
    return headers


@lru_cache(maxsize=1)
def get_model() -> OpenAIResponsesModel:
    key = os.getenv("PORTKEY_API_KEY", "").strip()
    if not key:
        raise MissingAPIKey(
            "PORTKEY_API_KEY is not set. Put it in a .env file in this folder or the folder above it."
        )
    client = AsyncOpenAI(
        api_key=key,
        base_url=PORTKEY_BASE_URL,
        timeout=MODEL_TIMEOUT_SECONDS,  # a hung call fails the step instead of stalling the run
        max_retries=2,
        default_headers=portkey_headers(key),
    )
    # Responses API: gpt-6-luna does not accept function tools with reasoning on /v1/chat/completions.
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


def settings(agent_key: str, effort: Effort) -> OpenAIResponsesModelSettings:
    """Per-agent settings. The cache key groups calls that share the same long static prefix
    (system prompt + company policy) so OpenAI's prompt cache hits more often."""
    return OpenAIResponsesModelSettings(
        openai_reasoning_effort=effort,
        openai_prompt_cache_key=f"empower-{agent_key}",
    )
