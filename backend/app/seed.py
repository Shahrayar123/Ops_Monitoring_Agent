"""First-run data: run migrations, then create the default admin, a demo plan,
and the bdaktprod demo tenant (json mode, pointing at the existing export).

    python -m backend.app.seed        (from the repo root)

Idempotent — safe to run again; existing rows are left alone.
"""

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.core.security import hash_password
from backend.app.db.base import SessionLocal, engine
from backend.app.db.models import Plan, Role, Tenant, User, UserTenant


def _bdaktprod_thresholds() -> dict:
    """Reuse the real bdaktprod thresholds (the 20 disk mounts, 1800s heartbeat,
    ...) from its existing engine YAML, so the DB tenant matches the cluster."""
    try:
        from config import load_tenant_config

        cfg = load_tenant_config(str(REPO_ROOT / "config" / "tenants" / "bdaktprod.yaml"))
        return cfg.thresholds.model_dump()
    except Exception as exc:  # YAML not present in some deployments — fall back to defaults
        log.warning("Could not load bdaktprod thresholds from YAML (%s); using defaults.", exc)
        return {}

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("seed")


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "alembic"))
    command.upgrade(cfg, "head")


def seed() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        # --- demo plan ---
        plan = db.scalar(select(Plan).where(Plan.name == "Demo"))
        if plan is None:
            plan = Plan(
                name="Demo",
                description="Evaluation plan: local model, standard limits.",
                allowed_models=["qwen2.5:7b", "gpt-4o-mini", "claude-sonnet-5", "gemini-2.0-flash", "grok-3-mini"],
                max_context_tokens=8192,
                allowed_cloudera_versions=["7.1.9", "7.1.7", "7.3.1"],
                daily_api_limit=50,
                monthly_api_limit=500,
            )
            db.add(plan)
            log.info("Created plan 'Demo'")

        # --- admin account ---
        admin = db.scalar(select(User).where(User.email == settings.admin_email))
        if admin is None:
            admin = User(
                email=settings.admin_email,
                full_name="Administrator",
                password_hash=hash_password(settings.admin_password),
                role=Role.ADMIN,
                plan=plan,
            )
            db.add(admin)
            log.info("Created admin account %s", settings.admin_email)

        # --- demo tenant: the real bdaktprod export ---
        tenant = db.scalar(select(Tenant).where(Tenant.slug == "bdaktprod"))
        if tenant is None:
            tenant = Tenant(
                slug="bdaktprod",
                display_name="BDA KT Production",
                cluster_name="bdaktprod-cluster",
                cloudera_version="7.1.9",
                data_source_mode="json",
                data_dir=str(REPO_ROOT / "data" / "bdaktprod"),
                thresholds=_bdaktprod_thresholds(),
            )
            db.add(tenant)
            log.info("Created demo tenant 'bdaktprod' (json mode)")
        elif not tenant.thresholds:
            # Backfill thresholds for a tenant seeded before they were populated.
            tenant.thresholds = _bdaktprod_thresholds()
            log.info("Backfilled bdaktprod thresholds from YAML")

        db.flush()
        if not db.scalar(
            select(UserTenant).where(
                UserTenant.user_id == admin.id, UserTenant.tenant_id == tenant.id
            )
        ):
            db.add(UserTenant(user_id=admin.id, tenant_id=tenant.id))

        db.commit()
        log.info("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    log.info("Database: %s", get_settings().database_url)
    run_migrations()
    seed()
