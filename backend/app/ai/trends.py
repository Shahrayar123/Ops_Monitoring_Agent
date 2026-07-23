"""Computed trend extrapolation — the honest version of "expected to fill in N hours".

Only disk fullness is extrapolated, because it's a monotonic, physically-meaningful
signal where a linear fill-rate estimate is defensible. We do NOT invent timelines
for CPU/RAM/health — those are noisy and non-monotonic. If the rate isn't clearly
positive or the window is too short, we simply say nothing rather than guess.
"""

from dataclasses import dataclass

from config import TenantConfig
from data_sources import DataSource


@dataclass
class DiskProjection:
    entity: str              # "host:/mount"
    current_pct: float
    rate_pct_per_hour: float
    hours_to_full: float     # to 100%


def disk_projections(source: DataSource, tenant: TenantConfig, limit: int = 6) -> list[DiskProjection]:
    """For each watched mount that is steadily filling, estimate hours to 100%
    from a linear fit of its recent fullness history. Returns soonest first;
    mounts that are flat or draining are omitted."""
    watched = set(tenant.thresholds.disk_mounts)
    series = source.get_metrics(["fs_bytes_used_percent"])

    projections: list[DiskProjection] = []
    for s in series:
        mount = s.attributes.get("mount_point")
        if mount not in watched or len(s.points) < 2:
            continue

        points = sorted(s.points, key=lambda p: p.timestamp)
        first, last = points[0], points[-1]
        hours = (last.timestamp - first.timestamp).total_seconds() / 3600.0
        if hours <= 0:
            continue

        rate = (last.value - first.value) / hours     # %/hour
        current = last.value
        # Only project mounts that are meaningfully climbing and not already full.
        if rate <= 0.05 or current >= 100:
            continue
        hours_to_full = (100.0 - current) / rate
        projections.append(DiskProjection(
            entity=f"{s.entity_name}:{mount}",
            current_pct=round(current, 1),
            rate_pct_per_hour=round(rate, 2),
            hours_to_full=round(hours_to_full, 1),
        ))

    projections.sort(key=lambda p: p.hours_to_full)
    return projections[:limit]


def format_for_prompt(projections: list[DiskProjection]) -> str:
    if not projections:
        return "(No mount is filling fast enough to project a time-to-full.)"
    lines = []
    for p in projections:
        lines.append(
            f"- {p.entity}: {p.current_pct}% now, rising ~{p.rate_pct_per_hour}%/h "
            f"-> ~{p.hours_to_full:.0f}h to full"
        )
    return "\n".join(lines)
