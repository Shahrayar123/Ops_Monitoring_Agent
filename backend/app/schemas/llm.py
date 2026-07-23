"""Request/response shapes for models, keys, usage, and plans."""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class ModelOut(BaseModel):
    id: str
    label: str
    provider: str
    provider_label: str
    context_tokens: int
    needs_key: bool
    notes: str
    allowed: bool          # is this model in the user's plan?
    key_ready: bool        # does the user have a key for it (or is it keyless)?


class ProviderKeyOut(BaseModel):
    provider: str
    provider_label: str
    configured: bool
    masked_key: Optional[str] = None


class SetApiKeyRequest(BaseModel):
    provider: str
    api_key: str = Field(min_length=8, max_length=400)


class SelectModelRequest(BaseModel):
    model_id: str


class SetPriorityRequest(BaseModel):
    # Ordered fallback chain: [0] is the default. Max 3 (validated in the route).
    model_ids: list[str] = Field(default_factory=list, max_length=3)


class OllamaUrlRequest(BaseModel):
    url: str = Field(min_length=3, max_length=300)


class TestModelRequest(BaseModel):
    model_id: str


class LlmSettingsOut(BaseModel):
    model_priority: list[str]          # the user's fallback chain ([0] = default)
    ollama_base_url: str
    models: list[ModelOut]
    providers: list[ProviderKeyOut]
    usage: "UsageOut"
    limits_note: str = "Usage limits are set by your administrator."


class UsageOut(BaseModel):
    used_today: int
    used_month: int
    daily_limit: int
    monthly_limit: int
    tokens_today: int
    tokens_month: int
    daily_token_limit: int
    monthly_token_limit: int


# --- admin: plans ---


class PlanUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    allowed_models: list[str] = []
    max_context_tokens: int = Field(default=8192, ge=256)
    allowed_cloudera_versions: list[str] = []
    daily_api_limit: int = Field(default=0, ge=0)
    monthly_api_limit: int = Field(default=0, ge=0)
    is_active: bool = True


class AssignPlanRequest(BaseModel):
    plan_id: int


class SetUserClustersRequest(BaseModel):
    """The complete set of clusters a user should have access to — replaces
    whatever was there before (add missing links, remove ones not listed)."""

    tenant_slugs: list[str] = []


# --- admin: per-user access & invites ---


class UserAccessUpdate(BaseModel):
    """The complete per-user access override the admin sets. Nulls mean 'inherit
    from the plan'; 0 means 'unlimited'; an empty allowed_models inherits too."""

    allowed_models: list[str] = []
    model_priority: Optional[list[str]] = None
    daily_call_limit: Optional[int] = Field(default=None, ge=0)
    monthly_call_limit: Optional[int] = Field(default=None, ge=0)
    daily_token_limit: Optional[int] = Field(default=None, ge=0)
    monthly_token_limit: Optional[int] = Field(default=None, ge=0)


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(default="", max_length=255)
    role: str = Field(default="user", pattern=r"^(user|admin)$")
    plan_id: Optional[int] = None
    allowed_models: list[str] = []
    daily_call_limit: Optional[int] = Field(default=None, ge=0)
    monthly_call_limit: Optional[int] = Field(default=None, ge=0)
    daily_token_limit: Optional[int] = Field(default=None, ge=0)
    monthly_token_limit: Optional[int] = Field(default=None, ge=0)
    # Clusters to grant this user access to immediately (by Tenant.slug).
    # Admins implicitly see every cluster regardless of this list.
    tenant_slugs: list[str] = []


class InviteResult(BaseModel):
    user_id: int
    email: str
    temp_password: str          # shown ONCE to the admin to share
    invite_link: str
    emailed: bool               # whether an email actually went out (SMTP configured)
    message: str


class AdminUserDetail(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    must_change_password: bool
    plan_id: Optional[int]
    plan_name: Optional[str]
    # raw per-user overrides (null/empty = inherit from plan)
    allowed_models: list[str]
    model_priority: list[str]
    daily_call_limit: Optional[int]
    monthly_call_limit: Optional[int]
    daily_token_limit: Optional[int]
    monthly_token_limit: Optional[int]
    # resolved effective values (what actually applies)
    effective_allowed_models: list[str]
    effective_daily_calls: int
    effective_monthly_calls: int
    effective_daily_tokens: int
    effective_monthly_tokens: int

