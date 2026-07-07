"""Tests for per-customer secrets files (secrets/<tenant_id>.env)."""

import os
from unittest.mock import MagicMock, patch

import pytest

import config.secrets as secrets_module
from config import load_tenant_config, load_tenant_secrets
from data_sources import DataSourceError, choose_data_source


@pytest.fixture
def secrets_dir(tmp_path, monkeypatch):
    """Point the secrets folder at a temp directory for the test."""
    monkeypatch.setattr(secrets_module, "SECRETS_DIR", tmp_path)
    return tmp_path


def test_a_tenant_secrets_file_is_loaded_into_the_environment(secrets_dir, monkeypatch):
    monkeypatch.delenv("SOME_TENANT_PASSWORD", raising=False)
    (secrets_dir / "some-tenant.env").write_text("SOME_TENANT_PASSWORD=s3cret\n")

    assert load_tenant_secrets("some-tenant") is True
    assert os.environ["SOME_TENANT_PASSWORD"] == "s3cret"


def test_a_missing_secrets_file_is_fine(secrets_dir):
    assert load_tenant_secrets("tenant-without-secrets") is False


def test_a_rotated_value_in_the_file_wins_over_a_stale_one(secrets_dir, monkeypatch):
    monkeypatch.setenv("ROTATED_PASSWORD", "old-value")
    (secrets_dir / "rot-tenant.env").write_text("ROTATED_PASSWORD=new-value\n")

    load_tenant_secrets("rot-tenant")

    assert os.environ["ROTATED_PASSWORD"] == "new-value"


def test_api_tenant_credentials_are_picked_up_from_its_secrets_file(secrets_dir, monkeypatch):
    monkeypatch.delenv("USE_JSON", raising=False)
    monkeypatch.delenv("EXAMPLE_TENANT_CM_USERNAME", raising=False)
    monkeypatch.delenv("EXAMPLE_TENANT_CM_PASSWORD", raising=False)
    (secrets_dir / "example-api-tenant.env").write_text(
        "EXAMPLE_TENANT_CM_USERNAME=svc_monitor\nEXAMPLE_TENANT_CM_PASSWORD=pw\n"
    )
    tenant = load_tenant_config("config/tenants/example-api.template.yaml")

    fake = MagicMock()
    fake.check_connection.return_value = "v51"

    with patch("data_sources.select.ClouderaApiSource", return_value=fake) as fake_cls:
        assert choose_data_source(tenant) is fake

    # the credentials were in the environment by the time the source was built
    assert os.environ["EXAMPLE_TENANT_CM_USERNAME"] == "svc_monitor"
    fake_cls.assert_called_once()


def test_the_error_for_a_missing_credential_names_the_secrets_file(secrets_dir, monkeypatch):
    monkeypatch.delenv("USE_JSON", raising=False)
    monkeypatch.delenv("EXAMPLE_TENANT_CM_USERNAME", raising=False)
    monkeypatch.delenv("EXAMPLE_TENANT_CM_PASSWORD", raising=False)
    tenant = load_tenant_config("config/tenants/example-api.template.yaml")

    with pytest.raises(DataSourceError) as exc_info:
        choose_data_source(tenant)

    message = str(exc_info.value)
    assert "EXAMPLE_TENANT_CM_USERNAME" in message
    assert "example-api-tenant.env" in message
