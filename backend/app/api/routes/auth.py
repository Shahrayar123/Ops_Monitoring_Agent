"""Auth endpoints: register, login, refresh, logout, me, change-password, and
the self-service side of the account-deletion lifecycle (request/cancel
deletion, request recovery). The admin side (accept/reject deletion, approve/
reject recovery) lives in api/routes/user_admin.py.

Design notes:
- Register creates a normal `user` on the default plan; admins are created by
  other admins (or the seed script) — a public endpoint must never mint admins.
- Login failures return the SAME message for bad email and bad password, so
  the endpoint can't be used to probe which emails exist. /auth/recover follows
  the same anti-enumeration pattern.
- Logout revokes the refresh token's jti; the short-lived access token simply
  expires (standard stateless-JWT tradeoff).
- Account lifecycle: active -> deletion_requested -> deleted_recoverable
  (30-day window, see db.models.AccountStatus) -> either recovery_requested ->
  active again, or dormant if the window elapses unreviewed.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.security import (
    TokenError,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from ...db.base import get_db
from ...db.models import AccountStatus, Plan, RevokedToken, Role, User
from ...schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RecoverAccountRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from ..deps import get_current_user

log = logging.getLogger("backend.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

BAD_CREDENTIALS = "Incorrect email or password"
DELETED_ACCOUNT = "This account has been deleted. You can request account recovery."
DORMANT_ACCOUNT = "This account has been permanently deactivated and can no longer be recovered."
RECOVERY_SUBMITTED = "If this account is eligible for recovery, a request has been submitted for admin review."


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> User:
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    default_plan = db.scalar(select(Plan).where(Plan.is_active).order_by(Plan.id))
    user = User(
        email=email,
        full_name=body.full_name.strip(),
        password_hash=hash_password(body.password),
        role=Role.USER,
        plan=default_plan,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("New account registered: %s (plan: %s)", email, default_plan.name if default_plan else "-")
    return user


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail=BAD_CREDENTIALS)
    if not user.is_active:
        status = user.account_status
        if status == AccountStatus.DORMANT:
            raise HTTPException(status_code=403, detail=DORMANT_ACCOUNT)
        if status in (AccountStatus.DELETED_RECOVERABLE, AccountStatus.RECOVERY_REQUESTED):
            raise HTTPException(status_code=403, detail=DELETED_ACCOUNT)
        raise HTTPException(status_code=403, detail="This account has been disabled")

    return TokenPair(
        access_token=create_token(user.id, user.role, "access"),
        refresh_token=create_token(user.id, user.role, "refresh"),
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    try:
        payload = decode_token(body.refresh_token, expected_kind="refresh")
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    if db.scalar(select(RevokedToken).where(RevokedToken.jti == payload["jti"])):
        raise HTTPException(status_code=401, detail="This session has been logged out")

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account not found or disabled")

    # Rotate: revoke the used refresh token and issue a fresh pair.
    db.add(RevokedToken(
        jti=payload["jti"],
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
    ))
    db.commit()
    return TokenPair(
        access_token=create_token(user.id, user.role, "access"),
        refresh_token=create_token(user.id, user.role, "refresh"),
    )


@router.post("/logout", status_code=204)
def logout(body: RefreshRequest, db: Session = Depends(get_db)) -> None:
    """Revoke the refresh token. Idempotent: logging out twice is fine."""
    try:
        payload = decode_token(body.refresh_token, expected_kind="refresh")
    except TokenError:
        return  # already invalid/expired — nothing to revoke
    if not db.scalar(select(RevokedToken).where(RevokedToken.jti == payload["jti"])):
        db.add(RevokedToken(
            jti=payload["jti"],
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        ))
        db.commit()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/change-password", status_code=204)
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False   # clears the forced-change flag for invited users
    db.add(user)
    db.commit()
    log.info("Password changed for %s", user.email)


@router.post("/request-deletion", response_model=UserOut)
def request_account_deletion(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    """Self-service: a user flags their own account for deletion. This does NOT
    delete anything — an admin reviews pending requests and deletes the account
    from the admin panel. Admin accounts can't request this (they can't be
    deleted at all — see DELETE /admin/users/{id})."""
    if user.role == Role.ADMIN:
        raise HTTPException(status_code=400, detail="Admin accounts cannot request deletion")
    user.deletion_requested_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("Account deletion requested by %s", user.email)
    return user


@router.post("/cancel-deletion-request", response_model=UserOut)
def cancel_deletion_request(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    """Lets the user change their mind before an admin acts on the request."""
    user.deletion_requested_at = None
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/recover", status_code=200)
def recover_account(body: RecoverAccountRequest, db: Session = Depends(get_db)) -> dict:
    """Public endpoint: a soft-deleted user asks to be restored. Requires the
    original password to prove identity (a soft-deleted account still has
    is_active=False, so it can't authenticate normally to call this).

    Always returns the same generic message regardless of whether the email
    exists or is eligible — same anti-enumeration pattern as /auth/login.
    An admin reviews the request from the admin panel and approves or rejects it;
    this endpoint only ever flags the request, it never reactivates anything."""
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is not None and verify_password(body.password, user.password_hash):
        if user.account_status == AccountStatus.DELETED_RECOVERABLE:
            user.recovery_requested_at = datetime.now(timezone.utc)
            db.add(user)
            db.commit()
            log.info("Account recovery requested by %s", user.email)
    return {"message": RECOVERY_SUBMITTED}
