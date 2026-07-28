"""LLM platform tests: registry, per-user access, priority chain, token+call
limits, key masking, admin invites, model fallback.

The provider call is monkeypatched so tests never hit a real LLM.
"""

import pytest

from backend.app.llm import providers
from backend.app.llm.providers import ChatResult
from .conftest import auth_header


@pytest.fixture()
def fake_llm(monkeypatch):
    def fake_test_model(spec, *, api_key=None, ollama_base_url=None):
        return ChatResult(text="OK", prompt_tokens=5, completion_tokens=1, total_tokens=6, latency_ms=12)
    monkeypatch.setattr(providers, "test_model", fake_test_model)


# ---------- model listing & access ----------


def test_settings_lists_effective_allowed_models(client, user_tokens):
    # The test plan allows only qwen2.5:7b; the user has no per-user override,
    # so effective allowed = plan allowed.
    r = client.get("/settings/llm", headers=auth_header(user_tokens))
    assert r.status_code == 200
    body = r.json()
    allowed = [m["id"] for m in body["models"] if m["allowed"]]
    assert allowed == ["qwen2.5:7b"]
    assert len(body["models"]) >= 5           # every registry model listed
    assert all(p["provider"] != "ollama" for p in body["providers"])
    # usage carries both call and token limits now
    assert "daily_token_limit" in body["usage"] and "daily_limit" in body["usage"]


# ---------- priority chain ----------


def test_set_priority_enforces_allowed_and_max_three(client, admin_tokens):
    # Give the admin's own account access to 3 models via a plan edit.
    plan = client.get("/admin/plans", headers=auth_header(admin_tokens)).json()[0]
    client.patch(f"/admin/plans/{plan['id']}", json={
        **plan, "allowed_models": ["qwen2.5:7b", "gpt-4o", "claude-sonnet-5"],
    }, headers=auth_header(admin_tokens))

    ok = client.post("/settings/llm/priority", json={"model_ids": ["gpt-4o", "qwen2.5:7b"]}, headers=auth_header(admin_tokens))
    assert ok.status_code == 200
    assert ok.json()["model_priority"] == ["gpt-4o", "qwen2.5:7b"]

    # a model not in the allowed set is rejected
    denied = client.post("/settings/llm/priority", json={"model_ids": ["gemini-2.0-flash"]}, headers=auth_header(admin_tokens))
    assert denied.status_code == 403

    # more than 3 is rejected (schema caps the list)
    too_many = client.post("/settings/llm/priority", json={"model_ids": ["qwen2.5:7b", "gpt-4o", "claude-sonnet-5", "grok-3-mini"]}, headers=auth_header(admin_tokens))
    assert too_many.status_code == 422


# ---------- keys ----------


def test_api_key_encrypted_and_only_masked_returned(client, user_tokens):
    r = client.put("/settings/llm/keys", json={"provider": "openai", "api_key": "sk-secret-1234abcd"}, headers=auth_header(user_tokens))
    assert r.status_code == 200
    openai = next(p for p in r.json()["providers"] if p["provider"] == "openai")
    assert openai["configured"] and openai["masked_key"].endswith("abcd")
    assert "sk-secret-1234abcd" not in r.text


# ---------- metering & limits ----------


def test_test_model_records_usage(client, user_tokens, fake_llm):
    before = client.get("/settings/llm", headers=auth_header(user_tokens)).json()["usage"]["used_today"]
    r = client.post("/settings/llm/test", json={"model_id": "qwen2.5:7b"}, headers=auth_header(user_tokens))
    assert r.status_code == 200 and r.json()["ok"]
    assert r.json()["usage"]["used_today"] == before + 1
    assert r.json()["usage"]["tokens_today"] >= 6


def test_daily_call_limit_enforced(client, user_tokens, fake_llm, db_session):
    from backend.app.db.models import ApiUsage, User
    from sqlalchemy import select
    s = db_session()
    user = s.scalar(select(User).where(User.email.like("user@%")))
    for _ in range(user.plan.daily_api_limit):   # test plan = 10 calls/day
        s.add(ApiUsage(user_id=user.id, model_id="qwen2.5:7b", provider="ollama", kind="test", total_tokens=6, success=True))
    s.commit(); s.close()

    r = client.post("/settings/llm/test", json={"model_id": "qwen2.5:7b"}, headers=auth_header(user_tokens))
    assert r.status_code == 429
    assert "call limit" in r.json()["error"]["message"].lower()


