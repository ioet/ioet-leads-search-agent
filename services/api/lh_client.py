"""LittleHorse client helpers used by the campaign API."""

from __future__ import annotations

import logging
from typing import Any

from littlehorse.config import LHConfig
from littlehorse.model.object_id_pb2 import ScheduledWfRunId
from littlehorse.model.service_pb2 import (
    DeleteScheduledWfRunRequest,
    RunWfRequest,
    ScheduleWfRequest,
)
from littlehorse.utils import to_variable_value

from workflow.workflows.fire_schedule import FIRE_SCHEDULE_WF_NAME
from workflow.workflows.leads_search import PARENT_WF_NAME

logger = logging.getLogger(__name__)


class LittleHorseError(RuntimeError):
    pass


def _stub():
    return LHConfig().stub()


def start_leads_search_run(variables: dict[str, Any]) -> str:
    """Start ``leads-search-workflow`` and return the WfRun id."""
    try:
        stub = _stub()
        request = RunWfRequest(wf_spec_name=PARENT_WF_NAME)
        for key, value in variables.items():
            request.variables[key].CopyFrom(to_variable_value(value))
        wf_run = stub.RunWf(request)
    except Exception as exc:
        raise LittleHorseError(f"Failed to start workflow: {exc}") from exc

    run_id = getattr(getattr(wf_run, "id", None), "id", None) or ""
    if not run_id:
        raise LittleHorseError("LittleHorse returned an empty WfRun id")
    logger.info("Started %s as WfRun %s", PARENT_WF_NAME, run_id)
    return str(run_id)


def schedule_fire_campaign(*, schedule_id: str, cron_expression: str) -> str:
    """Register a LittleHorse cron that runs ``fire-scheduled-campaign``."""
    try:
        stub = _stub()
        request = ScheduleWfRequest(
            wf_spec_name=FIRE_SCHEDULE_WF_NAME,
            cron_expression=cron_expression,
        )
        request.variables["schedule-id"].CopyFrom(to_variable_value(schedule_id))
        scheduled = stub.ScheduleWf(request)
    except Exception as exc:
        raise LittleHorseError(f"Failed to schedule workflow: {exc}") from exc

    lh_id = getattr(getattr(scheduled, "id", None), "id", None) or ""
    if not lh_id:
        raise LittleHorseError("LittleHorse returned an empty ScheduledWfRun id")
    logger.info(
        "Scheduled %s as %s cron=%s schedule_id=%s",
        FIRE_SCHEDULE_WF_NAME,
        lh_id,
        cron_expression,
        schedule_id,
    )
    return str(lh_id)


def delete_scheduled_wf_run(lh_schedule_id: str) -> None:
    if not lh_schedule_id:
        return
    try:
        stub = _stub()
        stub.DeleteScheduledWfRun(
            DeleteScheduledWfRunRequest(id=ScheduledWfRunId(id=lh_schedule_id))
        )
        logger.info("Deleted ScheduledWfRun %s", lh_schedule_id)
    except Exception as exc:
        raise LittleHorseError(
            f"Failed to delete ScheduledWfRun {lh_schedule_id}: {exc}"
        ) from exc
