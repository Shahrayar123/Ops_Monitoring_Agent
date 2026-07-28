"""User LLM settings — model priority, API keys, Ollama URL, usage.

    GET    /settings/llm                     everything the Settings page needs
    POST   /settings/llm/priority            set the fallback chain (up to 3 models)
    POST   /settings/llm/ollama-url          set the local Ollama address
    PUT    /settings/llm/keys                 save an encrypted provider API key
    DELETE /settings/llm/keys/{provider}      remove a key
    POST   /settings/llm/test                 tiny real call to validate + warm the meter

Which models a user MAY use and their usage limits are set by an admin (see
llm/access.py). Here the user only picks their priority order and keys.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...db.models import User
from ...llm import providers, settings as llm_settings, usage
from ...llm.access import effective_allowed_models, effective_priority
from ...llm.registry import PROVIDER_LABELS, all_models, get_model, providers_in_use
from ...schemas.llm import (
    LlmSettingsOut,
    ModelOut,
    OllamaUrlRequest,
    ProviderKeyOut,
    SetApiKeyRequest,
    SetPriorityRequest,
    TestModelRequest,
    UsageOut,
)
from ..deps import get_current_user

router = APIRouter(prefix="/settings/llm", tags=["settings"])


def _models_for(db: Session, user: User) -> list[ModelOut]:
    allowed = set(effective_allowed_models(user))
    out = []
    for m in all_models():
        key_ready = (not m.needs_key) or llm_settings.has_api_key(db, user.id, m.provider)
        out.append(ModelOut(
            id=m.id, label=m.label, provider=m.provider,
            provider_label=PROVIDER_LABELS.get(m.provider, m.provider),
            context_tokens=m.context_tokens, needs_key=m.needs_key, notes=m.notes,
            allowed=m.id in allowed, key_ready=key_ready,
        ))
    return out


def _providers_for(db: Session, user: User) -> list[ProviderKeyOut]:
    out = []
    for p in providers_in_use():
        if p == "ollama":
            continue  # local — no cloud key
        out.append(ProviderKeyOut(
            provider=p, provider_label=PROVIDER_LABELS.get(p, p),
            configured=llm_settings.has_api_key(db, user.id, p),
            masked_key=llm_settings.masked_key(db, user.id, p),
        ))
    return out


def _usage_out(db: Session, user: User) -> UsageOut:
    s = usage.status_for(db, user)
    return UsageOut(**s.__dict__)


def _settings_out(db: Session, user: User) -> LlmSettingsOut:
    return LlmSettingsOut(
        model_priority=effective_priority(user),
        ollama_base_url=llm_settings.get_ollama_url(db, user.id) or providers.DEFAULT_OLLAMA_URL,
        models=_models_for(db, user),
        providers=_providers_for(db, user),
        usage=_usage_out(db, user),
    )


@router.get("", response_model=LlmSettingsOut)
def get_llm_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _settings_out(db, user)


@router.post("/priority", response_model=LlmSettingsOut)
def set_priority(body: SetPriorityRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    allowed = set(effective_allowed_models(user))
    chosen = body.model_ids
    if len(chosen) > 3:
        raise HTTPException(status_code=400, detail="You can prioritise at most 3 models")
    if len(set(chosen)) != len(chosen):
        raise HTTPException(status_code=400, detail="The same model can't appear twice")
    for mid in chosen:
        if get_model(mid) is None:
            raise HTTPException(status_code=404, detail=f"Unknown model '{mid}'")
        if mid not in allowed:
            raise HTTPException(status_code=403, detail=f"'{mid}' isn't one of your allowed models")
    user.model_priority = chosen
    db.add(user)
    db.commit()
    db.refresh(user)
    return _settings_out(db, user)


@router.post("/ollama-url", response_model=LlmSettingsOut)
def set_ollama_url(body: OllamaUrlRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    llm_settings.set_ollama_url(db, user.id, body.url.rstrip("/"))
    return _settings_out(db, user)


@router.put("/keys", response_model=LlmSettingsOut)
def set_key(body: SetApiKeyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.provider not in PROVIDER_LABELS or body.provider == "ollama":
        raise HTTPException(status_code=400, detail="Unknown provider")
    llm_settings.set_api_key(db, user.id, body.provider, body.api_key.strip())
    return _settings_out(db, user)


@router.delete("/keys/{provider}", response_model=LlmSettingsOut)
def delete_key(provider: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    llm_settings.delete_api_key(db, user.id, provider)
    return _settings_out(db, user)


@router.post("/test")
def test_model(body: TestModelRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send a one-word prompt to validate a model + key. Counts against limits
    (it's a real call) and records usage so the meter stays truthful."""
    spec = get_model(body.model_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown model")
    if body.model_id not in set(effective_allowed_models(user)):
        raise HTTPException(status_code=403, detail="This model isn't one of your allowed models")

    try:
        usage.check_limit(db, user)
    except usage.LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    api_key = llm_settings.get_api_key(db, user.id, spec.provider) if spec.needs_key else None
    ollama_url = llm_settings.get_ollama_url(db, user.id) or providers.DEFAULT_OLLAMA_URL

    try:
        result = providers.test_model(spec, api_key=api_key, ollama_base_url=ollama_url)
    except providers.LLMError as exc:
        usage.record(db, user, spec.id, spec.provider, "test", None, success=False)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    usage.record(db, user, spec.id, spec.provider, "test", result, success=True)
    return {
        "ok": True,
        "message": f"{spec.label} responded in {result.latency_ms} ms.",
        "reply": result.text.strip(),
        "tokens": result.total_tokens,
        "usage": _usage_out(db, user).model_dump(),
    }
