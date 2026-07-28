"""Resolve a user's EFFECTIVE LLM access.

Per-user settings (admin-controlled) override the plan; the plan is the default
when a user field is unset. This one place decides, for any user:

    which models they may use   (allowed_models)
    their day/month call limit   (0 = unlimited)
    their day/month token limit  (0 = unlimited)

Everything else — settings, usage enforcement, admin views, Phase 5 — reads
from here, so the override/fallback rule is defined exactly once.
"""

from dataclasses import dataclass

from ..db.models import User
from .registry import get_model


def effective_allowed_models(user: User) -> list[str]:
    """The model ids this user may use. Per-user list wins; else the plan's."""
    if user.allowed_models:
        allowed = list(user.allowed_models)
    elif user.plan and user.plan.allowed_models:
        allowed = list(user.plan.allowed_models)
    else:
        allowed = []
    # Drop any ids no longer in the registry so stale config can't break things.
    return [m for m in allowed if get_model(m)]


@dataclass
class EffectiveLimits:
    daily_calls: int      # 0 = unlimited
    monthly_calls: int
    daily_tokens: int
    monthly_tokens: int


def _pick(user_value, plan_value) -> int:
    if user_value is not None:
        return user_value
    return plan_value or 0


def effective_limits(user: User) -> EffectiveLimits:
    plan = user.plan
    return EffectiveLimits(
        daily_calls=_pick(user.daily_call_limit, plan.daily_api_limit if plan else 0),
        monthly_calls=_pick(user.monthly_call_limit, plan.monthly_api_limit if plan else 0),
        daily_tokens=_pick(user.daily_token_limit, plan.daily_token_limit if plan else 0),
        monthly_tokens=_pick(user.monthly_token_limit, plan.monthly_token_limit if plan else 0),
    )


def effective_priority(user: User) -> list[str]:
    """The user's fallback chain, filtered to models they're still allowed and
    that still exist — so a revoked model silently drops out of the chain."""
    allowed = set(effective_allowed_models(user))
    return [m for m in (user.model_priority or []) if m in allowed][:3]