def test_per_user_token_limit_overrides_plan(client, admin_tokens, user_tokens, fake_llm, db_session):
    from backend.app.db.models import ApiUsage, User
    from sqlalchemy import select

    # Admin sets a tiny per-user daily token limit.
    users = client.get("/admin/users", headers=auth_header(admin_tokens)).json()
    uid = next(u["id"] for u in users if u["email"].startswith("user@"))
    r = client.patch(f"/admin/users/{uid}/access", json={
        "allowed_models": ["qwen2.5:7b"], "daily_token_limit": 5,
    }, headers=auth_header(admin_tokens))
    assert r.status_code == 200
    assert r.json()["effective_daily_tokens"] == 5

    # Burn 6 tokens, then the next call is blocked on the token limit.
    s = db_session()
    u = s.get(User, uid)
    s.add(ApiUsage(user_id=u.id, model_id="qwen2.5:7b", provider="ollama", kind="test", total_tokens=6, success=True))
    s.commit(); s.close()

    blocked = client.post("/settings/llm/test", json={"model_id": "qwen2.5:7b"}, headers=auth_header(user_tokens))
    assert blocked.status_code == 429
    assert "token limit" in blocked.json()["error"]["message"].lower()


# ---------- admin: invites & per-user access ----------


def test_saving_access_drops_a_retired_model_instead_of_400(client, admin_tokens, user_tokens, db_session):
    """A model id removed from the registry can linger in a user's stored
    allowed_models/model_priority. Editing that user's access must not 400 on the
    orphaned id — it should silently drop it and save the rest (self-heal)."""
    from backend.app.db.models import User
    from sqlalchemy.orm.attributes import flag_modified

    users = client.get("/admin/users", headers=auth_header(admin_tokens)).json()
    uid = next(u["id"] for u in users if u["email"].startswith("user@"))

    # Simulate the orphaned data: a valid model plus one that isn't in the registry.
    s = db_session()
    u = s.get(User, uid)
    u.allowed_models = ["qwen2.5:7b", "totally-removed-model"]
    u.model_priority = ["totally-removed-model", "qwen2.5:7b"]
    flag_modified(u, "allowed_models"); flag_modified(u, "model_priority")
    s.commit(); s.close()

    # Re-submitting the pre-loaded selection (orphan included) must succeed...
    r = client.patch(f"/admin/users/{uid}/access", json={
        "allowed_models": ["qwen2.5:7b", "totally-removed-model"],
        "model_priority": ["totally-removed-model", "qwen2.5:7b"],
    }, headers=auth_header(admin_tokens))
    assert r.status_code == 200
    # ...and the orphan is gone from what was stored, the real model kept.
    assert r.json()["allowed_models"] == ["qwen2.5:7b"]

    s = db_session()
    u = s.get(User, uid)
    assert "totally-removed-model" not in u.allowed_models
    assert "totally-removed-model" not in u.model_priority
    s.close()


def test_admin_creates_user_and_gets_credentials(client, admin_tokens):
    r = client.post("/admin/users/create", json={
        "email": "invitee@blutechconsulting.com", "full_name": "Invited User", "role": "user",
        "allowed_models": ["qwen2.5:7b", "gpt-4o"], "daily_call_limit": 25,
    }, headers=auth_header(admin_tokens))
    assert r.status_code == 201
    body = r.json()
    assert body["temp_password"]                 # shown once to the admin
    assert body["emailed"] is False              # no SMTP configured in tests
    assert "/login" in body["invite_link"]

    # the invited user can sign in with the temp password and is flagged to change it
    login = client.post("/auth/login", json={"email": "invitee@blutechconsulting.com", "password": body["temp_password"]})
    assert login.status_code == 200
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.json()["must_change_password"] is True


# ---------- password reset (admin) & forgot-password (self-service) ----------


def _create_user(client, admin_tokens, email):
    return client.post("/admin/users/create", json={
        "email": email, "full_name": "Reset Target", "role": "user",
    }, headers=auth_header(admin_tokens)).json()


def test_admin_reset_password_issues_new_working_credentials(client, admin_tokens):
    created = _create_user(client, admin_tokens, "resetme@blutechconsulting.com")
    old_pw, uid = created["temp_password"], created["user_id"]

    r = client.post(f"/admin/users/{uid}/reset-password", headers=auth_header(admin_tokens))
    assert r.status_code == 200
    body = r.json()
    new_pw = body["temp_password"]
    assert new_pw and new_pw != old_pw
    assert body["emailed"] is False              # no SMTP in tests -> shown on screen

    # the old password is dead; the new one works and forces a change
    assert client.post("/auth/login", json={"email": "resetme@blutechconsulting.com", "password": old_pw}).status_code == 401
    login = client.post("/auth/login", json={"email": "resetme@blutechconsulting.com", "password": new_pw})
    assert login.status_code == 200
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.json()["must_change_password"] is True


