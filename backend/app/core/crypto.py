"""Encryption-at-rest for stored secrets (user LLM API keys, CM passwords).

Fernet (AES-128-CBC + HMAC) with a key from settings. Values are encrypted
before they touch the database and are never sent back to the frontend after
saving — the UI only ever sees a masked placeholder.
"""

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.encode("ascii"))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


class DecryptionError(Exception):
    """The stored value can't be decrypted (wrong ENCRYPTION_KEY or corrupt data)."""


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "Stored secret could not be decrypted — has ENCRYPTION_KEY changed?"
        ) from exc


def mask(secret_last4: str) -> str:
    """The only form of a secret the frontend ever sees, e.g. '••••••••abcd'."""
    return "••••••••" + secret_last4
