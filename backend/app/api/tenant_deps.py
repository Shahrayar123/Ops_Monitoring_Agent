"""Resolve a tenant from the URL and enforce access.

Admins see every tenant. Normal users see only tenants linked to them via
user_tenants. Both come through get_tenant_or_404, which 404s unknown slugs and
403s tenants the user isn't allowed to see.
"""

from fastapi import Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.base import get_db
from ..db.models import Role, Tenant, User, UserTenant
from .deps import get_current_user


def get_tenant_or_404(
    slug: str = Path(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"No cluster named '{slug}'")

    if user.role != Role.ADMIN:
        linked = db.scalar(
            select(UserTenant).where(
                UserTenant.user_id == user.id, UserTenant.tenant_id == tenant.id
            )
        )
        if not linked:
            raise HTTPException(status_code=403, detail="You don't have access to this cluster")
    return tenant