def test_reset_password_requires_admin(client, user_tokens):
    assert client.post("/admin/users/1/reset-password", headers=auth_header(user_tokens)).status_code == 403


def test_admin_account_cannot_be_reset_from_admin_panel(client, admin_tokens, db_session):
    """Resetting an admin from here is disallowed (a known bad path) — mirrors the
    can't-delete-an-admin rule. Admins use change-password / forgot-password."""
    from backend.app.db.models import Role, User
    from sqlalchemy import select

    s = db_session()
    admin_id = s.scalar(select(User.id).where(User.role == Role.ADMIN))
    s.close()

    r = client.post(f"/admin/users/{admin_id}/reset-password", headers=auth_header(admin_tokens))
    assert r.status_code == 400
    assert "admin" in r.json()["error"]["message"].lower()


def test_forgot_password_without_smtp_leaves_the_account_usable(client, admin_tokens):
    """Safety guard: with no email configured, forgot-password must NOT rotate the
    password — otherwise the user is locked out with no way to receive a new one."""
    created = _create_user(client, admin_tokens, "forgot@blutechconsulting.com")
    pw = created["temp_password"]

    r = client.post("/auth/forgot-password", json={"email": "forgot@blutechconsulting.com"})
    assert r.status_code == 200
    assert "temporary password has been sent" in r.json()["message"]   # generic

    # original password still works — nothing was changed
    assert client.post("/auth/login", json={"email": "forgot@blutechconsulting.com", "password": pw}).status_code == 200


def test_forgot_password_unknown_email_gives_same_generic_message(client):
    r = client.post("/auth/forgot-password", json={"email": "nobody@blutechconsulting.com"})
    assert r.status_code == 200
    assert "temporary password has been sent" in r.json()["message"]


def test_send_credentials_emails_the_shown_password(client, admin_tokens, monkeypatch):
    """The 'Send email' button on the result screen mails exactly what's shown,
    without rotating the password. Verifies the live-credential guard too."""
    import backend.app.api.routes.user_admin as ua
    created = _create_user(client, admin_tokens, "sendme@blutechconsulting.com")
    uid, pw = created["user_id"], created["temp_password"]

    # No SMTP configured (test default) -> reports not-sent, but no error / no change.
    r = client.post(f"/admin/users/{uid}/send-credentials",
                    json={"temp_password": pw, "kind": "invite"}, headers=auth_header(admin_tokens))
    assert r.status_code == 200 and r.json()["sent"] is False

    # A stale/wrong password is rejected before any send.
    bad = client.post(f"/admin/users/{uid}/send-credentials",
                      json={"temp_password": "not-the-real-one", "kind": "invite"}, headers=auth_header(admin_tokens))
    assert bad.status_code == 409

    # With email mocked, the correct password is delivered and NOT rotated.
    sent = {}
    monkeypatch.setattr(ua, "smtp_configured", lambda: True)
    monkeypatch.setattr(ua, "send_invite", lambda to, name, temp, link: (sent.update(to=to, temp=temp) or True))
    ok = client.post(f"/admin/users/{uid}/send-credentials",
                     json={"temp_password": pw, "kind": "invite"}, headers=auth_header(admin_tokens))
    assert ok.status_code == 200 and ok.json()["sent"] is True
    assert sent == {"to": "sendme@blutechconsulting.com", "temp": pw}
    # password unchanged — original still logs in
    assert client.post("/auth/login", json={"email": "sendme@blutechconsulting.com", "password": pw}).status_code == 200


def test_send_credentials_requires_admin(client, user_tokens):
    assert client.post("/admin/users/1/send-credentials",
                       json={"temp_password": "x", "kind": "invite"}, headers=auth_header(user_tokens)).status_code == 403


