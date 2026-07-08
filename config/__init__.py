"""Configuration: tenant profiles (YAML) and LLM settings (.env).

Importing this package also loads .env once, so every module can read
environment variables without caring where they came from.
"""

from dotenv import load_dotenv

load_dotenv()

from .schema import (
    ClouderaConfig,
    CredentialsConfig,
    DataSourceConfig,
    RedisConfig,
    SSHConfig,
    TenantConfig,
    ThresholdsConfig,
)
from .loader import TenantConfigError, load_tenant_config, load_tenant_configs_from_dir
from .llm_config import LLMConfig, load_llm_config
from .secrets import load_tenant_secrets, secrets_file_for
from .thresholds_writer import ThresholdUpdateError, update_tenant_thresholds

__all__ = [
    "ClouderaConfig",
    "CredentialsConfig",
    "DataSourceConfig",
    "RedisConfig",
    "SSHConfig",
    "TenantConfig",
    "ThresholdsConfig",
    "TenantConfigError",
    "load_tenant_config",
    "load_tenant_configs_from_dir",
    "LLMConfig",
    "load_llm_config",
    "load_tenant_secrets",
    "secrets_file_for",
    "ThresholdUpdateError",
    "update_tenant_thresholds",
]
