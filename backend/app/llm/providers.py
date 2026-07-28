"""One `chat()` for every provider.

Callers pass a ModelSpec, the messages, and the user's API key (+ Ollama URL for
local models). They get back the text and token usage — identical shape no
matter the vendor. Errors become a single friendly LLMError so the UI can show
one clear message ("Invalid API key", "Couldn't reach Ollama", ...).
"""

import time
from dataclasses import dataclass

from .registry import PROVIDER_BASE_URLS, ModelSpec

DEFAULT_OLLAMA_URL = "http://localhost:11434"

OPENAI_COMPATIBLE = {"openai", "xai", "google", "ollama", "groq", "openrouter"}


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int


class LLMError(Exception):
    """A provider call failed. The message is safe to show to the user."""


def base_url(spec: ModelSpec, ollama_base_url: str | None) -> str:
    if spec.provider == "ollama":
        root = (ollama_base_url or DEFAULT_OLLAMA_URL).rstrip("/")
        return f"{root}/v1"
    return PROVIDER_BASE_URLS[spec.provider]


def chat(
    spec: ModelSpec,
    messages: list[dict],
    *,
    api_key: str | None = None,
    ollama_base_url: str | None = None,
    system: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    timeout: float = 60.0,
) -> ChatResult:
    if spec.needs_key and not api_key:
        raise LLMError(f"No API key configured for {spec.label}.")

    started = time.monotonic()
    if spec.provider == "anthropic":
        result = _anthropic_chat(spec, messages, api_key, system, max_tokens, temperature, timeout)
    elif spec.provider in OPENAI_COMPATIBLE:
        result = _openai_compatible_chat(spec, messages, api_key, ollama_base_url, system, max_tokens, temperature, timeout)
    else:
        raise LLMError(f"Unsupported provider '{spec.provider}'.")
    result.latency_ms = int((time.monotonic() - started) * 1000)
    return result


def _openai_compatible_chat(spec, messages, api_key, ollama_base_url, system, max_tokens, temperature, timeout=60.0) -> ChatResult:
    from openai import (
        APIConnectionError,
        AuthenticationError,
        OpenAI,
        OpenAIError,
        RateLimitError,
    )

    full = ([{"role": "system", "content": system}] if system else []) + messages
    client = OpenAI(
        base_url=base_url(spec, ollama_base_url),
        api_key=api_key or "ollama",  # Ollama ignores the key but the SDK needs a value
        timeout=timeout,
        max_retries=1,
    )
    try:
        resp = client.chat.completions.create(
            model=spec.model, messages=full, max_tokens=max_tokens, temperature=temperature
        )
    except AuthenticationError as exc:
        raise LLMError(f"Invalid API key for {spec.label}.") from exc
    except RateLimitError as exc:
        raise LLMError(f"{spec.label} rate limit or quota exceeded.") from exc
    except APIConnectionError as exc:
        where = "Ollama" if spec.provider == "ollama" else spec.label
        raise LLMError(f"Could not reach {where}. Check it's running and reachable.") from exc
    except OpenAIError as exc:
        raise LLMError(f"{spec.label} error: {exc}") from exc

    usage = resp.usage
    return ChatResult(
        text=resp.choices[0].message.content or "",
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
        latency_ms=0,
    )


def _anthropic_chat(spec, messages, api_key, system, max_tokens, temperature, timeout=60.0) -> ChatResult:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)
    try:
        resp = client.messages.create(
            model=spec.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or anthropic.NOT_GIVEN,
            messages=messages,
        )
    except anthropic.AuthenticationError as exc:
        raise LLMError(f"Invalid API key for {spec.label}.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError(f"{spec.label} rate limit or quota exceeded.") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"Could not reach {spec.label}.") from exc
    except anthropic.AnthropicError as exc:
        raise LLMError(f"{spec.label} error: {exc}") from exc

    text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
    return ChatResult(
        text=text,
        prompt_tokens=resp.usage.input_tokens,
        completion_tokens=resp.usage.output_tokens,
        total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
        latency_ms=0,
    )


def test_model(spec: ModelSpec, *, api_key: str | None = None, ollama_base_url: str | None = None) -> ChatResult:
    """A tiny real call to prove the model + key work (and warm the meter)."""
    return chat(
        spec,
        [{"role": "user", "content": "Reply with the single word: OK"}],
        api_key=api_key,
        ollama_base_url=ollama_base_url,
        max_tokens=16,
    )