def test_forgot_password_with_email_configured_rotates_password(client, admin_tokens, monkeypatch):
    """Happy path with email mocked: the password is rotated and the emailed temp
    password works while the old one dies."""
    import backend.app.api.routes.auth as auth_routes
    sent = {}
    monkeypatch.setattr(auth_routes, "smtp_configured", lambda: True)
    monkeypatch.setattr(auth_routes, "send_password_reset",
                        lambda to, name, temp, link: (sent.update(to=to, temp=temp) or True))

    created = _create_user(client, admin_tokens, "fp2@blutechconsulting.com")
    old_pw = created["temp_password"]

    r = client.post("/auth/forgot-password", json={"email": "fp2@blutechconsulting.com"})
    assert r.status_code == 200
    assert sent["to"] == "fp2@blutechconsulting.com"
    assert client.post("/auth/login", json={"email": "fp2@blutechconsulting.com", "password": old_pw}).status_code == 401
    assert client.post("/auth/login", json={"email": "fp2@blutechconsulting.com", "password": sent["temp"]}).status_code == 200


def test_admin_sets_per_user_models_and_user_sees_them(client, admin_tokens):
    created = client.post("/admin/users/create", json={
        "email": "scoped@blutechconsulting.com", "role": "user", "allowed_models": ["qwen2.5:7b", "claude-sonnet-5"],
    }, headers=auth_header(admin_tokens)).json()
    login = client.post("/auth/login", json={"email": "scoped@blutechconsulting.com", "password": created["temp_password"]})
    token = {"access_token": login.json()["access_token"]}

    body = client.get("/settings/llm", headers=auth_header(token)).json()
    allowed = {m["id"] for m in body["models"] if m["allowed"]}
    assert allowed == {"qwen2.5:7b", "claude-sonnet-5"}   # per-user list, NOT the plan


def test_user_management_requires_admin(client, user_tokens):
    assert client.post("/admin/users/create", json={"email": "x@blutechconsulting.com"}, headers=auth_header(user_tokens)).status_code == 403
    assert client.patch("/admin/users/1/access", json={"allowed_models": []}, headers=auth_header(user_tokens)).status_code == 403
    assert client.delete("/admin/users/1", headers=auth_header(user_tokens)).status_code == 403


def test_admin_deletes_user(client, admin_tokens):
    created = client.post("/admin/users/create", json={
        "email": "todelete@blutechconsulting.com", "role": "user",
    }, headers=auth_header(admin_tokens)).json()
    uid = created["user_id"]

    r = client.delete(f"/admin/users/{uid}", headers=auth_header(admin_tokens))
    assert r.status_code == 204

    # gone from the list and can no longer log in
    users = client.get("/admin/users", headers=auth_header(admin_tokens)).json()
    assert not any(u["id"] == uid for u in users)
    login = client.post("/auth/login", json={"email": "todelete@blutechconsulting.com", "password": "whatever"})
    assert login.status_code == 401

    # deleting again is a 404, not a crash
    assert client.delete(f"/admin/users/{uid}", headers=auth_header(admin_tokens)).status_code == 404


def test_admin_deletes_user_who_has_data_in_every_related_table(client, admin_tokens, db_session):
    """Regression: deleting a user with rows in ANY table that FKs to users.id
    must succeed. The plain delete test above uses a fresh user with no related
    rows, so it passed while a real FK violation (user_kpi_refresh_rates) shipped.
    This populates every referencing table first.
    """
    from backend.app.db.models import ApiUsage, UserKpiRefreshRate, UserSetting, UserTenant

    created = client.post("/admin/users/create", json={
        "email": "fulldata@blutechconsulting.com", "role": "user",
    }, headers=auth_header(admin_tokens)).json()
    uid = created["user_id"]
    token = {"access_token": client.post("/auth/login", json={
        "email": "fulldata@blutechconsulting.com", "password": created["temp_password"]}).json()["access_token"]}

    # cluster link (UserTenant)
    client.post("/admin/tenants", json={"slug": "delfk", "display_name": "Del FK", "cluster_name": "delfk"},
                headers=auth_header(admin_tokens))
    client.post(f"/admin/tenants/delfk/link/{uid}", headers=auth_header(admin_tokens))
    # per-user KPI refresh override (UserKpiRefreshRate) — the row that caused the bug
    client.put("/settings/kpi-refresh", json={"task": "cpu_percent", "seconds": 120}, headers=auth_header(token))
    # a stored setting (UserSetting) + a usage row (ApiUsage)
    client.post("/settings/llm/ollama-url", json={"url": "http://localhost:11434"}, headers=auth_header(token))
    s = db_session()
    s.add(ApiUsage(user_id=uid, model_id="qwen2.5:7b", provider="ollama", kind="analysis", total_tokens=10, success=True))
    s.commit()
    # sanity: every referencing table really has a row for this user
    assert s.query(UserTenant).filter_by(user_id=uid).count() == 1
    assert s.query(UserKpiRefreshRate).filter_by(user_id=uid).count() == 1
    assert s.query(UserSetting).filter_by(user_id=uid).count() >= 1
    assert s.query(ApiUsage).filter_by(user_id=uid).count() == 1
    s.close()

    r = client.delete(f"/admin/users/{uid}", headers=auth_header(admin_tokens))
    assert r.status_code == 204, r.text

    # and every dependent row is gone too (no orphans left behind)
    s2 = db_session()
    assert s2.query(UserTenant).filter_by(user_id=uid).count() == 0
    assert s2.query(UserKpiRefreshRate).filter_by(user_id=uid).count() == 0
    assert s2.query(UserSetting).filter_by(user_id=uid).count() == 0
    assert s2.query(ApiUsage).filter_by(user_id=uid).count() == 0
    s2.close()


