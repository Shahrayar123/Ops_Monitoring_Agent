"""Run a chat through the user's model fallback chain.

Tries the user's priority models in order (default first). If one errors — bad
key, provider down, local Ollama unreachable — it records the failure and falls
through to the next. Each attempt is metered. The limit check runs once up front.

This is the single entry point the AI analysis (Phase 5) uses, so all the
per-user policy (which models, which keys, limits, fallback) lives in one place.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..db.models import User
from . import settings as llm_settings
from . import usage
from .access import effective_allowed_models, effective_priority
from .providers import ChatResult, DEFAULT_OLLAMA_URL, LLMError, chat
from .registry import get_model

log = logging.getLogger("backend.llm.runner")


@dataclass
class ChatOutcome:
    result: ChatResult
    model_id: str
    attempts: list[dict]   # per-model: {model_id, ok, error?}


def _chain_for(user: User) -> list[str]:
    """The models to try, in order: the user's priority chain, or — if they
    haven't set one — their first allowed model."""
    chain = effective_priority(user)
    if chain:
        return chain
    allowed = effective_allowed_models(user)
    return allowed[:1]


def chat_with_fallback(
    db: Session,
    user: User,
    messages: list[dict],
    *,
    kind: str = "analysis",
    system: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    timeout: float = 60.0,
) -> ChatOutcome:
    chain = _chain_for(user)
    if not chain:
        raise LLMError("No model is available — set your model priority in Settings.")

    usage.check_limit(db, user)  # one limit gate for the whole request

    ollama_url = llm_settings.get_ollama_url(db, user.id) or DEFAULT_OLLAMA_URL
    attempts: list[dict] = []

    for model_id in chain:
        spec = get_model(model_id)
        if spec is None:
            attempts.append({"model_id": model_id, "ok": False, "error": "unknown model"})
            continue

        api_key = llm_settings.get_api_key(db, user.id, spec.provider) if spec.needs_key else None
        if spec.needs_key and not api_key:
            attempts.append({"model_id": model_id, "ok": False, "error": f"no {spec.provider} API key"})
            continue

        try:
            result = chat(spec, messages, api_key=api_key, ollama_base_url=ollama_url,
                          system=system, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
        except LLMError as exc:
            log.warning("Model '%s' failed for user %s, falling back: %s", model_id, user.id, exc)
            usage.record(db, user, spec.id, spec.provider, kind, None, success=False)
            attempts.append({"model_id": model_id, "ok": False, "error": str(exc)})
            continue

        usage.record(db, user, spec.id, spec.provider, kind, result, success=True)
        attempts.append({"model_id": model_id, "ok": True})
        return ChatOutcome(result=result, model_id=model_id, attempts=attempts)

    # Every model in the chain failed.
    tried = "; ".join(f"{a['model_id']}: {a.get('error')}" for a in attempts)
    raise LLMError(f"All models failed. Tried — {tried}")
