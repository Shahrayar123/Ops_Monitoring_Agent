"""Admin: create/invite users, control each user's model + cluster access, and
review the account-deletion lifecycle.

    POST   /admin/users/create                 create a user (optionally with cluster access) + generate an invite
    GET    /admin/users/{id}/detail             full per-user access (raw + effective)
    PATCH  /admin/users/{id}/access             set allowed models + call/token limits
    GET    /admin/users/{id}/clusters           which clusters this user can see
    PUT    /admin/users/{id}/clusters           replace the user's whole cluster set in one save
    DELETE /admin/users/{id}                    permanently delete a user (hard delete)
    POST   /admin/users/{id}/deletion/accept    accept a self-service deletion request -> soft-delete, 30-day recovery window
    POST   /admin/users/{id}/deletion/reject    reject a self-service deletion request -> account stays active
    POST   /admin/users/{id}/recovery/approve   restore a soft-deleted account (proactively, or in response to a recovery request)
    POST   /admin/users/{id}/recovery/reject    deny a pending recovery request -> account stays soft-deleted

See db.models.AccountStatus for the full lifecycle state machine. DELETE (hard
delete) stays available at any point as the admin's "purge permanently" tool —
e.g. to clean up a DORMANT account once the recovery window has lapsed.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.email import send_invite, send_password_reset, smtp_configured
from ...core.security import generate_temp_password, hash_password, verify_password
from ...db.base import get_db
from ...db.models import (
    AccountStatus, ApiUsage, Plan, Role, Tenant, TenantFile, User,
    UserKpiRefreshRate, UserSetting, UserTenant,
)
from ...engine.kpi_access import ALL_KPI_TASKS
from ...llm.access import effective_allowed_models, effective_limits, effective_priority
from ...llm.registry import get_model
from ...schemas.auth import UserOut
from ...schemas.llm import (
    AdminUserDetail,
    CreateUserRequest,
    InviteResult,
    SendCredentialsRequest,
    SendCredentialsResult,
    SetUserClustersRequest,
    UserAccessUpdate,
)
from ..deps import require_admin

log = logging.getLogger("backend.user_admin")

router = APIRouter(prefix="/admin/users", tags=["admin:users"], dependencies=[Depends(require_admin)])


def _validate_kpis(tasks: list[str]) -> list[str]:
    """De-dupe (keep order) and reject any task that isn't one of the nine
    checks. An empty list is valid and means 'no restriction — all KPIs'."""
    seen = list(dict.fromkeys(tasks))
    unknown = [t for t in seen if t not in ALL_KPI_TASKS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown KPI(s): {', '.join(unknown)}")
    return seen


def _clean_models(ids: list[str]) -> list[str]:
    """Keep only model ids that still exist in the registry (de-duped, order kept).

    Unknown ids are DROPPED, not rejected. A model removed from registry.py (e.g.
    a retired OpenRouter slug) can still be sitting in a user's stored
    allowed_models/model_priority; the Access modal pre-selects that stored value,
    so on save the admin would re-submit an id they were never shown a checkbox
    for. Rejecting it (a 400) would make the whole panel un-saveable through no
    fault of the admin's. Dropping it instead self-heals the row on the next save,
    and matches how effective_allowed_models() already filters unknown ids
    everywhere else."""
    return [m for m in dict.fromkeys(ids) if get_model(m) is not None]


def _detail(user: User) -> AdminUserDetail:
    limits = effective_limits(user)
    return AdminUserDetail(
        id=user.id, email=user.email, full_name=user.full_name, role=user.role,
        is_active=user.is_active, must_change_password=user.must_change_password,
        plan_id=user.plan_id, plan_name=user.plan.name if user.plan else None,
        allowed_models=user.allowed_models or [],
        model_priority=effective_priority(user),
        daily_call_limit=user.daily_call_limit, monthly_call_limit=user.monthly_call_limit,
        daily_token_limit=user.daily_token_limit, monthly_token_limit=user.monthly_token_limit,
        allowed_kpis=user.allowed_kpis or [],
        effective_allowed_models=effective_allowed_models(user),
        effective_daily_calls=limits.daily_calls, effective_monthly_calls=limits.monthly_calls,
        effective_daily_tokens=limits.daily_tokens, effective_monthly_tokens=limits.monthly_tokens,
    )


@router.post("/create", response_model=InviteResult, status_code=201)
def create_user(body: CreateUserRequest, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    if body.plan_id is not None and db.get(Plan, body.plan_id) is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    allowed_models = _clean_models(body.allowed_models)
    allowed_kpis = _validate_kpis(body.allowed_kpis)

    slugs = list(dict.fromkeys(body.tenant_slugs))  # de-dupe, keep order
    tenants = list(db.scalars(select(Tenant).where(Tenant.slug.in_(slugs)))) if slugs else []
    missing = set(slugs) - {t.slug for t in tenants}
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown cluster(s): {', '.join(sorted(missing))}")

    temp_password = generate_temp_password()  # human-shareable one-time password
    user = User(
        email=email,
        full_name=body.full_name.strip(),
        password_hash=hash_password(temp_password),
        role=body.role,
        plan_id=body.plan_id,
        must_change_password=True,
        allowed_models=allowed_models,
        allowed_kpis=allowed_kpis,
        daily_call_limit=body.daily_call_limit,
        monthly_call_limit=body.monthly_call_limit,
        daily_token_limit=body.daily_token_limit,
        monthly_token_limit=body.monthly_token_limit,
    )
    db.add(user)
    db.flush()  # assigns user.id, needed for the UserTenant rows below

    for tenant in tenants:
        db.add(UserTenant(user_id=user.id, tenant_id=tenant.id))
    db.commit()
    db.refresh(user)

    invite_link = f"{get_settings().app_base_url.rstrip('/')}/login"
    emailed = send_invite(email, user.full_name, temp_password, invite_link)
    log.info("Admin created user %s with access to clusters %s (emailed=%s)", email, slugs, emailed)

    return InviteResult(
        user_id=user.id, email=email, temp_password=temp_password, invite_link=invite_link,
        emailed=emailed,
        message=(
            "Invite emailed to the user." if emailed
            else "SMTP isn't configured — share these credentials with the user. They'll set a new password on first sign-in."
        ),
    )


@router.post("/{user_id}/reset-password", response_model=InviteResult)
def reset_password(user_id: int, db: Session = Depends(get_db)):
    """Issue a NEW temporary password for a user and return it to the admin.

    Used when a user is locked out, or when the original invite credentials were
    lost — the first password is bcrypt-hashed and can never be shown again, so
    this replaces it with a fresh one rather than revealing the old one. The user
    is flagged must_change_password, so the temp password only lives until their
    next sign-in. Also emailed to the user when SMTP is configured; shown on
    screen either way (that's what solves the dismissed-popup case)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Admin accounts are excluded from admin-initiated reset (mirrors the
    # can't-delete-an-admin rule). Admins change their own password via
    # /auth/change-password, or recover it self-service via /auth/forgot-password.
    if user.role == Role.ADMIN:
        raise HTTPException(status_code=400, detail="Admin accounts can't be reset from here — use Change password, or Forgot password on the sign-in screen.")

    temp_password = generate_temp_password()
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    db.add(user)
    db.commit()

    login_link = f"{get_settings().app_base_url.rstrip('/')}/login"
    emailed = send_password_reset(user.email, user.full_name, temp_password, login_link)
    log.info("Admin reset password for %s (emailed=%s)", user.email, emailed)

    return InviteResult(
        user_id=user.id, email=user.email, temp_password=temp_password, invite_link=login_link,
        emailed=emailed,
        message=(
            "Password reset — the new temporary password was also emailed to the user."
            if emailed else
            "Password reset — share this temporary password with the user. They'll set their own on first sign-in."
        ),
    )


@router.post("/{user_id}/send-credentials", response_model=SendCredentialsResult)
def send_credentials(user_id: int, body: SendCredentialsRequest, db: Session = Depends(get_db)):
    """Email the credentials currently shown on the admin's result screen to the
    user (an invite welcome, or a password-reset notice).

    The admin passes back the temp password they're looking at; we verify it's
    still the account's live credential before mailing, so a stale screen (e.g.
    another reset happened since) can't send a password that no longer works. The
    password itself is never re-generated here — this only delivers what's already
    set. Requires SMTP to be configured; otherwise the admin copies + shares it."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(body.temp_password, user.password_hash):
        raise HTTPException(status_code=409, detail="These credentials are out of date — reset the password to get a fresh one.")
    if not smtp_configured():
        return SendCredentialsResult(sent=False, message="Email isn't configured on the server — copy the credentials and share them manually.")

    login_link = f"{get_settings().app_base_url.rstrip('/')}/login"
    if body.kind == "reset":
        sent = send_password_reset(user.email, user.full_name, body.temp_password, login_link)
    else:
        sent = send_invite(user.email, user.full_name, body.temp_password, login_link)
    log.info("Admin sent %s credentials to %s (sent=%s)", body.kind, user.email, sent)

    return SendCredentialsResult(
        sent=sent,
        message="Credentials emailed to the user." if sent
        else "Couldn't send the email — check the SMTP settings. Copy the credentials and share them manually.",
    )


@router.get("/{user_id}/detail", response_model=AdminUserDetail)
def user_detail(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _detail(user)


@router.get("/{user_id}/clusters")
def user_clusters(user_id: int, db: Session = Depends(get_db)):
    """Which clusters this user currently has access to (admins can see all
    clusters regardless of this list — it only gates normal users)."""
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    rows = db.scalars(
        select(Tenant).join(UserTenant, UserTenant.tenant_id == Tenant.id).where(UserTenant.user_id == user_id)
    )
    return [{"slug": t.slug, "display_name": t.display_name} for t in rows]


@router.put("/{user_id}/clusters")
def set_user_clusters(user_id: int, body: SetUserClustersRequest, db: Session = Depends(get_db)):
    """Replaces the user's whole cluster set in one transaction — the admin
    ticks whichever clusters should be visible on this user's dashboard and
    saves once, rather than toggling one link/unlink call per cluster."""
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")

    slugs = list(dict.fromkeys(body.tenant_slugs))  # de-dupe, keep order
    tenants = list(db.scalars(select(Tenant).where(Tenant.slug.in_(slugs)))) if slugs else []
    missing = set(slugs) - {t.slug for t in tenants}
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown cluster(s): {', '.join(sorted(missing))}")

    db.execute(delete(UserTenant).where(UserTenant.user_id == user_id))
    for tenant in tenants:
        db.add(UserTenant(user_id=user_id, tenant_id=tenant.id))
    db.commit()

    log.info("Admin set clusters for user %s -> %s", user_id, slugs)
    return [{"slug": t.slug, "display_name": t.display_name} for t in tenants]


@router.patch("/{user_id}/access", response_model=AdminUserDetail)
def set_access(user_id: int, body: UserAccessUpdate, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.allowed_models = _clean_models(body.allowed_models)
    user.allowed_kpis = _validate_kpis(body.allowed_kpis)
    user.daily_call_limit = body.daily_call_limit
    user.monthly_call_limit = body.monthly_call_limit
    user.daily_token_limit = body.daily_token_limit
    user.monthly_token_limit = body.monthly_token_limit
    if body.model_priority is not None:
        # keep only still-allowed models, max 3
        allowed = set(effective_allowed_models(user)) if body.allowed_models else set(effective_allowed_models(user))
        user.model_priority = [m for m in body.model_priority if m in allowed][:3]

    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("Admin updated access for user %s", user.email)
    return _detail(user)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == Role.ADMIN:
        raise HTTPException(status_code=400, detail="Admin accounts cannot be deleted")

    # Clear every row that references this user, or the FK constraints reject the
    # delete. If you add a new table with a users.id FK, add it here too — a
    # missing line here surfaces as a 500 on delete, not a friendly error.
    db.execute(delete(UserTenant).where(UserTenant.user_id == user_id))
    db.execute(delete(UserSetting).where(UserSetting.user_id == user_id))
    db.execute(delete(ApiUsage).where(ApiUsage.user_id == user_id))
    db.execute(delete(UserKpiRefreshRate).where(UserKpiRefreshRate.user_id == user_id))
    # Uploaded files outlive their uploader — keep the file, just drop the link.
    db.execute(
        TenantFile.__table__.update().where(TenantFile.uploaded_by_id == user_id).values(uploaded_by_id=None)
    )
    db.delete(user)
    db.commit()
    log.info("Admin %s deleted user %s", admin.email, user.email)


def _get_user_for_review(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/{user_id}/deletion/accept", response_model=UserOut)
def accept_deletion_request(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Soft-deletes the account: deactivates it and starts the 30-day recovery
    window (see db.models.AccountStatus). Nothing is purged — cluster access,
    settings, and usage history are kept so recovery is a full restore."""
    user = _get_user_for_review(db, user_id)
    if user.account_status != AccountStatus.DELETION_REQUESTED:
        raise HTTPException(status_code=400, detail="This user has no pending deletion request")

    user.is_active = False
    user.deleted_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("Admin %s accepted deletion request for %s — soft-deleted, recoverable until %s",
              admin.email, user.email, user.recoverable_until)
    return user


@router.post("/{user_id}/deletion/reject", response_model=UserOut)
def reject_deletion_request(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Denies the request: the account is untouched and stays active."""
    user = _get_user_for_review(db, user_id)
    if user.account_status != AccountStatus.DELETION_REQUESTED:
        raise HTTPException(status_code=400, detail="This user has no pending deletion request")

    user.deletion_requested_at = None
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("Admin %s rejected deletion request for %s", admin.email, user.email)
    return user


@router.post("/{user_id}/recovery/approve", response_model=UserOut)
def approve_recovery_request(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Restores a soft-deleted account to normal — reactivates it and clears
    the whole lifecycle (deletion + deletion-review + recovery timestamps).

    Works both when the user has explicitly asked to be restored
    (RECOVERY_REQUESTED) and when the admin wants to restore proactively,
    e.g. after a phone call, without waiting on the self-service request
    (DELETED_RECOVERABLE) — either way, only inside the 30-day window."""
    user = _get_user_for_review(db, user_id)
    if user.account_status not in (AccountStatus.DELETED_RECOVERABLE, AccountStatus.RECOVERY_REQUESTED):
        raise HTTPException(status_code=400, detail="This user is not in a recoverable state")

    user.is_active = True
    user.deletion_requested_at = None
    user.deleted_at = None
    user.recovery_requested_at = None
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("Admin %s approved recovery for %s — account reactivated", admin.email, user.email)
    return user


@router.post("/{user_id}/recovery/reject", response_model=UserOut)
def reject_recovery_request(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Denies the recovery request: the account stays soft-deleted, still
    inside its original 30-day window (it isn't extended)."""
    user = _get_user_for_review(db, user_id)
    if user.account_status != AccountStatus.RECOVERY_REQUESTED:
        raise HTTPException(status_code=400, detail="This user has no pending recovery request")

    user.recovery_requested_at = None
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("Admin %s rejected recovery request for %s", admin.email, user.email)
    return user
