"""Phase 1 acceptance tests: registration, login, tokens, roles, error shape."""

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD, USER_EMAIL, USER_PASSWORD, auth_header


# ---------- health & error envelope ----------


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_errors_use_the_standard_envelope_with_request_id(client):
    resp = client.get("/auth/me")  # no token
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["request_id"]
    assert resp.headers["X-Request-ID"] == body["error"]["request_id"]


def test_validation_errors_are_readable(client):
    resp = client.post("/auth/register", json={"email": "not-an-email", "password": "short"})
    assert resp.status_code == 422
    msg = resp.json()["error"]["message"]
    assert "email" in msg and "password" in msg


# ---------- register & login ----------


def test_register_creates_a_user_on_the_default_plan(client):
    resp = client.post(
        "/auth/register",
        json={"email": "new@blutechconsulting.com", "password": "GoodPass!123", "full_name": "New Person"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "user"            # public registration can never mint admins
    assert body["plan"]["name"] == "Test Plan"
    assert "password" not in str(body).lower() or "password_hash" not in body


def test_register_rejects_duplicate_email(client, user_tokens):
    resp = client.post(
        "/auth/register", json={"email": USER_EMAIL, "password": "Whatever!123"}
    )
    assert resp.status_code == 409


def test_login_wrong_password_and_unknown_email_look_identical(client):
    a = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
    b = client.post("/auth/login", json={"email": "ghost@blutechconsulting.com", "password": "wrong"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


def test_me_returns_the_logged_in_account(client, admin_tokens):
    resp = client.get("/auth/me", headers=auth_header(admin_tokens))
    assert resp.status_code == 200
    assert resp.json()["email"] == ADMIN_EMAIL
    assert resp.json()["role"] == "admin"


# ---------- refresh & logout ----------


def test_refresh_rotates_the_token_pair(client, admin_tokens):
    resp = client.post("/auth/refresh", json={"refresh_token": admin_tokens["refresh_token"]})
    assert resp.status_code == 200
    fresh = resp.json()
    assert fresh["access_token"] != admin_tokens["access_token"]

    # The used refresh token is revoked — replaying it must fail.
    replay = client.post("/auth/refresh", json={"refresh_token": admin_tokens["refresh_token"]})
    assert replay.status_code == 401


def test_logout_revokes_the_refresh_token(client, admin_tokens):
    resp = client.post("/auth/logout", json={"refresh_token": admin_tokens["refresh_token"]})
    assert resp.status_code == 204
    resp = client.post("/auth/refresh", json={"refresh_token": admin_tokens["refresh_token"]})
    assert resp.status_code == 401


def test_an_access_token_cannot_be_used_as_a_refresh_token(client, admin_tokens):
    resp = client.post("/auth/refresh", json={"refresh_token": admin_tokens["access_token"]})
    assert resp.status_code == 401


# ---------- roles ----------


def test_admin_endpoints_reject_normal_users(client, user_tokens):
    resp = client.get("/admin/users", headers=auth_header(user_tokens))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_admin_endpoints_work_for_admins(client, admin_tokens):
    resp = client.get("/admin/users", headers=auth_header(admin_tokens))
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert ADMIN_EMAIL in emails

    resp = client.get("/admin/plans", headers=auth_header(admin_tokens))
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "Test Plan"


def test_admin_can_disable_and_reenable_a_user(client, admin_tokens, user_tokens):
    users = client.get("/admin/users", headers=auth_header(admin_tokens)).json()
    target = next(u for u in users if u["email"] == USER_EMAIL)

    resp = client.post(
        f"/admin/users/{target['id']}/active",
        params={"is_active": False},
        headers=auth_header(admin_tokens),
    )
    assert resp.status_code == 200 and resp.json()["is_active"] is False

    # Disabled user can no longer log in, and their access token stops working.
    resp = client.post("/auth/login", json={"email": USER_EMAIL, "password": USER_PASSWORD})
    assert resp.status_code == 403
    resp = client.get("/auth/me", headers=auth_header(user_tokens))
    assert resp.status_code == 401

    resp = client.post(
        f"/admin/users/{target['id']}/active",
        params={"is_active": True},
        headers=auth_header(admin_tokens),
    )
    assert resp.json()["is_active"] is True


def test_admin_cannot_disable_their_own_account(client, admin_tokens):
    me = client.get("/auth/me", headers=auth_header(admin_tokens)).json()
    resp = client.post(
        f"/admin/users/{me['id']}/active",
        params={"is_active": False},
        headers=auth_header(admin_tokens),
    )
    assert resp.status_code == 400


# ---------- change password ----------


def test_change_password_flow(client, user_tokens):
    resp = client.post(
        "/auth/change-password",
        json={"current_password": USER_PASSWORD, "new_password": "BrandNew!456"},
        headers=auth_header(user_tokens),
    )
    assert resp.status_code == 204

    assert client.post(
        "/auth/login", json={"email": USER_EMAIL, "password": USER_PASSWORD}
    ).status_code == 401
    assert client.post(
        "/auth/login", json={"email": USER_EMAIL, "password": "BrandNew!456"}
    ).status_code == 200


def test_change_password_requires_the_current_password(client, user_tokens):
    resp = client.post(
        "/auth/change-password",
        json={"current_password": "wrong", "new_password": "BrandNew!456"},
        headers=auth_header(user_tokens),
    )
    assert resp.status_code == 400
