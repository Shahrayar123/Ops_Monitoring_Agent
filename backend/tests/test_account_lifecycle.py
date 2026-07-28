"""Account deletion lifecycle: self-service request -> admin accept/reject ->
soft-delete with a 30-day recovery window -> self-service recovery request ->
admin approve/reject -> dormant once the window elapses unreviewed.
"""

from datetime import datetime, timedelta, timezone

from backend.app.db.models import User
from .conftest import auth_header


def _get_user(client, admin_tokens, email):
    users = client.get("/admin/users", headers=auth_header(admin_tokens)).json()
    return next(u for u in users if u["email"] == email)


def _invite(client, admin_tokens, email):
    return client.post("/admin/users/create", json={"email": email, "role": "user"},
                        headers=auth_header(admin_tokens)).json()


def test_full_deletion_review_and_recovery_cycle(client, admin_tokens):
    created = _invite(client, admin_tokens, "lifecycle@blutechconsulting.com")
    login = client.post("/auth/login", json={"email": "lifecycle@blutechconsulting.com", "password": created["temp_password"]})
    utoken = {"access_token": login.json()["access_token"]}

    # 1. user requests deletion
    r = client.post("/auth/request-deletion", headers=auth_header(utoken))
    assert r.status_code == 200
    assert r.json()["account_status"] == "deletion_requested"

    # 2. admin sees it, accepts -> soft-deleted, recoverable
    u = _get_user(client, admin_tokens, "lifecycle@blutechconsulting.com")
    assert u["account_status"] == "deletion_requested"
    r = client.post(f"/admin/users/{u['id']}/deletion/accept", headers=auth_header(admin_tokens))
    assert r.status_code == 200
    body = r.json()
    assert body["account_status"] == "deleted_recoverable"
    assert body["is_active"] is False
    assert body["recoverable_until"] is not None

    # can't log in anymore, but gets a distinct "deleted, can recover" message
    bad_login = client.post("/auth/login", json={"email": "lifecycle@blutechconsulting.com", "password": created["temp_password"]})
    assert bad_login.status_code == 403
    assert "deleted" in bad_login.json()["error"]["message"].lower()

    # accepting again is a no-op guard, not a crash
    assert client.post(f"/admin/users/{u['id']}/deletion/accept", headers=auth_header(admin_tokens)).status_code == 400

    # 3. user requests recovery (public endpoint, proves identity via password)
    r = client.post("/auth/recover", json={"email": "lifecycle@blutechconsulting.com", "password": created["temp_password"]})
    assert r.status_code == 200

    u = _get_user(client, admin_tokens, "lifecycle@blutechconsulting.com")
    assert u["account_status"] == "recovery_requested"

    # 4. admin approves -> fully restored
    r = client.post(f"/admin/users/{u['id']}/recovery/approve", headers=auth_header(admin_tokens))
    assert r.status_code == 200
    body = r.json()
    assert body["account_status"] == "active"
    assert body["is_active"] is True
    assert body["deleted_at"] is None
    assert body["deletion_requested_at"] is None

    # user can log in normally again
    good_login = client.post("/auth/login", json={"email": "lifecycle@blutechconsulting.com", "password": created["temp_password"]})
    assert good_login.status_code == 200


def test_admin_can_reject_deletion_request(client, admin_tokens):
    created = _invite(client, admin_tokens, "rejectdel@blutechconsulting.com")
    login = client.post("/auth/login", json={"email": "rejectdel@blutechconsulting.com", "password": created["temp_password"]})
    utoken = {"access_token": login.json()["access_token"]}
    client.post("/auth/request-deletion", headers=auth_header(utoken))

    u = _get_user(client, admin_tokens, "rejectdel@blutechconsulting.com")
    r = client.post(f"/admin/users/{u['id']}/deletion/reject", headers=auth_header(admin_tokens))
    assert r.status_code == 200
    body = r.json()
    assert body["account_status"] == "active"
    assert body["is_active"] is True

    # account is untouched — still logs in fine
    good_login = client.post("/auth/login", json={"email": "rejectdel@blutechconsulting.com", "password": created["temp_password"]})
    assert good_login.status_code == 200

    # rejecting again is a no-op guard (nothing pending anymore)
    assert client.post(f"/admin/users/{u['id']}/deletion/reject", headers=auth_header(admin_tokens)).status_code == 400


