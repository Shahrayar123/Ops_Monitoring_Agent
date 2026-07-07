"""Shared helpers for sources that hold several days of data and let the user
view any single day (the export source and the live API source).

Keeping these in one place means both sources filter by day, list available
days, and pick a "reference now" for the heartbeat check in exactly the same
way — so switching a tenant between file data and the live API changes nothing
about how the date filter behaves.
"""

from datetime import date, datetime, time, timezone

from .base import Host, MetricSeries


def trim_to_day(series: list[MetricSeries], as_of: date | None) -> list[MetricSeries]:
    """Keep only points on or before the end of the `as_of` day. `as_of=None`
    means no filtering (use everything, i.e. the most recent data)."""
    if as_of is None:
        return series
    cutoff = datetime.combine(as_of, time.max, tzinfo=timezone.utc)
    trimmed: list[MetricSeries] = []
    for s in series:
        kept = [p for p in s.points if p.timestamp <= cutoff]
        if kept:
            trimmed.append(s.model_copy(update={"points": kept}))
    return trimmed


def days_present(series: list[MetricSeries]) -> list[date]:
    """The distinct calendar days that appear in the given series."""
    days = {p.timestamp.date() for s in series for p in s.points}
    return sorted(days)


def reference_now(hosts: list[Host]) -> datetime:
    """The moment to judge heartbeats against — the newest host heartbeat. For a
    static/day-filtered view this keeps heartbeat ages sensible (each host is
    compared to the most recently-reporting host, not the real wall clock)."""
    heartbeats = [h.last_heartbeat for h in hosts]
    if heartbeats:
        return max(heartbeats)
    return datetime.now(timezone.utc)
