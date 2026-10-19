"""Unit tests for Schedule expression → LittleHorse cron conversion."""

from __future__ import annotations

import pytest

from services.api.schedule_cron import CronError, to_lh_cron
from services.api.schemas.entities import ScheduleType


def test_recurring_passes_through() -> None:
    assert (
        to_lh_cron(
            schedule_type=ScheduleType.RECURRING,
            expression="0 7 * * 1",
            timezone="America/New_York",
        )
        == "0 7 * * 1"
    )


def test_recurring_rejects_bad_cron() -> None:
    with pytest.raises(CronError):
        to_lh_cron(
            schedule_type=ScheduleType.RECURRING,
            expression="0 7 * *",
            timezone="UTC",
        )


def test_once_naive_datetime_uses_timezone() -> None:
    cron = to_lh_cron(
        schedule_type=ScheduleType.ONCE,
        expression="2026-10-20T09:30:00",
        timezone="America/New_York",
    )
    # 09:30 EDT = 13:30 UTC
    assert cron == "30 13 20 10 *"


def test_once_utc_z() -> None:
    cron = to_lh_cron(
        schedule_type=ScheduleType.ONCE,
        expression="2026-03-15T14:05:00Z",
        timezone="UTC",
    )
    assert cron == "5 14 15 3 *"


def test_once_invalid() -> None:
    with pytest.raises(CronError):
        to_lh_cron(
            schedule_type=ScheduleType.ONCE,
            expression="not-a-date",
            timezone="UTC",
        )
