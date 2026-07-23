"""Backend settings, loaded from environment / .env.

PostgreSQL is the production database. On machines without Postgres (like the
current dev laptop) DATABASE_URL falls back to a local SQLite file so the whole
product still runs — switching to Postgres is just setting DATABASE_URL, e.g.:

    DATABASE_URL=postgresql+psycopg://ops:secret@localhost:5432/ops_monitoring

SECURITY: SECRET_KEY signs the JWTs and ENCRYPTION_KEY encrypts stored API
keys / CM credentials. Both get generated into .env on first run if missing —
fine for dev; set real values in production.
"""

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Cloudera Ops Monitoring"
    debug: bool = False

    # --- database ---
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'backend' / 'ops.db'}"

    # --- auth ---
    secret_key: str = ""                      # JWT signing key (generated if empty)
    access_token_minutes: int = 30
    refresh_token_days: int = 7

    # --- secrets at rest ---
    encryption_key: str = ""                  # Fernet key (generated if empty)

    # --- CORS (the React dev server in Phase 2+) ---
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- first-run admin (seed) ---
    # (email-validator rejects reserved TLDs like .local, so use a real domain)
    admin_email: str = "admin@blutechconsulting.com"
    admin_password: str = "ChangeMe!123"

    # --- where the frontend lives (for invite links) ---
    app_base_url: str = "http://localhost:5173"

    # --- SMTP for invite emails (optional; invites work without it) ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@blutechconsulting.com"
    smtp_use_tls: bool = True


def _persist_generated_secret(name: str, value: str) -> None:
    """Append a generated secret to .env so it survives restarts (a new key on
    every boot would invalidate all sessions and make stored secrets
    undecryptable)."""
    line = f"\n{name}={value}\n"
    with ENV_FILE.open("a", encoding="utf-8") as f:
        f.write(line)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key:
        settings.secret_key = secrets.token_urlsafe(48)
        _persist_generated_secret("SECRET_KEY", settings.secret_key)
    if not settings.encryption_key:
        from cryptography.fernet import Fernet

        settings.encryption_key = Fernet.generate_key().decode("ascii")
        _persist_generated_secret("ENCRYPTION_KEY", settings.encryption_key)
    return settings
