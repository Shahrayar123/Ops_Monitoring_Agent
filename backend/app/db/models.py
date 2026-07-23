"""The product's tables.

Naming/typing rules:
- Portable column types only (JSON, String, DateTime) so PostgreSQL and the
  SQLite dev fallback run the exact same schema.
- Secrets (CM passwords, LLM API keys) are stored ONLY in *_encrypted columns,
  written through core/crypto.py — never plain text.
- Plans are the commercial knob: which models a customer may use, their context
  budget, allowed Cloudera versions, and daily/monthly AI-call limits.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    """SQLite (used in tests/dev fallback) drops tzinfo on round-trip even for
    DateTime(timezone=True) columns; Postgres doesn't. Normalize either case to
    UTC-aware so arithmetic against utcnow() is always safe."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class Role:
    """Role names — a str column, not a table; two roles don't need a join."""

    ADMIN = "admin"
    USER = "user"
    ALL = (ADMIN, USER)


class AccountStatus:
    """The account-lifecycle states, derived (never stored) from the User
    timestamp columns below — see User.account_status. Keeping this as a pure
    function of timestamps means there's one source of truth and nothing can
    drift out of sync with a separately-persisted status enum."""

    ACTIVE = "active"
    DELETION_REQUESTED = "deletion_requested"    # user asked to close their account; admin hasn't reviewed it yet
    DELETED_RECOVERABLE = "deleted_recoverable"  # admin accepted the request; soft-deleted, inside the grace window
    RECOVERY_REQUESTED = "recovery_requested"    # user asked to be restored; admin hasn't reviewed it yet
    DORMANT = "dormant"                          # grace window elapsed with no recovery — permanently shut down


RECOVERY_WINDOW = timedelta(days=30)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=Role.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    plan: Mapped["Plan | None"] = relationship(back_populates="users")

    # Force a password change on next login (set for admin-invited accounts).
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- per-user LLM access (admin-controlled; overrides the plan when set) ---
    # allowed_models: which models THIS user may use. Empty = inherit from plan.
    allowed_models: Mapped[list] = mapped_column(JSON, default=list)
    # model_priority: the user's own fallback chain (<=3 ids); [0] is the default.
    model_priority: Mapped[list] = mapped_column(JSON, default=list)
    # Limit overrides (NULL = inherit from plan). Calls and tokens, day and month.
    daily_call_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_call_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # --- account lifecycle (see AccountStatus) — a soft-delete with a 30-day
    # recovery window, entirely derived from these four timestamps. ---
    # Self-service deletion request: set when the user asks to close their own
    # account; an admin reviews it (accept -> deleted_at, or reject -> cleared).
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when an admin accepts a deletion request: the account is soft-deleted
    # (is_active flips False) but stays recoverable until RECOVERY_WINDOW elapses.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when a soft-deleted user asks to be restored; an admin reviews it
    # (approve -> account reactivated and all four timestamps cleared, or
    # reject -> cleared, account stays deleted-recoverable).
    recovery_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenants: Mapped[list["UserTenant"]] = relationship(back_populates="user")

    @property
    def account_status(self) -> str:
        if self.deleted_at is None:
            return AccountStatus.DELETION_REQUESTED if self.deletion_requested_at else AccountStatus.ACTIVE
        if utcnow() - _as_aware(self.deleted_at) >= RECOVERY_WINDOW:
            return AccountStatus.DORMANT
        return AccountStatus.RECOVERY_REQUESTED if self.recovery_requested_at else AccountStatus.DELETED_RECOVERABLE

    @property
    def recoverable_until(self) -> "datetime | None":
        return _as_aware(self.deleted_at) + RECOVERY_WINDOW if self.deleted_at else None


