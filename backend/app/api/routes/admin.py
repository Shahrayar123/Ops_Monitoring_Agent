"""Admin-only endpoints — Phase 1 scope: see accounts and plans, activate/
deactivate users. The full admin panel (plans editor, limits, usage charts)
arrives in Phase 4; these endpoints prove the role guard and give the seed
data somewhere to be seen.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...db.models import Plan, User
from ...schemas.auth import PlanOut, UserOut
from ..deps import require_admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: Session = Depends(get_db)) -> list[Plan]:
    return list(db.scalars(select(Plan).order_by(Plan.id)))


@router.post("/users/{user_id}/active", response_model=UserOut)
def set_user_active(
    user_id: int,
    is_active: bool,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"No user with id {user_id}")
    if user.id == admin.id and not is_active:
        raise HTTPException(status_code=400, detail="You can't disable your own account")
    user.is_active = is_active
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
