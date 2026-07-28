"""Admin: plans editor, plan assignment, and usage overview.

    GET    /admin/plans                list plans (also on the read-only admin router)
    POST   /admin/plans                create a plan
    PATCH  /admin/plans/{id}           edit a plan
    DELETE /admin/plans/{id}           delete a plan (if unused)
    POST   /admin/users/{id}/plan      assign a plan to a user
    GET    /admin/usage                per-user usage overview (today / month / tokens)
    GET    /admin/catalog              the model registry + cloudera version list
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...db.models import ApiUsage, Plan, User
from ...llm.registry import PROVIDER_LABELS, all_models
from ...schemas.auth import PlanOut
from ...schemas.llm import AssignPlanRequest, PlanUpsert
from ..deps import require_admin

router = APIRouter(prefix="/admin", tags=["admin:plans"], dependencies=[Depends(require_admin)])


@router.get("/catalog")
def catalog():
    """What plans can grant: the full model registry + a suggested version list."""
    return {
        "models": [
            {"id": m.id, "label": m.label, "provider": m.provider,
             "provider_label": PROVIDER_LABELS.get(m.provider, m.provider),
             "context_tokens": m.context_tokens, "needs_key": m.needs_key}
            for m in all_models()
        ],
        "cloudera_versions": ["7.1.9", "7.1.8", "7.1.7", "7.3.1", "7.2.18"],
    }


@router.post("/plans", response_model=PlanOut, status_code=201)
def create_plan(body: PlanUpsert, db: Session = Depends(get_db)):
    if db.scalar(select(Plan).where(Plan.name == body.name)):
        raise HTTPException(status_code=409, detail=f"A plan named '{body.name}' already exists")
    plan = Plan(**body.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.patch("/plans/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: int, body: PlanUpsert, db: Session = Depends(get_db)):
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    for field, value in body.model_dump().items():
        setattr(plan, field, value)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/plans/{plan_id}", status_code=204)
def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    in_use = db.scalar(select(func.count(User.id)).where(User.plan_id == plan_id))
    if in_use:
        raise HTTPException(status_code=409, detail=f"{in_use} user(s) are on this plan — reassign them first")
    db.delete(plan)
    db.commit()


@router.post("/users/{user_id}/plan", status_code=204)
def assign_plan(user_id: int, body: AssignPlanRequest, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if db.get(Plan, body.plan_id) is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    user.plan_id = body.plan_id
    db.add(user)
    db.commit()


@router.get("/usage")
def usage_overview(db: Session = Depends(get_db)):
    """Per-user usage this day/month — powers the admin usage dashboard."""
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def count(user_id, since):
        return db.scalar(
            select(func.count(ApiUsage.id)).where(
                ApiUsage.user_id == user_id, ApiUsage.success.is_(True), ApiUsage.created_at >= since
            )
        ) or 0

    rows = []
    for user in db.scalars(select(User).order_by(User.id)):
        tokens = db.scalar(
            select(func.coalesce(func.sum(ApiUsage.total_tokens), 0)).where(
                ApiUsage.user_id == user.id, ApiUsage.created_at >= month_start
            )
        ) or 0
        from ...llm.access import effective_limits, effective_priority

        limits = effective_limits(user)
        rows.append({
            "user_id": user.id,
            "email": user.email,
            "plan": user.plan.name if user.plan else None,
            "models": effective_priority(user),  # the user's active model chain
            "used_today": count(user.id, day_start),
            "used_month": count(user.id, month_start),
            "daily_limit": limits.daily_calls,
            "monthly_limit": limits.monthly_calls,
            "tokens_month": int(tokens),
            "daily_token_limit": limits.daily_tokens,
            "monthly_token_limit": limits.monthly_tokens,
        })
    return {"users": rows}
