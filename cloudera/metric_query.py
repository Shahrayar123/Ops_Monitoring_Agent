"""Builds the query strings the Cloudera Manager metrics API expects.

CM's metrics endpoint takes a small SQL-like language called "tsquery":

    select cpu_percent where category=HOST

This module builds only the simple form our checks need — it is not a full
tsquery implementation.
"""


def build_metric_query(
    metric_names: list[str], category: str, extra_filter: str | None = None
) -> str:
    if not metric_names:
        raise ValueError("build_metric_query needs at least one metric name")

    query = "select " + ", ".join(metric_names) + f" where category={category}"
    if extra_filter:
        query += f" and {extra_filter}"
    return query
