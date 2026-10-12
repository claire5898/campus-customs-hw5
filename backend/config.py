"""OpenAI-through-Portkey model configuration shared by all agents."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = os.getenv("PORTKEY_API_BASE_URL", "https://api.portkey.ai/v1")


def make_model() -> OpenAIResponsesModel:
    """Create the required OpenAI model client routed through Portkey."""
    portkey_key = os.getenv("PORTKEY_API_KEY")
    if not portkey_key:
        raise RuntimeError("PORTKEY_API_KEY is missing from the project-root .env")

    client = AsyncOpenAI(
        api_key=portkey_key,
        base_url=PORTKEY_BASE_URL,
        default_headers={
            "x-portkey-api-key": portkey_key,
            "x-portkey-provider": "openai",
        },
    )
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
