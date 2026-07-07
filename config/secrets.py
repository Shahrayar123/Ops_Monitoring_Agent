"""Per-customer secrets files.

Each customer's credentials live in their own file: secrets/<tenant_id>.env.
The global .env holds only truly global settings (AI model, dev overrides) —
never customer credentials. This way:

- reading one customer's secrets doesn't expose every other customer's,
- rotating one customer's password touches only that customer's file,
- onboarding = one YAML in config/tenants/ + one file in secrets/.

The file format is the same simple KEY=value as .env:

    # secrets/acme-corp.env
    ACME_CORP_CM_USERNAME=svc_ops_monitor
    ACME_CORP_CM_PASSWORD=...

load_tenant_secrets() is called automatically whenever a tenant's data source
is built, so the variables its YAML references are present in the environment
by the time they're read. A missing file is fine (JSON-stage tenants don't
need one); a missing VARIABLE still fails loudly later with its exact name.
"""

import logging
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)

SECRETS_DIR = Path(__file__).resolve().parent.parent / "secrets"


def secrets_file_for(tenant_id: str) -> Path:
    return SECRETS_DIR / f"{tenant_id}.env"


def load_tenant_secrets(tenant_id: str) -> bool:
    """Load secrets/<tenant_id>.env into the environment if it exists.
    Returns True when a file was found and loaded. override=True so a freshly
    rotated value in the file always wins over a stale one already loaded."""
    path = secrets_file_for(tenant_id)
    if not path.is_file():
        log.debug("No secrets file for tenant '%s' (%s) — skipping", tenant_id, path)
        return False

    load_dotenv(path, override=True)
    log.info("Loaded secrets file for tenant '%s'", tenant_id)
    return True
