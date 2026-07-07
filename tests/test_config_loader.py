import pytest

from config import TenantConfigError, load_tenant_config, load_tenant_configs_from_dir

TENANTS_DIR = "config/tenants"


def test_json_tenant_loads_with_default_thresholds():
    config = load_tenant_config(f"{TENANTS_DIR}/example-dev.yaml")

    assert config.tenant_id == "example-dev"
    assert config.data_source.type == "json"
    assert config.data_source.data_dir == "data/sample"
    assert config.cloudera is None
    assert config.credentials is None
    assert config.thresholds.cpu_pct == 60.0
    assert config.thresholds.ram_pct == 60.0
    assert config.thresholds.disk_pct == 90.0
    assert config.thresholds.heartbeat_window_sec == 60
    assert config.thresholds.disk_mounts == ["/var", "/opt", "/home", "/tmp"]


def test_api_tenant_loads_with_cloudera_and_credentials():
    config = load_tenant_config(f"{TENANTS_DIR}/example-api.template.yaml")

    assert config.data_source.type == "api"
    assert config.cloudera is not None
    assert config.cloudera.cm_host == "cm.example-customer.internal"
    assert config.cloudera.api_version == "auto"
    assert config.credentials is not None
    assert config.credentials.username_env == "EXAMPLE_TENANT_CM_USERNAME"
    assert config.ssh is not None
    assert config.ssh.log_dirs == [
        "/var/log/hadoop",
        "/var/log/hadoop-hdfs",
        "/var/log/hadoop-yarn",
    ]


def test_json_tenant_without_data_dir_fails_fast(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
tenant_id: bad-json-tenant
display_name: "Bad Tenant"
cluster_name: Some-Cluster
data_source:
  type: json
"""
    )

    with pytest.raises(TenantConfigError, match="data_dir is required"):
        load_tenant_config(bad)


def test_api_tenant_without_cloudera_settings_fails_fast(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
tenant_id: bad-api-tenant
display_name: "Bad Tenant"
cluster_name: Some-Cluster
data_source:
  type: api
"""
    )

    with pytest.raises(TenantConfigError) as exc_info:
        load_tenant_config(bad)

    assert "cloudera settings are required" in str(exc_info.value)
    assert "credentials settings are required" in str(exc_info.value)


def test_missing_file_gives_clear_error():
    with pytest.raises(TenantConfigError, match="not found"):
        load_tenant_config("config/tenants/does-not-exist.yaml")


def test_loading_a_directory_keys_tenants_by_id():
    configs = load_tenant_configs_from_dir(TENANTS_DIR)

    assert "example-dev" in configs
    assert "example-api-tenant" in configs
    assert configs["example-dev"].data_source.type == "json"
