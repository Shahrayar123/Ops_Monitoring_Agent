"""Persist edited thresholds back to a tenant's YAML file.

Edits come from the dashboard via the API. We validate the new values with the
same ThresholdsConfig model the loader uses (so a bad value is rejected before
anything is written), then update ONLY the thresholds block in the YAML —
using round-trip YAML so the file's comments and layout are preserved.
"""

import logging
from pathlib import Path

from ruamel.yaml import YAML

from .schema import ThresholdsConfig

log = logging.getLogger(__name__)

TENANTS_DIR = Path(__file__).resolve().parent / "tenants"

_yaml = YAML()          # round-trip mode: keeps comments, quotes, ordering
_yaml.preserve_quotes = True


class ThresholdUpdateError(Exception):
    """The new thresholds are invalid, or the tenant file can't be written."""


def update_tenant_thresholds(tenant_id: str, new_values: dict) -> ThresholdsConfig:
    """Validate `new_values`, write them into config/tenants/<id>.yaml, and
    return the validated thresholds. Raises ThresholdUpdateError on any problem."""
    path = TENANTS_DIR / f"{tenant_id}.yaml"
    if not path.is_file():
        raise ThresholdUpdateError(f"No tenant file for '{tenant_id}' ({path})")

    # 1. Validate first — never write junk. Merge over current values so a
    #    partial update (e.g. just cpu_pct) is allowed.
    try:
        current = load_current_thresholds(path)
        merged = {**current.model_dump(), **new_values}
        validated = ThresholdsConfig(**merged)
    except Exception as exc:  # pydantic ValidationError or bad input
        raise ThresholdUpdateError(f"Invalid thresholds: {exc}") from exc

    # 2. Write back, preserving the rest of the file. Update keys IN PLACE (not
    #    replacing the whole block) so per-line comments in the YAML survive.
    try:
        with path.open(encoding="utf-8") as f:
            doc = _yaml.load(f)
        block = doc.get("thresholds")
        if block is None:
            doc["thresholds"] = validated.model_dump()
        else:
            for key, value in validated.model_dump().items():
                block[key] = value
        with path.open("w", encoding="utf-8") as f:
            _yaml.dump(doc, f)
    except Exception as exc:
        raise ThresholdUpdateError(f"Could not write {path}: {exc}") from exc

    log.info("Updated thresholds for tenant '%s': %s", tenant_id, new_values)
    return validated


def load_current_thresholds(path: Path) -> ThresholdsConfig:
    with path.open(encoding="utf-8") as f:
        doc = _yaml.load(f)
    raw = dict(doc.get("thresholds", {})) if doc else {}
    return ThresholdsConfig(**raw)
