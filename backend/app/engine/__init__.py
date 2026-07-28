"""Bridge between the product's database tenants and the monitoring engine.

The engine (checks/, data_sources/, config/) is framework-agnostic and speaks in
`TenantConfig` + `DataSource`. This package converts a database `Tenant` row into
those objects and runs the checks — so the same battle-tested engine powers both
the legacy Streamlit dashboard and this product, with zero duplicated logic.
"""
