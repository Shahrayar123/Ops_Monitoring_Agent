"""Which LLM the AI analyst uses and where it's served.

These settings are shared infrastructure (one model service for all tenants),
so they come from .env rather than tenant YAML files:

    OLLAMA_BASE_URL  e.g. http://localhost:11434/v1
    OLLAMA_MODEL     e.g. qwen2.5:7b
    OLLAMA_API_KEY   any non-empty string (Ollama ignores it, the client requires it)
"""

import os

from pydantic import BaseModel


class LLMConfig(BaseModel):
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen2.5:7b"
    api_key: str = "ollama"


def load_llm_config() -> LLMConfig:
    return LLMConfig(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        model=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
        api_key=os.environ.get("OLLAMA_API_KEY", "ollama"),
    )
