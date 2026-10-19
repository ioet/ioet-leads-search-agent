"""Convert Schedule expressions to LittleHorse unix cron (UTC)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.api.schemas.entities import ScheduleType


class CronError(ValueError):
    pass


def to_lh_cron(
    *,
    schedule_type: ScheduleType,
    expression: str,
    timezone: str = "UTC",
) -> str:
    """Return a 5-field unix cron expression in UTC for ScheduleWf."""
    expr = expression.strip()
    if schedule_type == ScheduleType.RECURRING:
        parts = expr.split()
        if len(parts) != 5:
            raise CronError("Recurring schedules need a 5-field unix cron expression")
        # Treated as UTC; timezone is stored for UI display only (DST-safe conversion is future work).
        return expr

    # once: ISO-8601 datetime (with or without offset); interpret naive as timezone.
    try:
        raw = expr.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CronError(f"Invalid once datetime: {expression!r}") from exc

    if dt.tzinfo is None:
        try:
            tz = ZoneInfo(timezone)
        except Exception as exc:
            raise CronError(f"Unknown timezone: {timezone!r}") from exc
        dt = dt.replace(tzinfo=tz)
    utc = dt.astimezone(ZoneInfo("UTC"))
    return f"{utc.minute} {utc.hour} {utc.day} {utc.month} *"
