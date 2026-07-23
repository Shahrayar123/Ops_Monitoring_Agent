"""Per-user KPI card refresh-rate overrides.

    GET    /settings/kpi-refresh            this user's effective rate for all nine checks
    PUT    /settings/kpi-refresh            set (or update) the override for one check
    DELETE /settings/kpi-refresh/{task}     clear the override -> falls back to the cluster/engine default

A user only sees this in Settings once they have at least one assigned
cluster (frontend checks GET /tenants); the setting itself has no cluster
dimension — it's "how often should MY cpu_percent card refresh", applied
across every cluster this user can see, not per (user, cluster) pair.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...db.models import UserKpiRefreshRate
from ...engine.bridge import DEFAULT_REFRESH_RATES
from ...schemas.kpi import KpiRefreshRateOut, SetKpiRefreshRateRequest
from ..deps import get_current_user

router = APIRouter(prefix="/settings/kpi-refresh", tags=["settings"])


def _overrides_for(db: Session, user_id: int) -> dict[str, int]:
    rows = db.scalars(select(UserKpiRefreshRate).where(UserKpiRefreshRate.user_id == user_id))
    return {r.task: r.interval_seconds for r in rows}


def _rates_out(db: Session, user_id: int) -> list[KpiRefreshRateOut]:
    overrides = _overrides_for(db, user_id)
    return [
        KpiRefreshRateOut(
            task=task, default_seconds=default,
            seconds=overrides.get(task, default),
            is_override=task in overrides,
        )
        for task, default in DEFAULT_REFRESH_RATES.items()
    ]


@router.get("", response_model=list[KpiRefreshRateOut])
def get_kpi_refresh_rates(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return _rates_out(db, user.id)


@router.put("", response_model=list[KpiRefreshRateOut])
def set_kpi_refresh_rate(body: SetKpiRefreshRateRequest, user=Depends(get_current_user), db: Session = Depends(get_db)):
    if body.task not in DEFAULT_REFRESH_RATES:
        raise HTTPException(status_code=404, detail=f"Unknown KPI check '{body.task}'")

    row = db.scalar(
        select(UserKpiRefreshRate).where(UserKpiRefreshRate.user_id == user.id, UserKpiRefreshRate.task == body.task)
    )
    if row is None:
        db.add(UserKpiRefreshRate(user_id=user.id, task=body.task, interval_seconds=body.seconds))
    else:
        row.interval_seconds = body.seconds
        db.add(row)
    db.commit()
    return _rates_out(db, user.id)


@router.delete("/{task}", response_model=list[KpiRefreshRateOut])
def reset_kpi_refresh_rate(task: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    if task not in DEFAULT_REFRESH_RATES:
        raise HTTPException(status_code=404, detail=f"Unknown KPI check '{task}'")
    db.execute(
        UserKpiRefreshRate.__table__.delete().where(
            UserKpiRefreshRate.user_id == user.id, UserKpiRefreshRate.task == task
        )
    )
    db.commit()
    return _rates_out(db, user.id)
