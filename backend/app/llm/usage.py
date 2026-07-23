"""Metering: record model calls and enforce a plan's daily/monthly limits.

A limit of 0 means unlimited. Windows are calendar-based (UTC): "today" and
"this month". Enforcement counts only successful, billable calls so a failed
key test doesn't burn a user's quota.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import ApiUsage, User
from .access import effective_limits
from .providers import ChatResult


def record(db: Session, user: User, model_id: str, provider: str, kind: str, result: ChatResult | None, success: bool) -> ApiUsage:
    row = ApiUsage(
        user_id=user.id,
        model_id=model_id,
        provider=provider,
        kind=kind,
        prompt_tokens=result.prompt_tokens if result else 0,
        completion_tokens=result.completion_tokens if result else 0,
        total_tokens=result.total_tokens if result else 0,
        latency_ms=result.latency_ms if result else 0,
        success=success,
    )
    db.add(row)
    db.commit()
    return row


def _count_since(db: Session, user_id: int, since: datetime) -> int:
    return db.scalar(
        select(func.count(ApiUsage.id)).where(
            ApiUsage.user_id == user_id,
            ApiUsage.success.is_(True),
            ApiUsage.created_at >= since,
        )
    ) or 0


def _tokens_since(db: Session, user_id: int, since: datetime) -> int:
    return int(db.scalar(
        select(func.coalesce(func.sum(ApiUsage.total_tokens), 0)).where(
            ApiUsage.user_id == user_id,
            ApiUsage.created_at >= since,
        )
    ) or 0)


def _day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@dataclass
class UsageStatus:
    used_today: int          # calls today
    used_month: int          # calls this month
    daily_limit: int         # 0 = unlimited (effective)
    monthly_limit: int
    tokens_today: int
    tokens_month: int
    daily_token_limit: int   # 0 = unlimited (effective)
    monthly_token_limit: int


def status_for(db: Session, user: User) -> UsageStatus:
    limits = effective_limits(user)
    return UsageStatus(
        used_today=_count_since(db, user.id, _day_start()),
        used_month=_count_since(db, user.id, _month_start()),
        daily_limit=limits.daily_calls,
        monthly_limit=limits.monthly_calls,
        tokens_today=_tokens_since(db, user.id, _day_start()),
        tokens_month=_tokens_since(db, user.id, _month_start()),
        daily_token_limit=limits.daily_tokens,
        monthly_token_limit=limits.monthly_tokens,
    )


class LimitExceeded(Exception):
    """The user has hit a daily/monthly call OR token limit."""


def check_limit(db: Session, user: User) -> None:
    """Raise LimitExceeded if the user is at or over any effective limit (calls
    or tokens, day or month). Call BEFORE a billable model call."""
    s = status_for(db, user)
    if s.daily_limit and s.used_today >= s.daily_limit:
        raise LimitExceeded(f"Daily call limit reached ({s.daily_limit}/day). Resets at 00:00 UTC — or ask an admin to raise it.")
    if s.monthly_limit and s.used_month >= s.monthly_limit:
        raise LimitExceeded(f"Monthly call limit reached ({s.monthly_limit}/month). Ask an admin to raise it.")
    if s.daily_token_limit and s.tokens_today >= s.daily_token_limit:
        raise LimitExceeded(f"Daily token limit reached ({s.daily_token_limit:,}/day). Resets at 00:00 UTC — or ask an admin to raise it.")
    if s.monthly_token_limit and s.tokens_month >= s.monthly_token_limit:
        raise LimitExceeded(f"Monthly token limit reached ({s.monthly_token_limit:,}/month). Ask an admin to raise it.")
