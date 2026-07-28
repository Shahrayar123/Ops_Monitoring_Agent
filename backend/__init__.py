"""The product backend: FastAPI + PostgreSQL.

Layout:
    app/core/    settings, security (JWT/bcrypt), crypto (Fernet), error handling
    app/db/      SQLAlchemy engine/session and the table models
    app/schemas/ Pydantic request/response shapes
    app/api/     route handlers + auth dependencies
    app/seed.py  first-run data (admin account, demo plan, demo tenant)

The monitoring engine (checks/, data_sources/, config/, cloudera/) stays at the
repo root and is imported by this backend. AI analysis lives in app/ai/ and
app/llm/, on top of the engine's deterministic checks.
"""
