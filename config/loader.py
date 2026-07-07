"""Loads tenant YAML files into validated TenantConfig objects.

Fails fast: a broken tenant file raises TenantConfigError immediately with
every problem listed at once — the system never starts half-configured.
"""

from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import TenantConfig


class TenantConfigError(Exception):
    """A tenant config file is missing, malformed, or invalid."""


def load_tenant_config(path: str | Path) -> TenantConfig:
    """Load and validate one tenant's YAML file."""
    path = Path(path)
    if not path.is_file():
        raise TenantConfigError(f"Tenant config file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TenantConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise TenantConfigError(f"Tenant config {path} must be a YAML mapping at the top level")

    try:
        return TenantConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise TenantConfigError(f"Invalid tenant config {path}: {problems}") from exc


def load_tenant_configs_from_dir(directory: str | Path) -> dict[str, TenantConfig]:
    """Load every *.yaml/*.yml tenant file in a folder, keyed by tenant_id."""
    directory = Path(directory)
    if not directory.is_dir():
        raise TenantConfigError(f"Tenant config directory not found: {directory}")

    configs: dict[str, TenantConfig] = {}
    for file_path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
        config = load_tenant_config(file_path)
        if config.tenant_id in configs:
            raise TenantConfigError(f"Duplicate tenant_id '{config.tenant_id}' in {file_path}")
        configs[config.tenant_id] = config

    return configs