class Plan(Base):
    """A customer plan: what the subscription allows."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")

    # LLM entitlements
    allowed_models: Mapped[list] = mapped_column(JSON, default=list)      # model registry ids
    max_context_tokens: Mapped[int] = mapped_column(Integer, default=8192)

    # Cloudera entitlements
    allowed_cloudera_versions: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["7.1.9"]

    # AI usage limits (0 = unlimited) — plan defaults, overridable per user.
    daily_api_limit: Mapped[int] = mapped_column(Integer, default=0)    # calls/day
    monthly_api_limit: Mapped[int] = mapped_column(Integer, default=0)  # calls/month
    daily_token_limit: Mapped[int] = mapped_column(Integer, default=0)
    monthly_token_limit: Mapped[int] = mapped_column(Integer, default=0)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    users: Mapped[list[User]] = relationship(back_populates="plan")


class Tenant(Base):
    """One monitored cluster. `data_source_mode` is the admin's choice of how
    this customer's data arrives: uploaded export files first, live API later."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)  # e.g. "bdaktprod"
    display_name: Mapped[str] = mapped_column(String(255))
    cluster_name: Mapped[str] = mapped_column(String(255))
    cloudera_version: Mapped[str] = mapped_column(String(50), default="")

    data_source_mode: Mapped[str] = mapped_column(String(10), default="json")  # json | api

    # json mode: folder holding this tenant's uploaded/export files
    data_dir: Mapped[str] = mapped_column(String(500), default="")

    # api mode: connection details (password encrypted at rest)
    cm_host: Mapped[str] = mapped_column(String(255), default="")
    cm_port: Mapped[int] = mapped_column(Integer, default=7183)
    cm_use_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    cm_username: Mapped[str] = mapped_column(String(255), default="")
    cm_password_encrypted: Mapped[str] = mapped_column(Text, default="")

    # per-check thresholds & refresh rates (JSON blobs; schema-validated in the API)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    refresh_rates: Mapped[dict] = mapped_column(JSON, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    files: Mapped[list["TenantFile"]] = relationship(back_populates="tenant")
    users: Mapped[list["UserTenant"]] = relationship(back_populates="tenant")


class TenantFile(Base):
    """One uploaded Cloudera export file for a json-mode tenant."""

    __tablename__ = "tenant_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    file_type: Mapped[str] = mapped_column(String(50))     # hosts | cpu | ram | disk | ...
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    validation_status: Mapped[str] = mapped_column(String(20), default="pending")  # ok | failed
    validation_detail: Mapped[str] = mapped_column(Text, default="")
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tenant: Mapped[Tenant] = relationship(back_populates="files")


class UserTenant(Base):
    """Which users can see which clusters."""

    __tablename__ = "user_tenants"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)

    user: Mapped[User] = relationship(back_populates="tenants")
    tenant: Mapped[Tenant] = relationship(back_populates="users")


class UserKpiRefreshRate(Base):
    """Per-user override of a KPI card's auto-refresh cadence. `task` is one of
    the nine check ids (e.g. "cpu_percent"); applies across every cluster this
    user can see — not per-cluster, since the ask is "refresh time per KPI
    metric" for the user, not per (user, cluster, metric) triple. Missing row
    for a task means "use the cluster's own refresh_rates / engine default"."""

    __tablename__ = "user_kpi_refresh_rates"
    __table_args__ = (UniqueConstraint("user_id", "task"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task: Mapped[str] = mapped_column(String(50))
    interval_seconds: Mapped[int] = mapped_column(Integer)


class UserSetting(Base):
    """Per-user settings, one row per key (selected model, Ollama URL, API keys).
    Secret values go in value_encrypted; plain ones in value."""

    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("user_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(Text, default="")
    value_encrypted: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ApiUsage(Base):
    """One AI/model call — the metering ledger behind plan limits and the usage
    dashboards. `kind` distinguishes a connection test from a real analysis."""

    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    model_id: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20), default="analysis")  # analysis | test
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class RevokedToken(Base):
    """Refresh-token ids (jti) that logout has revoked. Checked on every
    refresh; expired rows can be purged by a maintenance job."""

    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
