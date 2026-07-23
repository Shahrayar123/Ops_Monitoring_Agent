"""The LLM platform: the model registry and the provider layer.

Every supported model is declared in registry.py with its provider and context
budget. providers.py exposes ONE `chat()` used by the whole product — so the AI
analysis in Phase 5 never cares which vendor a user picked. Four of the five
providers (OpenAI, Grok, Gemini, Ollama) speak the OpenAI-compatible API, so one
client covers them; Claude uses the Anthropic SDK.
"""
