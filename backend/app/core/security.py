"""Passwords and tokens.

Passwords: bcrypt (never stored or logged in plain text).
Tokens: two JWTs —
  - access token  (short-lived): sent on every request, carries user id + role
  - refresh token (long-lived): only good for minting a new access token; it
    carries a unique id (jti) that logout stores in a revocation list, so a
    stolen refresh token can be cut off server-side.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import bcrypt
import jwt

from .config import get_settings

ALGORITHM = "HS256"

TokenKind = Literal["access", "refresh"]


# ---------- passwords ----------


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:  # malformed stored hash — treat as no match, never crash login
        return False


# ---------- tokens ----------


def create_token(user_id: int, role: str, kind: TokenKind) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    lifetime = (
        timedelta(minutes=settings.access_token_minutes)
        if kind == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "kind": kind,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


class TokenError(Exception):
    """The token is missing, malformed, expired, or of the wrong kind."""


def decode_token(token: str, expected_kind: Optional[TokenKind] = None) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc
    if expected_kind and payload.get("kind") != expected_kind:
        raise TokenError(f"Expected a {expected_kind} token")
    return payload