def test_admin_can_reject_recovery_request(client, admin_tokens):
    created = _invite(client, admin_tokens, "rejectrec@blutechconsulting.com")
    login = client.post("/auth/login", json={"email": "rejectrec@blutechconsulting.com", "password": created["temp_password"]})
    utoken = {"access_token": login.json()["access_token"]}
    client.post("/auth/request-deletion", headers=auth_header(utoken))

    u = _get_user(client, admin_tokens, "rejectrec@blutechconsulting.com")
    client.post(f"/admin/users/{u['id']}/deletion/accept", headers=auth_header(admin_tokens))
    client.post("/auth/recover", json={"email": "rejectrec@blutechconsulting.com", "password": created["temp_password"]})

    u2 = _get_user(client, admin_tokens, "rejectrec@blutechconsulting.com")
    assert u2["account_status"] == "recovery_requested"

    r = client.post(f"/admin/users/{u2['id']}/recovery/reject", headers=auth_header(admin_tokens))
    assert r.status_code == 200
    body = r.json()
    assert body["account_status"] == "deleted_recoverable"  # still soft-deleted, just no longer pending
    assert body["is_active"] is False

    # rejecting again is a no-op guard (nothing pending anymore)
    assert client.post(f"/admin/users/{u2['id']}/recovery/reject", headers=auth_header(admin_tokens)).status_code == 400


def test_admin_can_restore_directly_without_a_recovery_request(client, admin_tokens):
    """Admin shouldn't have to wait on the user's self-service recovery
    request — e.g. after a phone call, they can restore a deleted_recoverable
    account straight away."""
    created = _invite(client, admin_tokens, "directrestore@blutechconsulting.com")
    login = client.post("/auth/login", json={"email": "directrestore@blutechconsulting.com", "password": created["temp_password"]})
    utoken = {"access_token": login.json()["access_token"]}
    client.post("/auth/request-deletion", headers=auth_header(utoken))

    u = _get_user(client, admin_tokens, "directrestore@blutechconsulting.com")
    client.post(f"/admin/users/{u['id']}/deletion/accept", headers=auth_header(admin_tokens))
    u2 = _get_user(client, admin_tokens, "directrestore@blutechconsulting.com")
    assert u2["account_status"] == "deleted_recoverable"  # no recovery request yet

    r = client.post(f"/admin/users/{u2['id']}/recovery/approve", headers=auth_header(admin_tokens))
    assert r.status_code == 200
    body = r.json()
    assert body["account_status"] == "active"
    assert body["is_active"] is True

    good_login = client.post("/auth/login", json={"email": "directrestore@blutechconsulting.com", "password": created["temp_password"]})
    assert good_login.status_code == 200


def test_reject_and_accept_require_a_pending_deletion_request(client, admin_tokens):
    created = _invite(client, admin_tokens, "nopending@blutechconsulting.com")
    u = _get_user(client, admin_tokens, "nopending@blutechconsulting.com")
    # never requested deletion -> both guards fire
    assert client.post(f"/admin/users/{u['id']}/deletion/accept", headers=auth_header(admin_tokens)).status_code == 400
    assert client.post(f"/admin/users/{u['id']}/deletion/reject", headers=auth_header(admin_tokens)).status_code == 400
    assert client.post(f"/admin/users/{u['id']}/recovery/approve", headers=auth_header(admin_tokens)).status_code == 400
    assert client.post(f"/admin/users/{u['id']}/recovery/reject", headers=auth_header(admin_tokens)).status_code == 400


def test_recover_endpoint_is_generic_and_does_not_leak_account_existence(client):
    r1 = client.post("/auth/recover", json={"email": "nobody@blutechconsulting.com", "password": "whatever123"})
    r2 = client.post("/auth/recover", json={"email": "nobody2@blutechconsulting.com", "password": "whatever123"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()


def test_account_becomes_dormant_after_recovery_window_elapses(client, admin_tokens, db_session):
    created = _invite(client, admin_tokens, "dormant@blutechconsulting.com")
    login = client.post("/auth/login", json={"email": "dormant@blutechconsulting.com", "password": created["temp_password"]})
    utoken = {"access_token": login.json()["access_token"]}
    client.post("/auth/request-deletion", headers=auth_header(utoken))

    u = _get_user(client, admin_tokens, "dormant@blutechconsulting.com")
    client.post(f"/admin/users/{u['id']}/deletion/accept", headers=auth_header(admin_tokens))

    # backdate deleted_at past the 30-day window directly in the DB
    session = db_session()
    row = session.get(User, u["id"])
    row.deleted_at = datetime.now(timezone.utc) - timedelta(days=31)
    session.commit()
    session.close()

    u2 = _get_user(client, admin_tokens, "dormant@blutechconsulting.com")
    assert u2["account_status"] == "dormant"

    # dormant accounts get a distinct, terminal login message
    bad_login = client.post("/auth/login", json={"email": "dormant@blutechconsulting.com", "password": created["temp_password"]})
    assert bad_login.status_code == 403
    assert "permanently" in bad_login.json()["error"]["message"].lower()

    # recovery is no longer offered once dormant
    r = client.post("/auth/recover", json={"email": "dormant@blutechconsulting.com", "password": created["temp_password"]})
    assert r.status_code == 200  # still generic...
    u3 = _get_user(client, admin_tokens, "dormant@blutechconsulting.com")
    assert u3["account_status"] == "dormant"  # ...but it did NOT flip to recovery_requested

    # admin can still hard-purge a dormant account via the existing delete tool
    assert client.delete(f"/admin/users/{u['id']}", headers=auth_header(admin_tokens)).status_code == 204
