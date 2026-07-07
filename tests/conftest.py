"""Shared test setup: one sample tenant and one JSON data source, used by most
test files.

Tests read their own frozen copy of the sample data (tests/sample_data/), NOT
the live data/ folder — that one is meant to be edited freely during demos to
simulate cluster changes, and tests must not break when it changes.
"""

import pytest

from config import load_tenant_config
from data_sources import JsonDataSource


@pytest.fixture
def tenant():
    return load_tenant_config("config/tenants/example-dev.yaml")


@pytest.fixture
def source():
    return JsonDataSource("tests/sample_data")