def test_admin_accounts_cannot_be_deleted(client, admin_tokens):
    # not even their own account
    users = client.get("/admin/users", headers=auth_header(admin_tokens)).json()
    admin_id = next(u["id"] for u in users if u["role"] == "admin")
    assert client.delete(f"/admin/users/{admin_id}", headers=auth_header(admin_tokens)).status_code == 400

    # nor any OTHER admin account
    other_admin = client.post("/admin/users/create", json={
        "email": "otheradmin@blutechconsulting.com", "role": "admin",
    }, headers=auth_header(admin_tokens)).json()
    r = client.delete(f"/admin/users/{other_admin['user_id']}", headers=auth_header(admin_tokens))
    assert r.status_code == 400


def test_user_can_request_and_cancel_account_deletion(client, user_tokens):
    me = client.get("/auth/me", headers=auth_header(user_tokens)).json()
    assert me["deletion_requested_at"] is None

    r = client.post("/auth/request-deletion", headers=auth_header(user_tokens))
    assert r.status_code == 200
    assert r.json()["deletion_requested_at"] is not None

    r2 = client.post("/auth/cancel-deletion-request", headers=auth_header(user_tokens))
    assert r2.status_code == 200
    assert r2.json()["deletion_requested_at"] is None


def test_admin_review_sees_and_can_delete_requested_account(client, admin_tokens, user_tokens):
    client.post("/auth/request-deletion", headers=auth_header(user_tokens))
    users = client.get("/admin/users", headers=auth_header(admin_tokens)).json()
    requester = next(u for u in users if u["deletion_requested_at"] is not None)
    r = client.delete(f"/admin/users/{requester['id']}", headers=auth_header(admin_tokens))
    assert r.status_code == 204


def test_admin_cannot_request_own_deletion(client, admin_tokens):
    r = client.post("/auth/request-deletion", headers=auth_header(admin_tokens))
    assert r.status_code == 400


# ---------- model fallback runner ----------


def test_fallback_runner_falls_through_to_the_next_model(client, admin_tokens, monkeypatch, db_session):
    """First model raises; the runner should record the failure and use the second."""
    from backend.app.db.models import User
    from backend.app.llm import runner
    from backend.app.llm.providers import LLMError
    from sqlalchemy import select

    calls = []

    def fake_chat(spec, messages, **kw):
        calls.append(spec.id)
        if spec.id == "gpt-4o":
            raise LLMError("boom")
        return ChatResult(text="hi", prompt_tokens=3, completion_tokens=2, total_tokens=5, latency_ms=9)

    monkeypatch.setattr(runner, "chat", fake_chat)

    s = db_session()
    admin = s.scalar(select(User).where(User.email.like("admin@%")))
    admin.allowed_models = ["gpt-4o", "qwen2.5:7b"]
    admin.model_priority = ["gpt-4o", "qwen2.5:7b"]
    s.add(admin); s.commit()
    # openai needs a key for the first model; give a fake one so it attempts it
    from backend.app.llm import settings as ls
    ls.set_api_key(s, admin.id, "openai", "sk-test-abcd")
    outcome = runner.chat_with_fallback(s, admin, [{"role": "user", "content": "hi"}])
    s.close()

    assert calls == ["gpt-4o", "qwen2.5:7b"]      # tried first, fell through
    assert outcome.model_id == "qwen2.5:7b"
    assert outcome.attempts[0]["ok"] is False and outcome.attempts[1]["ok"] is True
