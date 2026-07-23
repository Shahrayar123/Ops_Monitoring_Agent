"""The model registry — every LLM the product can use.

This is the "configuration of all models": each entry declares the provider, the
real model id to call, the context-token budget, and whether it needs a
user-supplied API key (local Ollama models don't). Plans and per-user access
reference these by `id`.

Because analysis is AGENTIC (the analyst runs as an Agents-SDK agent that calls
investigation tools — see app/ai/agent_runner.py), every model listed here must
support tool / function calling. Do not add a model that can't call tools.

Providers by transport:
    openai, xai (Grok), google (Gemini), ollama, groq, openrouter
        -> OpenAI-compatible endpoint (one code path in providers.py)
    anthropic (Claude)
        -> Anthropic SDK. NOTE: Anthropic can't run through the Agents SDK in
           this environment (no litellm/any-llm adapter — see agent_runner.py),
           so Claude models take a single-shot direct-call path. They still work,
           just without live tool use for that one provider.

Not yet included — Azure AI Foundry / Azure OpenAI: it needs a per-user resource
endpoint URL + deployment name + api-version, not just a pasted API key, so it
requires extra per-user config and its own keys UI. Deferred to a follow-up.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    id: str                      # unique id used everywhere (plans, settings)
    label: str                   # human name for the UI
    provider: str                # openai | anthropic | google | xai | ollama | groq | openrouter
    model: str                   # the actual model id sent to the provider
    context_tokens: int          # max context window
    needs_key: bool = True       # cloud models need a user key; Ollama does not
    notes: str = ""


# Default cloud endpoints (OpenAI-compatible). Ollama's base URL is per-user.
PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "xai": "https://api.x.ai/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

PROVIDER_LABELS = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI",
    "google": "Google (Gemini)",
    "xai": "xAI (Grok)",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "ollama": "Ollama (local)",
}

# The order providers are shown in (grouped dropdowns, keys UI). Anything not
# listed falls to the end, alphabetical.
PROVIDER_ORDER = ["anthropic", "openai", "google", "xai", "groq", "openrouter", "ollama"]


# The catalogue, grouped by provider. Extend freely — the whole app reads from
# here — but every model MUST support tool calling (this is an agentic product).
MODELS: list[ModelSpec] = [
    # --- Anthropic (Claude) — direct-call path, see module docstring ---
    ModelSpec("claude-opus-4-8", "Claude Opus 4.8", "anthropic", "claude-opus-4-8", 200000,
              notes="Most capable Claude; strongest reasoning for complex incidents."),
    ModelSpec("claude-sonnet-5", "Claude Sonnet 5", "anthropic", "claude-sonnet-5", 200000,
              notes="Balanced Claude — the default for most analysis."),
    ModelSpec("claude-haiku-4-5", "Claude Haiku 4.5", "anthropic", "claude-haiku-4-5-20251001", 200000,
              notes="Fast, low-cost Claude for high-volume analysis."),

    # --- OpenAI ---
    ModelSpec("gpt-4o", "GPT-4o", "openai", "gpt-4o", 128000),
    ModelSpec("gpt-4o-mini", "GPT-4o mini", "openai", "gpt-4o-mini", 128000),

    # --- Google (Gemini) ---
    ModelSpec("gemini-2.5-flash", "Gemini 2.5 Flash", "google", "gemini-2.5-flash", 1_000_000),
    ModelSpec("gemini-2.0-flash", "Gemini 2.0 Flash", "google", "gemini-2.0-flash", 1_000_000),

    # --- xAI (Grok) ---
    ModelSpec("grok-3-mini", "Grok 3 mini", "xai", "grok-3-mini", 131072),

    # --- Groq (fast inference, OpenAI-compatible) — one safe default; add more
    #     tool-calling Groq models (see console.groq.com/docs/models) as needed ---
    ModelSpec("groq-llama-3.3-70b", "Llama 3.3 70B (Groq)", "groq", "llama-3.3-70b-versatile", 131072,
              notes="Fast hosted Llama 3.3 on Groq — supports tool calling."),

    # --- OpenRouter (many models via one key) — one safe default. To use a FREE
    #     model, switch `model` to a `:free` variant (e.g.
    #     "meta-llama/llama-3.3-70b-instruct:free"), but FIRST confirm that model
    #     lists "Tools" support on openrouter.ai — many free models do not, and
    #     an agentic run needs tool calling. IDs rotate; verify before shipping. ---
    ModelSpec("openrouter-llama-3.3-70b", "Llama 3.3 70B (OpenRouter)", "openrouter", "meta-llama/llama-3.3-70b-instruct", 131072,
              notes="Llama 3.3 70B via OpenRouter — supports tool calling. Swap to a :free variant to run at no cost (verify tool support first)."),
    # Arcee Agent hosted via OpenRouter (vs the local Ollama arcee-agent above).
    # NOTE: verify the exact slug on openrouter.ai — Arcee's tool-calling model is
    # sometimes listed as "arcee-ai/caller-large"; adjust `model` if this 404s.
    ModelSpec("openrouter-arcee-agent", "Arcee Agent (OpenRouter)", "openrouter", "arcee-ai/arcee-agent", 32768,
              notes="Arcee's agentic tool-calling model, hosted via OpenRouter."),

    # --- Ollama (local; data never leaves the network). Only tool-capable local
    #     models belong here — qwen2.5, llama3.1, and arcee-agent all call tools. ---
    ModelSpec("qwen2.5:7b", "Qwen 2.5 7B (local)", "ollama", "qwen2.5:7b", 32768,
              needs_key=False, notes="Runs on the user's own Ollama — data never leaves the network."),
    ModelSpec("llama3.1:8b", "Llama 3.1 8B (local)", "ollama", "llama3.1:8b", 131072,
              needs_key=False, notes="Local Llama 3.1 via Ollama — supports tool calling."),
    ModelSpec("arcee-agent", "Arcee Agent (local)", "ollama", "arcee-ai/arcee-agent:latest", 32768,
              needs_key=False, notes="Local Arcee model tuned for agentic tool use."),
]

_BY_ID = {m.id: m for m in MODELS}


def get_model(model_id: str) -> ModelSpec | None:
    return _BY_ID.get(model_id)


def all_models() -> list[ModelSpec]:
    return list(MODELS)


def providers_in_use() -> list[str]:
    """Distinct providers across the catalogue, in PROVIDER_ORDER (for the
    API-keys UI and grouped model dropdowns)."""
    present = {m.provider for m in MODELS}
    ordered = [p for p in PROVIDER_ORDER if p in present]
    ordered += sorted(p for p in present if p not in PROVIDER_ORDER)
    return ordered
