"""User-facing monitoring endpoints — the dashboard's data source.

    GET  /tenants                          clusters this user can see
    GET  /tenants/{slug}                    one cluster's detail (+ file coverage)
    GET  /tenants/{slug}/dates              days available for the date filter
    GET  /tenants/{slug}/report?as_of=...   run all nine checks
    GET  /tenants/{slug}/refresh-rates      per-check refresh seconds (cluster default, with the
                                             viewing user's Settings -> KPI refresh overrides applied)
    GET/PUT /tenants/{slug}/thresholds      view / edit breach thresholds

Per-user refresh-rate overrides themselves are set at /settings/kpi-refresh
(api/routes/kpi_settings.py) — this file only applies them when reporting.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...db.models import Role, Tenant, User, UserKpiRefreshRate, UserTenant
from ...engine import bridge
from ...engine.bridge import DataSourceError
from ...engine import uploads
from ...schemas.tenant import TenantDetail, TenantSummary, ThresholdsUpdate
from ..deps import get_current_user
from ..tenant_deps import get_tenant_or_404

router = APIRouter(tags=["monitoring"])


def _effective_refresh_rates(tenant: Tenant, user: "User | None" = None, db: "Session | None" = None) -> dict:
    """The cluster's per-check rates, with this user's personal overrides (Settings
    -> KPI refresh time) applied on top — same rates used by every cluster they see.
    `user`/`db` are optional: the admin tenant-management panel (tenant_admin.py)
    reuses this for cluster defaults only, with no personal-dashboard user in scope."""
    rates = bridge.refresh_rates_for(tenant)
    if user is None or db is None:
        return rates
    overrides = db.scalars(select(UserKpiRefreshRate).where(UserKpiRefreshRate.user_id == user.id))
    return {**rates, **{o.task: o.interval_seconds for o in overrides}}


@router.get("/tenants", response_model=list[TenantSummary])
def list_tenants(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every cluster for admins; only linked clusters for normal users."""
    if user.role == Role.ADMIN:
        return list(db.scalars(select(Tenant).order_by(Tenant.display_name)))
    rows = db.scalars(
        select(Tenant)
        .join(UserTenant, UserTenant.tenant_id == Tenant.id)
        .where(UserTenant.user_id == user.id)
        .order_by(Tenant.display_name)
    )
    return list(rows)


def _tenant_detail(tenant: Tenant, user: "User | None" = None, db: "Session | None" = None) -> TenantDetail:
    detail = TenantDetail.model_validate(tenant)
    detail.has_cm_password = bool(tenant.cm_password_encrypted)
    detail.refresh_rates = _effective_refresh_rates(tenant, user, db)
    if tenant.data_source_mode == "json":
        detail.coverage = uploads.coverage(tenant.slug) if _uses_upload_dir(tenant) else None
    return detail


def _uses_upload_dir(tenant: Tenant) -> bool:
    # The seeded demo tenant points at the repo's data/ folder, not uploads/;
    # coverage only applies to admin-uploaded tenants.
    return str(uploads.tenant_dir(tenant.slug)) == tenant.data_dir


@router.get("/tenants/{slug}", response_model=TenantDetail)
def get_tenant(tenant: Tenant = Depends(get_tenant_or_404), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _tenant_detail(tenant, user, db)


@router.get("/tenants/{slug}/dates")
def tenant_dates(tenant: Tenant = Depends(get_tenant_or_404)):
    try:
        dates = bridge.available_dates(tenant)
    except DataSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"dates": [d.isoformat() for d in dates]}


@router.get("/tenants/{slug}/report")
def tenant_report(
    tenant: Tenant = Depends(get_tenant_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    as_of: Optional[date] = Query(default=None),
):
    try:
        report = bridge.build_report(tenant, as_of)
    except DataSourceError as exc:
        # The tenant's data source isn't usable yet (no files / API not wired).
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    payload = report.model_dump(mode="json")
    payload["refresh_rates"] = _effective_refresh_rates(tenant, user, db)
    payload["data_source_mode"] = tenant.data_source_mode
    payload["cloudera_version"] = tenant.cloudera_version
    return payload


@router.get("/tenants/{slug}/report/{task}")
def tenant_single_check(
    task: str,
    tenant: Tenant = Depends(get_tenant_or_404),
    as_of: Optional[date] = Query(default=None),
):
    """One check's current result — each dashboard card polls this on its own
    configured interval."""
    try:
        result = bridge.build_single_check(tenant, task, as_of)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown check '{task}'")
    except DataSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.get("/tenants/{slug}/refresh-rates")
def get_refresh_rates(tenant: Tenant = Depends(get_tenant_or_404), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _effective_refresh_rates(tenant, user, db)


@router.get("/tenants/{slug}/thresholds")
def get_thresholds(tenant: Tenant = Depends(get_tenant_or_404)):
    return bridge.tenant_to_config(tenant).thresholds.model_dump()


@router.put("/tenants/{slug}/thresholds")
def update_thresholds(
    body: ThresholdsUpdate,
    tenant: Tenant = Depends(get_tenant_or_404),
    db: Session = Depends(get_db),
):
    """Merge the provided fields into the tenant's thresholds and persist. The
    next report uses them immediately (bridge reads the DB each time)."""
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No threshold values provided")

    merged = {**(tenant.thresholds or {}), **changes}
    # Validate through the engine schema so a bad value is rejected with a reason.
    from config import ThresholdsConfig
    from pydantic import ValidationError

    try:
        validated = ThresholdsConfig(**merged).model_dump()
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()[0]["msg"]) from exc

    tenant.thresholds = validated
    db.add(tenant)
    db.commit()
    return validated
