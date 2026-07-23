"""Request/response shapes for auth and account endpoints."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RecoverAccountRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    allowed_models: list
    max_context_tokens: int
    allowed_cloudera_versions: list
    daily_api_limit: int
    monthly_api_limit: int
    is_active: bool = True


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: str
    is_active: bool
    must_change_password: bool = False
    created_at: datetime
    plan: Optional[PlanOut] = None
    deletion_requested_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    recovery_requested_at: Optional[datetime] = None
    account_status: str = "active"
    recoverable_until: Optional[datetime] = None
