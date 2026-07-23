"""Per-user LLM settings stored in the user_settings table.

Keys used:
    selected_model            plain   the model id the user picks for AI runs
    ollama_base_url           plain   where the user's local Ollama listens
    api_key:<provider>        secret  encrypted API key per cloud provider

Secrets go in value_encrypted (Fernet); the frontend only ever gets a masked
'••••••••abcd' back, never the real key.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.crypto import decrypt, encrypt, mask
from ..db.models import User, UserSetting

SELECTED_MODEL = "selected_model"
OLLAMA_BASE_URL = "ollama_base_url"


def _row(db: Session, user_id: int, key: str) -> UserSetting | None:
    return db.scalar(select(UserSetting).where(UserSetting.user_id == user_id, UserSetting.key == key))


def _set_plain(db: Session, user_id: int, key: str, value: str) -> None:
    row = _row(db, user_id, key)
    if row is None:
        row = UserSetting(user_id=user_id, key=key)
        db.add(row)
    row.value = value
    row.value_encrypted = ""
    db.commit()


def get_plain(db: Session, user_id: int, key: str, default: str = "") -> str:
    row = _row(db, user_id, key)
    return row.value if row and row.value else default


def set_selected_model(db: Session, user_id: int, model_id: str) -> None:
    _set_plain(db, user_id, SELECTED_MODEL, model_id)


def get_selected_model(db: Session, user_id: int) -> str:
    return get_plain(db, user_id, SELECTED_MODEL)


def set_ollama_url(db: Session, user_id: int, url: str) -> None:
    _set_plain(db, user_id, OLLAMA_BASE_URL, url)


def get_ollama_url(db: Session, user_id: int) -> str:
    return get_plain(db, user_id, OLLAMA_BASE_URL)


# ---------- API keys (encrypted) ----------


def _key_name(provider: str) -> str:
    return f"api_key:{provider}"


def set_api_key(db: Session, user_id: int, provider: str, api_key: str) -> None:
    row = _row(db, user_id, _key_name(provider))
    if row is None:
        row = UserSetting(user_id=user_id, key=_key_name(provider))
        db.add(row)
    row.value = api_key[-4:]            # last-4 kept in plain for the masked display
    row.value_encrypted = encrypt(api_key)
    db.commit()


def get_api_key(db: Session, user_id: int, provider: str) -> str | None:
    row = _row(db, user_id, _key_name(provider))
    if row is None or not row.value_encrypted:
        return None
    return decrypt(row.value_encrypted)


def delete_api_key(db: Session, user_id: int, provider: str) -> None:
    row = _row(db, user_id, _key_name(provider))
    if row is not None:
        db.delete(row)
        db.commit()


def has_api_key(db: Session, user_id: int, provider: str) -> bool:
    row = _row(db, user_id, _key_name(provider))
    return bool(row and row.value_encrypted)


def masked_key(db: Session, user_id: int, provider: str) -> str | None:
    row = _row(db, user_id, _key_name(provider))
    if row is None or not row.value_encrypted:
        return None
    return mask(row.value or "")
