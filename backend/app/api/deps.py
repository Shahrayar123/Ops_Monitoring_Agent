"""Auth dependencies used by every protected route.

    user  = Depends(get_current_user)   -> any logged-in, active account
    admin = Depends(require_admin)      -> admins only (403 otherwise)
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..core.security import TokenError, decode_token
from ..db.base import get_db
from ..db.models import Role, User


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return header.removeprefix("Bearer ").strip()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    try:
        payload = decode_token(_bearer_token(request), expected_kind="access")
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account not found or disabled")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
