"""Tiny WfSpec: fire a stored Schedule by id (starts a CampaignRun via the API)."""

from __future__ import annotations

import os

from littlehorse.model.common_wfspec_pb2 import ExponentialBackoffRetryPolicy
from littlehorse.workflow import Workflow, WorkflowThread

FIRE_SCHEDULE_WF_NAME = "fire-scheduled-campaign"

TASK_TIMEOUT_SECONDS = int(os.environ.get("TASK_TIMEOUT_SECONDS", "161"))
TASK_RETRIES = int(os.environ.get("TASK_RETRIES", "3"))


def _retry_policy() -> ExponentialBackoffRetryPolicy:
    return ExponentialBackoffRetryPolicy(
        base_interval_ms=1000,
        max_delay_ms=30_000,
        multiplier=2.0,
    )


def get_workflow() -> Workflow:
    def fire_scheduled_campaign(wf: WorkflowThread) -> None:
        schedule_id = wf.declare_str("schedule-id").required().searchable()
        wf.execute(
            "fire-scheduled-campaign",
            schedule_id,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
            retries=TASK_RETRIES,
            exponential_backoff=_retry_policy(),
        )

    return (
        Workflow(FIRE_SCHEDULE_WF_NAME, fire_scheduled_campaign)
        .with_task_timeout_seconds(TASK_TIMEOUT_SECONDS)
        .with_retry_policy(TASK_RETRIES, _retry_policy())
    )
