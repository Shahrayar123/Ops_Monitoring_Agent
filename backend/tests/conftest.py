"""Backend test setup: every test run gets a fresh in-memory-style SQLite DB
(a temp file), seeded with one admin + one plan, and a TestClient wired to it.

The get_db dependency is overridden so tests never touch the real dev database.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.security import hash_password
from backend.app.db.base import Base, get_db
from backend.app.db.models import Plan, Role, Tenant, User
from backend.app.main import app

# Note: email-validator rejects reserved TLDs like .local/.test — use a
# real-shaped domain for test accounts.
ADMIN_EMAIL = "admin@blutechconsulting.com"
ADMIN_PASSWORD = "AdminPass!123"
USER_EMAIL = "user@blutechconsulting.com"
USER_PASSWORD = "UserPass!123"


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    session = TestingSession()
    plan = Plan(
        name="Test Plan",
        allowed_models=["qwen2.5:7b"],
        max_context_tokens=4096,
        allowed_cloudera_versions=["7.1.9"],
        daily_api_limit=10,
        monthly_api_limit=100,
    )
    session.add(plan)
    session.add(User(
        email=ADMIN_EMAIL, full_name="Test Admin",
        password_hash=hash_password(ADMIN_PASSWORD), role=Role.ADMIN, plan=plan,
    ))
    session.commit()

    yield TestingSession
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        db = db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_tokens(client):
    resp = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture()
def user_tokens(client):
    resp = client.post(
        "/auth/register",
        json={"email": USER_EMAIL, "password": USER_PASSWORD, "full_name": "Test User"},
    )
    assert resp.status_code == 201, resp.text
    resp = client.post("/auth/login", json={"email": USER_EMAIL, "password": USER_PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()


def auth_header(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture()
def export_tenant(db_session):
    """A json-mode tenant pointing at the real bdaktprod export folder if present,
    else skips — so the suite runs on any checkout."""
    data_dir = REPO_ROOT / "data" / "bdaktprod"
    if not (data_dir / "hosts").is_dir():
        pytest.skip("bdaktprod export data not present in this checkout")
    session = db_session()
    tenant = Tenant(
        slug="bdaktprod",
        display_name="BDA KT Production",
        cluster_name="bdaktprod-cluster",
        cloudera_version="7.1.9",
        data_source_mode="json",
        data_dir=str(data_dir),
        thresholds={"disk_mounts": [f"/u{n:02d}" for n in range(1, 17)] + ["/var", "/opt", "/home", "/tmp"],
                    "heartbeat_window_sec": 1800},
    )
    session.add(tenant)
    session.commit()
    session.close()
    return "bdaktprod"
