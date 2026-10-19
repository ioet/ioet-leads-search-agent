"""Keep DynamoDB Schedule rows in sync with LittleHorse ScheduledWfRun objects."""

from __future__ import annotations

import logging

from services.api.lh_client import LittleHorseError, delete_scheduled_wf_run, schedule_fire_campaign
from services.api.schedule_cron import CronError, to_lh_cron
from services.api.schemas.entities import SchedulePublic, ScheduleType
from services.api.stores import schedules as schedule_store

logger = logging.getLogger(__name__)


class ScheduleSyncError(RuntimeError):
    pass


def sync_schedule_to_lh(schedule: SchedulePublic) -> SchedulePublic:
    """Create or refresh the LH schedule when enabled; delete when disabled."""
    # Tear down any previous LH schedule first.
    if schedule.lh_schedule_id:
        try:
            delete_scheduled_wf_run(schedule.lh_schedule_id)
        except LittleHorseError as exc:
            logger.warning("Could not delete old LH schedule %s: %s", schedule.lh_schedule_id, exc)
        schedule = schedule_store.update_schedule(schedule.schedule_id, lh_schedule_id="")

    if not schedule.enabled:
        return schedule

    try:
        cron = to_lh_cron(
            schedule_type=schedule.type,
            expression=schedule.expression,
            timezone=schedule.timezone,
        )
        lh_id = schedule_fire_campaign(
            schedule_id=schedule.schedule_id,
            cron_expression=cron,
        )
    except (CronError, LittleHorseError) as exc:
        raise ScheduleSyncError(str(exc)) from exc

    return schedule_store.update_schedule(schedule.schedule_id, lh_schedule_id=lh_id)


def unsync_schedule_from_lh(schedule: SchedulePublic) -> None:
    if schedule.lh_schedule_id:
        try:
            delete_scheduled_wf_run(schedule.lh_schedule_id)
        except LittleHorseError as exc:
            logger.warning(
                "Could not delete LH schedule %s: %s", schedule.lh_schedule_id, exc
            )
    schedule_store.update_schedule(schedule.schedule_id, lh_schedule_id="")


def unsync_all_for_campaign(campaign_id: str) -> None:
    for schedule in schedule_store.list_schedules_for_campaign(campaign_id):
        unsync_schedule_from_lh(schedule)
        if schedule.enabled:
            schedule_store.update_schedule(schedule.schedule_id, enabled=False)
