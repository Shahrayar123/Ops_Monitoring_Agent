"""Tests for choose_data_source().

Normal rule: each tenant's own data_source.type decides (json = demo stage,
api = live cluster). USE_JSON in .env is an optional override that forces every
tenant to one kind.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from config import load_tenant_config
from data_sources import DataSourceError, JsonDataSource, choose_data_source
from data_sources.select import forced_source_kind, source_kind_for


def _json_tenant():
    return load_tenant_config("config/tenants/example-dev.yaml")


def _api_tenant():
    return load_tenant_config("config/tenants/example-api.template.yaml")


# ---- the normal rule: the tenant's own type decides ----


def test_a_json_stage_tenant_gets_the_json_source(monkeypatch):
    monkeypatch.delenv("USE_JSON", raising=False)

    assert isinstance(choose_data_source(_json_tenant()), JsonDataSource)


def test_an_api_tenant_gets_the_api_source_when_reachable(monkeypatch):
    monkeypatch.delenv("USE_JSON", raising=False)
    monkeypatch.setenv("EXAMPLE_TENANT_CM_USERNAME", "u")
    monkeypatch.setenv("EXAMPLE_TENANT_CM_PASSWORD", "p")

    fake = MagicMock()
    fake.check_connection.return_value = "v51"

    with patch("data_sources.select.ClouderaApiSource", return_value=fake):
        assert choose_data_source(_api_tenant()) is fake


# ---- the USE_JSON override ----


def test_no_use_json_line_means_no_override(monkeypatch):
    monkeypatch.delenv("USE_JSON", raising=False)
    assert forced_source_kind() is None
    assert source_kind_for(_json_tenant()) == "json"
    assert source_kind_for(_api_tenant()) == "api"


def test_use_json_true_forces_json_for_everyone(monkeypatch):
    monkeypatch.setenv("USE_JSON", "true")
    assert source_kind_for(_json_tenant()) == "json"
    assert source_kind_for(_api_tenant()) == "json"


def test_use_json_false_forces_api_for_everyone(monkeypatch):
    monkeypatch.setenv("USE_JSON", "false")
    assert source_kind_for(_json_tenant()) == "api"
    assert source_kind_for(_api_tenant()) == "api"


def test_forcing_json_on_an_api_only_tenant_explains_the_problem(monkeypatch):
    monkeypatch.setenv("USE_JSON", "true")
    # the api template has no data_dir, so forcing json can't work
    with pytest.raises(DataSourceError, match="data folder"):
        choose_data_source(_api_tenant())


def test_forcing_api_on_a_json_only_tenant_explains_the_problem(monkeypatch):
    monkeypatch.setenv("USE_JSON", "false")
    # the dev tenant has no cloudera/credentials settings
    with pytest.raises(DataSourceError, match="cloudera/credentials"):
        choose_data_source(_json_tenant())


# ---- clear errors on the api path ----


def _reachable_api_tenant(monkeypatch):
    monkeypatch.delenv("USE_JSON", raising=False)
    monkeypatch.setenv("EXAMPLE_TENANT_CM_USERNAME", "u")
    monkeypatch.setenv("EXAMPLE_TENANT_CM_PASSWORD", "p")
    return _api_tenant()


def test_a_missing_credential_env_var_fails_clearly(monkeypatch):
    monkeypatch.delenv("USE_JSON", raising=False)
    monkeypatch.delenv("EXAMPLE_TENANT_CM_USERNAME", raising=False)
    monkeypatch.delenv("EXAMPLE_TENANT_CM_PASSWORD", raising=False)

    with pytest.raises(DataSourceError, match="EXAMPLE_TENANT_CM_USERNAME"):
        choose_data_source(_api_tenant())


def test_an_unreachable_cluster_fails_with_a_readable_message(monkeypatch):
    tenant = _reachable_api_tenant(monkeypatch)

    fake = MagicMock()
    fake.check_connection.side_effect = httpx.ConnectError("refused")

    with patch("data_sources.select.ClouderaApiSource", return_value=fake):
        with pytest.raises(DataSourceError, match="could not reach"):
            choose_data_source(tenant)


def test_a_connection_timeout_fails_with_a_readable_message(monkeypatch):
    tenant = _reachable_api_tenant(monkeypatch)

    fake = MagicMock()
    fake.check_connection.side_effect = httpx.TimeoutException("timed out")

    with patch("data_sources.select.ClouderaApiSource", return_value=fake):
        with pytest.raises(DataSourceError, match="timed out"):
            choose_data_source(tenant)
